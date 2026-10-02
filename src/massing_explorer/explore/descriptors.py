"""Realized scheme descriptors shared by evaluation, diagnostics, and search.

Strategy coordinates describe what the search asked for. These descriptors
describe what the solver actually produced. They contain no quality judgment:
evaluation maps this record to soft quality axes; legality is a separate gate.
"""

from __future__ import annotations

from statistics import pstdev
from typing import Any

PUBLIC_TOKENS = ("health", "physical", "dining", "food", "art", "music", "gym")

# Every slice of a multi-floor department must be at least this large.
MIN_SPLIT_PART_SQM = 70.0
_SQM_TO_SF = 10.76391041671
MIN_SPLIT_PART_SF = MIN_SPLIT_PART_SQM * _SQM_TO_SF

# Stable fields on every realized descriptor record. Optional site- or
# program-dependent fields are listed separately.
DESCRIPTOR_FIELDS = (
    "mass_count",
    "ground_footprint_area",
    "total_floor_area",
    "mean_height",
    "max_height",
    "spread",
    "height_variance",
    "footprint_likeness",
    "lengths",
    "preference_distance",
    "leftover_area",
    "fragmentation",
    "awkward_splits",
    "anchor_fit",
)
OPTIONAL_DESCRIPTOR_FIELDS = ("street_edge", "public_on_grade")


def describe_result(
    result: Any,
    session: Any = None,
    *,
    preference_distance: float = 0.0,
) -> dict[str, Any]:
    """Return judgment-free properties of one realized solver result."""
    masses = list(getattr(result, "masses", None) or [])
    validation = list(getattr(result, "validation", None) or [])
    failed = [check for check in validation if not check.passed]
    areas: list[float] = []
    stories: list[float] = []
    aspects: list[float] = []
    lengths: list[float] = []
    total_floor_area = 0.0

    for mass in masses:
        floors = list(getattr(mass, "floors", None) or [])
        if not floors:
            continue
        ground = floors[0]
        width = float(ground.width_ft or 0)
        length = float(ground.length_ft or 0)
        areas.append(max(0.0, width * length))
        stories.append(float(len(floors)))
        aspects.append(length / width if width else 0.0)
        lengths.append(length)
        for floor in floors:
            floor_width = float(getattr(floor, "width_ft", 0) or 0)
            floor_length = float(getattr(floor, "length_ft", 0) or 0)
            total_floor_area += max(0.0, floor_width * floor_length)

    descriptor: dict[str, Any] = {
        "mass_count": len(masses),
        "ground_footprint_area": sum(areas),
        "total_floor_area": total_floor_area,
        "mean_height": sum(stories) / len(stories) if stories else 0.0,
        "max_height": max(stories) if stories else 0.0,
        "spread": _spread(areas),
        "height_variance": float(pstdev(stories)) if len(stories) > 1 else 0.0,
        "footprint_likeness": _likeness(aspects),
        "lengths": [round(value, 1) for value in lengths],
        "preference_distance": float(preference_distance),
        "leftover_area": _leftover(masses),
        "fragmentation": _fragmentation(masses),
        "awkward_splits": _awkward_floor_splits(masses),
        "anchor_fit": _anchor_fit(failed, validation),
    }
    edge = _street_edge(masses, session)
    if edge is not None:
        descriptor["street_edge"] = edge
    public = _public_on_grade(masses)
    if public is not None:
        descriptor["public_on_grade"] = public
    return descriptor


def _spread(areas: list[float]) -> float:
    total = sum(areas)
    if total <= 0 or len(areas) < 2:
        return 0.0
    return 1.0 - (max(areas) / total)


def _likeness(values: list[float]) -> float:
    if len(values) < 2:
        return 1.0
    mean = sum(values) / len(values)
    if abs(mean) <= 1e-9:
        return 1.0
    mad = sum(abs(value - mean) for value in values) / len(values)
    return max(0.0, 1.0 - mad / mean)


def _street_edge(masses: list[Any], session: Any) -> float | None:
    if session is None:
        return None
    frontage = session.constraints.get("max_total_length_ft")
    if not frontage:
        return None
    used = 0.0
    for mass in masses:
        floors = list(getattr(mass, "floors", None) or [])
        if floors:
            used += float(floors[0].length_ft or 0)
    return min(1.0, used / float(frontage)) if float(frontage) > 0 else None


def _leftover(masses: list[Any]) -> float:
    """Unused share of usable floor. Measured, not a quality score."""
    usable = 0.0
    allocated = 0.0
    for mass in masses:
        for floor in getattr(mass, "floors", None) or []:
            usable += float(getattr(floor, "usable_area_sf", 0) or 0)
            allocated += float(getattr(floor, "allocated_gsf", 0) or 0)
    if usable <= 0:
        return 0.0
    return max(0.0, 1.0 - allocated / usable)


