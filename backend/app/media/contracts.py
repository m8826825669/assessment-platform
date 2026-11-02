from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from app.question_bank.contracts import Label


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Reserve(Input):
    filename: Annotated[str, Field(strict=True, min_length=1, max_length=160)]
    mime_type: Literal["image/png", "image/jpeg"]
    description: Annotated[Label, Field(max_length=1000)]

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value):
        if not value.strip() or any(c in value for c in "/\\\r\n\x00") or value.startswith("."):
            raise ValueError("Use a plain filename")
        return value

    @field_validator("description")
    @classmethod
    def meaningful_description(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("Describe the image for users who cannot see it")
        return value


class Fence(Input):
    expected_revision: Annotated[StrictInt, Field(ge=1, le=2147483646)]


class Attachments(Input):
    media_ids: Annotated[tuple[UUID, ...], Field(max_length=16)] = ()

    @field_validator("media_ids")
    @classmethod
    def distinct(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Media references must be distinct")
        return value
