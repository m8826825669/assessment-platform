import json
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.audit.service import clean_state
from app.db.models import ConsumerReceipt, OutboxDelivery, OutboxEvent

CONSUMER = "audit_receipt_v1"


class PermanentFailure(ValueError):
    pass


class LeaseExpired(RuntimeError):
    pass


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int
    event_id: str
    audit_id: str
    tenant_id: str | None
    action: str
    subject_id: str | None
    request_id: str | None
    before: dict
    after: dict


def validate_event(event: OutboxEvent) -> dict:
    try:
        payload = EventPayload.model_validate(event.payload).model_dump()
        if (
            event.event_type != "audit.recorded.v1"
            or payload["schema_version"] != 1
            or payload["event_id"] != str(event.id)
            or payload["audit_id"] != str(event.audit_id)
            or payload["tenant_id"] != (str(event.tenant_id) if event.tenant_id else None)
        ):
            raise ValueError("Event contract mismatch")
        for key in ["subject_id", "request_id"]:
            if payload[key] is not None:
                UUID(payload[key])
        clean_state(payload["action"], payload["before"])
        clean_state(payload["action"], payload["after"])
        return payload
    except (ValidationError, ValueError, TypeError, KeyError) as error:
        raise PermanentFailure("invalid_event") from error


def payload_hash(event: OutboxEvent) -> str:
    payload = validate_event(event)
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def receipt_handler(session, event: OutboxEvent) -> None:
    digest = payload_hash(event)
    session.execute(
        insert(ConsumerReceipt)
        .values(consumer=CONSUMER, event_id=event.id, payload_hash=digest)
        .on_conflict_do_nothing(index_elements=["consumer", "event_id"])
    )
    existing = session.get(ConsumerReceipt, (CONSUMER, event.id))
    if existing.payload_hash != digest:
        raise PermanentFailure("receipt_mismatch")


def retry_delay(attempt: int, base: int = 2) -> int:
    if not 1 <= attempt <= 20 or not 1 <= base <= 60:
        raise ValueError("Invalid retry policy input")
    return min(base * (2 ** (attempt - 1)), 3600)


@dataclass(frozen=True)
class Claim:
    event_id: UUID
    token: UUID


class Worker:
    def __init__(self, sessions, *, lease_seconds: int = 60, retry_base: int = 2):
        if not 5 <= lease_seconds <= 600 or not 1 <= retry_base <= 60:
            raise ValueError("Invalid worker policy")
        self.sessions = sessions
        self.lease_seconds = lease_seconds
        self.retry_base = retry_base

    def claim(self) -> Claim | None:
        with self.sessions() as session, session.begin():
            now = session.scalar(select(func.clock_timestamp()))
            exhausted = list(
                session.scalars(
                    select(OutboxDelivery)
                    .where(
                        OutboxDelivery.status == "processing",
                        OutboxDelivery.lease_expires_at <= now,
                        OutboxDelivery.attempts >= OutboxDelivery.max_attempts,
                    )
                    .order_by(OutboxDelivery.event_id)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            )
            for job in exhausted:
                job.status, job.lease_token, job.lease_expires_at = "dead", None, None
                job.last_error_code = "lease_exhausted"
            job = session.scalar(
                select(OutboxDelivery)
                .where(
                    OutboxDelivery.attempts < OutboxDelivery.max_attempts,
                    or_(
                        and_(OutboxDelivery.status == "pending", OutboxDelivery.available_at <= now),
                        and_(OutboxDelivery.status == "processing", OutboxDelivery.lease_expires_at <= now),
                    ),
                )
                .order_by(OutboxDelivery.available_at, OutboxDelivery.event_id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if job is None:
                return None
            lease_start = session.scalar(select(func.clock_timestamp()))
            token = uuid4()
            job.status, job.attempts = "processing", job.attempts + 1
            job.lease_token, job.lease_expires_at = token, lease_start + timedelta(seconds=self.lease_seconds)
            return Claim(job.event_id, token)

    def _current(self, session, claim: Claim):
        job = session.scalar(
            select(OutboxDelivery)
            .where(
                OutboxDelivery.event_id == claim.event_id,
                OutboxDelivery.status == "processing",
                OutboxDelivery.lease_token == claim.token,
            )
            .with_for_update()
        )
        now = session.scalar(select(func.clock_timestamp()))
        return (job, now) if job is not None and job.lease_expires_at > now else (None, now)

    def process(self, claim: Claim, handler=receipt_handler) -> str:
        try:
            with self.sessions() as session, session.begin():
                job, now = self._current(session, claim)
                if job is None:
                    return "stale"
                event = session.get(OutboxEvent, claim.event_id)
                validate_event(event)
                handler(session, event)  # Only transactional local DB handlers are supported in this release.
                if session.scalar(select(func.clock_timestamp())) >= job.lease_expires_at:
                    raise LeaseExpired()
                job.status, job.delivered_at = "delivered", session.scalar(select(func.clock_timestamp()))
                job.lease_token, job.lease_expires_at, job.last_error_code = None, None, None
            return "delivered"
        except LeaseExpired:
            return "stale"  # Transaction including the receipt was rolled back.
        except Exception as error:
            permanent = isinstance(error, PermanentFailure)
            with self.sessions() as session, session.begin():
                job, now = self._current(session, claim)
                if job is None:
                    return "stale"
                job.status = "dead" if permanent or job.attempts >= job.max_attempts else "pending"
                job.available_at = now + timedelta(seconds=retry_delay(job.attempts, self.retry_base))
                job.lease_token, job.lease_expires_at = None, None
                job.last_error_code = "invalid_event" if permanent else "handler_failed"
                return job.status

    def run_once(self, limit: int = 100) -> dict[str, int]:
        if not 1 <= limit <= 1000:
            raise ValueError("Limit must be between 1 and 1000")
        results: dict[str, int] = {}
        for _ in range(limit):
            claim = self.claim()
            if claim is None:
                break
            outcome = self.process(claim)
            results[outcome] = results.get(outcome, 0) + 1
        return results
