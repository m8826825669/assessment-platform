"""Validate fixed exam selections against section size and saved taxonomy."""

from dataclasses import dataclass
from typing import Mapping
from uuid import UUID


@dataclass(frozen=True)
class CoverageRule:
    term_id: UUID
    minimum: int
    maximum: int


@dataclass(frozen=True)
class Section:
    version_ids: tuple[UUID, ...]
    minimum: int
    maximum: int
    coverage: tuple[CoverageRule, ...] = ()


@dataclass(frozen=True)
class ApprovedSelection:
    question_id: UUID
    term_ids: frozenset[UUID]


@dataclass(frozen=True)
class Diagnostic:
    code: str
    section_index: int
    rule_index: int | None = None
    selection_index: int | None = None
    minimum: int | None = None
    maximum: int | None = None
    observed: int | None = None


def validate_blueprint(
    sections: tuple[Section, ...], approved: Mapping[UUID, ApprovedSelection]
) -> tuple[Diagnostic, ...]:
    """Use an eligibility map supplied by the caller for the current tenant."""
    if not sections:
        return (Diagnostic("sections_required", 0),)

    diagnostics: list[Diagnostic] = []
    for index, section in enumerate(sections):
        if not 0 <= section.minimum <= section.maximum:
            diagnostics.append(Diagnostic("invalid_section_bounds", index))
        for rule_index, rule in enumerate(section.coverage):
            if not 0 <= rule.minimum <= rule.maximum:
                diagnostics.append(Diagnostic("invalid_coverage_bounds", index, rule_index))
    if diagnostics:
        return tuple(diagnostics)

    seen: set[UUID] = set()
    for index, section in enumerate(sections):
        count = len(section.version_ids)
        if not section.minimum <= count <= section.maximum:
            diagnostics.append(
                Diagnostic(
                    "section_count",
                    index,
                    minimum=section.minimum,
                    maximum=section.maximum,
                    observed=count,
                )
            )
        selections: list[ApprovedSelection] = []
        for position, version_id in enumerate(section.version_ids):
            selection = approved.get(version_id)
            if selection is None:
                diagnostics.append(Diagnostic("selection_unavailable", index, selection_index=position))
            elif selection.question_id in seen:
                diagnostics.append(Diagnostic("duplicate_question", index, selection_index=position))
            else:
                seen.add(selection.question_id)
                selections.append(selection)

        # Incomplete selections cannot establish the section's coverage.
        if len(selections) != count:
            continue
        for rule_index, rule in enumerate(section.coverage):
            observed = sum(rule.term_id in selection.term_ids for selection in selections)
            if not rule.minimum <= observed <= rule.maximum:
                diagnostics.append(
                    Diagnostic(
                        "coverage_count",
                        index,
                        rule_index,
                        minimum=rule.minimum,
                        maximum=rule.maximum,
                        observed=observed,
                    )
                )
    return tuple(diagnostics)