def _fragmentation(masses: list[Any]) -> float:
    """Share of departments with disrupted, rather than contiguous, stacks."""
    floors_of: dict[str, set[int]] = {}
    for mass in masses:
        for floor in getattr(mass, "floors", None) or []:
            level = int(getattr(floor, "level", 0) or 0)
            for allocation in getattr(floor, "allocations", None) or []:
                floors_of.setdefault(str(allocation.department), set()).add(level)
    if not floors_of:
        return 0.0
    disrupted = 0
    for levels in floors_of.values():
        if len(levels) <= 1:
            continue
        ordered = sorted(levels)
        if ordered[-1] - ordered[0] + 1 != len(ordered):
            disrupted += 1
    return disrupted / len(floors_of)


def _awkward_floor_splits(masses: list[Any]) -> float:
    """Share of multi-floor departments with an illegal vertical split."""
    awkward = 0
    multi = 0
    for mass in masses:
        by_dept: dict[str, dict[int, float]] = {}
        for floor in getattr(mass, "floors", None) or []:
            level = int(getattr(floor, "level", 0) or 0)
            for allocation in getattr(floor, "allocations", None) or []:
                department = str(allocation.department)
                gsf = float(allocation.gsf or 0)
                if gsf <= 0:
                    continue
                by_dept.setdefault(department, {})[level] = (
                    by_dept.setdefault(department, {}).get(level, 0.0) + gsf
                )
        for levels in by_dept.values():
            if len(levels) < 2:
                continue
            multi += 1
            ordered = sorted(levels)
            contiguous = ordered[-1] - ordered[0] + 1 == len(ordered)
            thin = any(gsf + 1e-6 < MIN_SPLIT_PART_SF for gsf in levels.values())
            if not contiguous or thin:
                awkward += 1
    return awkward / multi if multi else 0.0


def awkward_split_violations(masses: list[Any]) -> list[dict[str, Any]]:
    """Per-department deal-breaker details for validation and UI."""
    out: list[dict[str, Any]] = []
    for mass in masses:
        mass_id = str(getattr(mass, "id", "") or "")
        mass_name = str(getattr(mass, "name", "") or mass_id or "Mass")
        by_dept: dict[str, dict[int, float]] = {}
        for floor in getattr(mass, "floors", None) or []:
            level = int(getattr(floor, "level", 0) or 0)
            for allocation in getattr(floor, "allocations", None) or []:
                department = str(allocation.department)
                gsf = float(allocation.gsf or 0)
                if gsf <= 0:
                    continue
                by_dept.setdefault(department, {})[level] = (
                    by_dept.setdefault(department, {}).get(level, 0.0) + gsf
                )
        for department, levels in by_dept.items():
            if len(levels) < 2:
                continue
            ordered = sorted(levels)
            contiguous = ordered[-1] - ordered[0] + 1 == len(ordered)
            reasons: list[str] = []
            if not contiguous:
                reasons.append(
                    "non-contiguous floors " + "+".join(f"L{level}" for level in ordered)
                )
            thin_levels = [
                (level, gsf)
                for level, gsf in sorted(levels.items())
                if gsf + 1e-6 < MIN_SPLIT_PART_SF
            ]
            if thin_levels:
                bits = ", ".join(
                    f"L{level}={gsf:,.0f} SF ({gsf / _SQM_TO_SF:.0f} m²)"
                    for level, gsf in thin_levels
                )
                reasons.append(
                    f"split slice under {MIN_SPLIT_PART_SQM:g} m² ({bits})"
                )
            if reasons:
                out.append(
                    {
                        "mass_id": mass_id,
                        "mass_name": mass_name,
                        "department": department,
                        "levels": ordered,
                        "reasons": reasons,
                    }
                )
    return out


def _public_on_grade(masses: list[Any]) -> float | None:
    total = 0.0
    ground = 0.0
    found = False
    for mass in masses:
        for floor in getattr(mass, "floors", None) or []:
            level = int(getattr(floor, "level", 0) or 0)
            for allocation in getattr(floor, "allocations", None) or []:
                name = str(allocation.department).lower()
                if not any(token in name for token in PUBLIC_TOKENS):
                    continue
                found = True
                gsf = float(allocation.gsf or 0)
                total += gsf
                if level == 0:
                    ground += gsf
    if not found or total <= 0:
        return None
    return ground / total


def _anchor_fit(failed: list[Any], all_checks: list[Any]) -> float:
    anchors = [
        check
        for check in all_checks
        if str(getattr(check, "check", "")).startswith("anchor")
    ]
    if not anchors:
        return 1.0
    passed = sum(1 for check in anchors if getattr(check, "passed", False))
    return passed / len(anchors)
