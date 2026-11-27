"""Build the immutable payload for a fixed pilot exam publication."""

from copy import deepcopy
from typing import Mapping
from uuid import UUID

from assessment_core.blueprint import ApprovedSelection, Section, validate_blueprint


def build_snapshot(
    sections: tuple[Section, ...],
    approved: Mapping[UUID, ApprovedSelection],
    public_items: Mapping[UUID, dict],
    grading_items: Mapping[UUID, dict],
) -> dict:
    """Build from exact-version records loaded by the publication transaction.

    The public records must use the explicit question projection. Grading records
    are stored separately from candidate content and must never be returned to candidates.
    """
    if validate_blueprint(sections, approved):
        raise ValueError("Invalid exam blueprint")

    return {
        "schema_version": 1,
        "policy": {
            "duration_minutes": 30,
            "item_weight": "1",
            "negative_marks": "0",
            "unanswered_points": "0",
            "invalid_items": "exclude",
            "percentage_decimal_places": 2,
            "percentage_rounding": "half_up",
            "zero_available_points": "no_percentage",
        },
        "sections": [
            {
                "minimum": section.minimum,
                "maximum": section.maximum,
                "coverage": [
                    {"term_id": str(rule.term_id), "minimum": rule.minimum, "maximum": rule.maximum}
                    for rule in section.coverage
                ],
                "items": [
                    {"version_id": str(version_id), "snapshot": deepcopy(public_items[version_id])}
                    for version_id in section.version_ids
                ],
            }
            for section in sections
        ],
        "grading": {
            str(version_id): deepcopy(grading_items[version_id])
            for section in sections
            for version_id in section.version_ids
        },
    }
