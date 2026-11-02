from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping
from uuid import uuid4


class RuleViolation(ValueError):
    """A named business rule failed."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuleViolation(code)


def aware(value: datetime) -> None:
    require(value.tzinfo is not None and value.utcoffset() is not None, "timezone_required")


@dataclass(frozen=True)
class Item:
    tenant_id: str
    version_id: str
    prompt: str
    options: tuple[str, ...]
    correct_index: int
    marks: Decimal = Decimal("1")
    approved: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", tuple(self.options))
        require(bool(self.tenant_id and self.version_id and self.prompt.strip()), "invalid_item")
        require(len(self.options) >= 2 and all(x.strip() for x in self.options), "invalid_options")
        require(
            type(self.correct_index) is int and 0 <= self.correct_index < len(self.options), "invalid_key"
        )
        require(
            isinstance(self.marks, Decimal) and self.marks.is_finite() and self.marks > 0, "invalid_marks"
        )

    def candidate_view(self) -> dict:
        return {"version_id": self.version_id, "prompt": self.prompt, "options": list(self.options)}


@dataclass(frozen=True)
class Exam:
    tenant_id: str
    publication_id: str
    items: tuple[Item, ...]
    duration_seconds: int
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        require(bool(self.tenant_id and self.publication_id), "invalid_publication")
        require(type(self.duration_seconds) is int and self.duration_seconds > 0, "invalid_duration")
        require(bool(self.items), "empty_exam")
        require(len({x.version_id for x in self.items}) == len(self.items), "duplicate_item")
        require(all(x.tenant_id == self.tenant_id for x in self.items), "tenant_mismatch")
        require(all(x.approved for x in self.items), "unapproved_item")
        payload = {
            "tenant": self.tenant_id,
            "publication": self.publication_id,
            "duration": self.duration_seconds,
            "items": [
                {
                    "version": x.version_id,
                    "prompt": x.prompt,
                    "options": x.options,
                    "key": x.correct_index,
                    "marks": str(x.marks),
                }
                for x in self.items
            ],
        }
        digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        object.__setattr__(self, "content_hash", digest)


@dataclass(frozen=True)
class SavedResponse:
    item_version_id: str
    choice: int
    revision: int


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    attempt_id: str
    publication_hash: str
    submitted_at: datetime
    responses: tuple[SavedResponse, ...]


class Attempt:
    """Single-process reference rules; callers must supply trusted server time.

    The later persistence adapter must enforce these invariants transactionally.
    This object is not a concurrency-safe store or an authentication boundary.
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        candidate_id: str,
        exam: Exam,
        opens_at: datetime,
        closes_at: datetime,
        now: datetime,
        extra_seconds: int = 0,
    ) -> None:
        for value in (opens_at, closes_at, now):
            aware(value)
        require(tenant_id == exam.tenant_id, "tenant_mismatch")
        require(bool(candidate_id), "candidate_required")
        require(type(extra_seconds) is int and extra_seconds >= 0, "invalid_extra_time")
        require(opens_at < closes_at, "invalid_window")
        require(opens_at <= now < closes_at, "outside_start_window")
        self._tenant_id = tenant_id
        self._candidate_id = candidate_id
        self._exam = exam
        self._attempt_id = str(uuid4())
        self._started_at = now
        self._deadline = min(closes_at, now + timedelta(seconds=exam.duration_seconds + extra_seconds))
        self._responses: dict[str, SavedResponse] = {}
        self._operations: dict[str, tuple[tuple, SavedResponse]] = {}
        self._receipt: Receipt | None = None

    @property
    def deadline(self) -> datetime:
        return self._deadline

    @property
    def responses(self) -> Mapping[str, SavedResponse]:
        return MappingProxyType(self._responses)

    @property
    def receipt(self) -> Receipt | None:
        return self._receipt

    def _authorise(self, tenant_id: str, candidate_id: str) -> None:
        require(tenant_id == self._tenant_id and candidate_id == self._candidate_id, "access_denied")

    def save(
        self,
        *,
        tenant_id: str,
        candidate_id: str,
        item_version_id: str,
        choice: int,
        expected_revision: int,
        operation_key: str,
        now: datetime,
    ) -> SavedResponse:
        self._authorise(tenant_id, candidate_id)
        aware(now)
        require(bool(operation_key), "operation_key_required")
        require(type(expected_revision) is int and expected_revision >= 0, "invalid_revision")
        payload = (item_version_id, choice, expected_revision)
        if operation_key in self._operations:
            previous_payload, previous_result = self._operations[operation_key]
            require(previous_payload == payload, "idempotency_conflict")
            return previous_result
        require(self._receipt is None, "already_submitted")
        require(self._started_at <= now < self._deadline, "outside_answer_window")
        item = next((x for x in self._exam.items if x.version_id == item_version_id), None)
        require(item is not None, "unknown_item")
        require(type(choice) is int and 0 <= choice < len(item.options), "invalid_choice")
        previous = self._responses.get(item_version_id)
        revision = previous.revision if previous else 0
        require(expected_revision == revision, "revision_conflict")
        result = SavedResponse(item_version_id, choice, revision + 1)
        self._responses[item_version_id] = result
        self._operations[operation_key] = (payload, result)
        return result

    def submit(self, *, tenant_id: str, candidate_id: str, now: datetime) -> Receipt:
        self._authorise(tenant_id, candidate_id)
        aware(now)
        if self._receipt is not None:
            return self._receipt
        require(self._started_at <= now < self._deadline, "outside_submission_window")
        self._receipt = Receipt(
            str(uuid4()),
            self._attempt_id,
            self._exam.content_hash,
            now,
            tuple(sorted(self._responses.values(), key=lambda x: x.item_version_id)),
        )
        return self._receipt
