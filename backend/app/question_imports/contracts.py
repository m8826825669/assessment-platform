"""Bounded internal JSON profile; typed body v1 stays unchanged."""

import json
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.question_bank.api import QuestionCreate
from app.question_bank.contracts import Identifier, content_hash

PROFILE = "assessment-question-import.v1"
MAX_BYTES = 2 * 1024 * 1024


class ImportItem(QuestionCreate):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    reference: Identifier


class Batch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    schema_version: Literal["assessment-question-import.v1"]
    items: Annotated[tuple[ImportItem, ...], Field(min_length=1, max_length=50)]

    @model_validator(mode="after")
    def batch_bounds(self):
        if len({item.reference for item in self.items}) != len(self.items):
            raise ValueError("References must be distinct within a batch")
        if sum(len(item.media_ids) for item in self.items) > 16:
            raise ValueError("Use at most 16 media attachment references per batch")
        return self


def fingerprint(batch):
    normalized = {
        "schema_version": batch.schema_version,
        "items": [
            {
                "reference": item.reference,
                "title": item.title,
                "content_hash": content_hash(item.content),
                "taxonomy_ids": sorted(str(i) for i in item.taxonomy_ids),
                "media_ids": sorted(str(i) for i in item.media_ids),
            }
            for item in batch.items
        ],
    }
    return sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def parse(data):
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Invalid document size")

    def distinct(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON property")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("Nonfinite JSON number")

    payload = json.loads(data.decode("utf-8-sig"), object_pairs_hook=distinct, parse_constant=nonfinite)
    pending = [(payload, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > 64:
            raise ValueError("Excessive nesting")
        if isinstance(value, dict):
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)
    return Batch.model_validate(payload)


def safe_errors(error: ValidationError):
    # Do not reflect arbitrary unknown property names, union tag values, input values or validator context.
    schema = Batch.model_json_schema()
    known = {
        "single_choice",
        "multiple_select",
        "numeric",
        "short_answer",
        "essay",
        "file_upload",
        "passage_group",
    }
    pending = [schema]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            known.update(value.get("properties", {}))
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return [
        {
            "loc": (
                "body",
                *(part if type(part) is int or part in known else "unknown_field" for part in entry["loc"]),
            ),
            "type": entry["type"],
            "msg": "Invalid import field",
        }
        for entry in error.errors()[:100]
    ]


def request_schema():
    """Inline the finite content union so manual bounded streaming still has valid OpenAPI body docs."""
    schema = Batch.model_json_schema()
    definitions = schema.pop("$defs", {})

    def expand(value):
        if isinstance(value, dict):
            if "$ref" in value:
                return expand(definitions[value["$ref"].split("/")[-1]])
            return {
                key: ({"propertyName": child["propertyName"]} if key == "discriminator" else expand(child))
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [expand(child) for child in value]
        return value

    return expand(schema)
