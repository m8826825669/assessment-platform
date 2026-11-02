"""P2-001 / QBK-01, QBK-02, PUB-01: validated immutable content and safe previews.

These contracts contain authoring secrets. Never return model_dump() to candidates.
Use candidate_view(). Database version immutability is a later, separate gate.
"""

from __future__ import annotations

import json
import unicodedata
from decimal import Decimal
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    TypeAdapter,
    model_validator,
)


def meaningful_text(value: str) -> str:
    if not value.strip() or any(
        unicodedata.category(character) in {"Cc", "Cs"} and character not in "\t\r\n" for character in value
    ):
        raise ValueError("Nonblank text without control characters is required")
    return value


def exact_decimal(value):
    if type(value) not in (str, int, Decimal):
        raise ValueError("Use a decimal string or integer, never a float or boolean")
    if isinstance(value, str) and len(value) > 64:
        raise ValueError("Decimal representation is too long")
    return value


Identifier = Annotated[str, StringConstraints(strict=True, pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
Text = Annotated[str, StringConstraints(strict=True, max_length=16000), AfterValidator(meaningful_text)]
Label = Annotated[str, StringConstraints(strict=True, max_length=1000), AfterValidator(meaningful_text)]
Points = Annotated[
    Decimal,
    BeforeValidator(exact_decimal),
    Field(gt=0, le=10000, max_digits=7, decimal_places=2, allow_inf_nan=False),
]
Number = Annotated[
    Decimal, BeforeValidator(exact_decimal), Field(max_digits=18, decimal_places=6, allow_inf_nan=False)
]
Tolerance = Annotated[Number, Field(ge=0)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True, hide_input_in_errors=True)


class Option(Contract):
    id: Identifier
    text: Label


class ItemBase(Contract):
    item_id: Identifier
    prompt: Text
    points: Points


class ChoiceBase(ItemBase):
    options: Annotated[tuple[Option, ...], Field(min_length=2, max_length=20)]

    @model_validator(mode="after")
    def unique_options(self):
        if len({option.id for option in self.options}) != len(self.options):
            raise ValueError("Option identifiers must be unique")
        labels = {unicodedata.normalize("NFKC", option.text).strip().casefold() for option in self.options}
        if len(labels) != len(self.options):
            raise ValueError("Option labels must be distinct")
        return self


class SingleChoice(ChoiceBase):
    kind: Literal["single_choice"]
    correct_option_id: Identifier

    @model_validator(mode="after")
    def known_answer(self):
        if self.correct_option_id not in {option.id for option in self.options}:
            raise ValueError("Answer must reference an existing option")
        return self


class MultipleSelect(ChoiceBase):
    kind: Literal["multiple_select"]
    correct_option_ids: Annotated[tuple[Identifier, ...], Field(min_length=1, max_length=20)]
    scoring: Literal["all_or_nothing"] = "all_or_nothing"

    @model_validator(mode="after")
    def known_answers(self):
        answers = set(self.correct_option_ids)
        if len(answers) != len(self.correct_option_ids) or not answers.issubset(
            {option.id for option in self.options}
        ):
            raise ValueError("Answers must be unique existing options")
        return self


class Numeric(ItemBase):
    kind: Literal["numeric"]
    expected: Number
    absolute_tolerance: Tolerance = Decimal("0")
    unit_label: Label | None = None


class Normalization(Contract):
    unicode_form: Literal["NFKC"] = "NFKC"
    case_sensitive: StrictBool = False
    collapse_whitespace: StrictBool = True

    def apply(self, value: str) -> str:
        value = unicodedata.normalize(self.unicode_form, value)
        value = " ".join(value.split()) if self.collapse_whitespace else value.strip()
        return value if self.case_sensitive else value.casefold()


class ShortAnswer(ItemBase):
    kind: Literal["short_answer"]
    accepted_answers: Annotated[tuple[Label, ...], Field(min_length=1, max_length=50)]
    normalization: Normalization = Normalization()
    max_response_characters: Annotated[StrictInt, Field(ge=1, le=4000)] = 1000

    @model_validator(mode="after")
    def distinct_answers(self):
        normalized = {self.normalization.apply(answer) for answer in self.accepted_answers}
        if "" in normalized or len(normalized) != len(self.accepted_answers):
            raise ValueError("Accepted answers must be distinct under the declared normalization")
        if any(len(answer) > self.max_response_characters for answer in self.accepted_answers):
            raise ValueError("Accepted answer exceeds the response limit")
        return self


class Criterion(Contract):
    id: Identifier
    description: Text
    max_points: Points


class ManualBase(ItemBase):
    rubric: Annotated[tuple[Criterion, ...], Field(min_length=1, max_length=30)]
    marker_guidance: Text

    @model_validator(mode="after")
    def rubric_matches_points(self):
        if len({criterion.id for criterion in self.rubric}) != len(self.rubric):
            raise ValueError("Rubric identifiers must be unique")
        if sum((criterion.max_points for criterion in self.rubric), Decimal(0)) != self.points:
            raise ValueError("Rubric points must equal item points")
        return self


class Essay(ManualBase):
    kind: Literal["essay"]
    max_response_characters: Annotated[StrictInt, Field(ge=1, le=100000)] = 20000


class FileUpload(ManualBase):
    kind: Literal["file_upload"]
    allowed_extensions: Annotated[
        tuple[Literal[".pdf", ".txt", ".png", ".jpg", ".jpeg"], ...], Field(min_length=1, max_length=5)
    ]
    max_files: Annotated[StrictInt, Field(ge=1, le=5)] = 1
    max_bytes_per_file: Annotated[StrictInt, Field(ge=1, le=20971520)] = 10485760

    @model_validator(mode="after")
    def distinct_extensions(self):
        if len(set(self.allowed_extensions)) != len(self.allowed_extensions):
            raise ValueError("File extensions must be distinct")
        return self


Leaf = Annotated[
    SingleChoice | MultipleSelect | Numeric | ShortAnswer | Essay | FileUpload, Field(discriminator="kind")
]


class PassageGroup(ItemBase):
    kind: Literal["passage_group"]
    passage: Text
    children: Annotated[tuple[Leaf, ...], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def coherent_children(self):
        identifiers = {child.item_id for child in self.children}
        if len(identifiers) != len(self.children) or self.item_id in identifiers:
            raise ValueError("Group and child identifiers must be distinct")
        if sum((child.points for child in self.children), Decimal(0)) != self.points:
            raise ValueError("Group points must equal child points")
        return self


Content = Annotated[
    SingleChoice | MultipleSelect | Numeric | ShortAnswer | Essay | FileUpload | PassageGroup,
    Field(discriminator="kind"),
]
CONTENT_ADAPTER = TypeAdapter(Content)


def validate_content(payload: dict) -> Content:
    """Validate untrusted authoring content; callers still enforce tenant and role authority."""
    return CONTENT_ADAPTER.validate_python(payload)


def candidate_view(item: Content) -> dict:
    """Explicit allowlist, recursively applied; this is not an authorization or delivery endpoint."""
    view = {"kind": item.kind, "item_id": item.item_id, "prompt": item.prompt, "points": str(item.points)}
    if isinstance(item, ChoiceBase):
        view["options"] = [{"id": option.id, "text": option.text} for option in item.options]
    if isinstance(item, Numeric):
        view["unit_label"] = item.unit_label
    if isinstance(item, (ShortAnswer, Essay)):
        view["max_response_characters"] = item.max_response_characters
    if isinstance(item, FileUpload):
        view.update(
            allowed_extensions=list(item.allowed_extensions),
            max_files=item.max_files,
            max_bytes_per_file=item.max_bytes_per_file,
        )
    if isinstance(item, PassageGroup):
        view.update(passage=item.passage, children=[candidate_view(child) for child in item.children])
    return view


def content_hash(item: Content) -> str:
    """Fingerprint all authoring fields under schema v1; not a signature or approval record."""

    def canonical_value(value):
        if isinstance(value, Decimal):
            if value == 0:
                return "0"
            result = format(value, "f")
            return result.rstrip("0").rstrip(".") if "." in result else result
        if isinstance(value, dict):
            return {key: canonical_value(child) for key, child in value.items()}
        if isinstance(value, (tuple, list)):
            return [canonical_value(child) for child in value]
        return value

    envelope = {"schema_version": "question-content.v1", "content": canonical_value(item.model_dump())}
    canonical = json.dumps(
        envelope, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    )
    return sha256(canonical.encode("utf-8")).hexdigest()
