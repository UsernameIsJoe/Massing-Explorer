"""
A performance vector, not a quality score.

Hard gate (requirements + limitations) decides legal archive membership.
Soft evaluation among legal schemes uses four composites — Program Coherence,
Preference Alignment, Performance Efficiency, Robustness / Flexibility.

Raw geometry signals (spread, leftover, …) stay for diagnostics and as inputs
to those composites. Courtyard enclosure and EnergyPlus stay omitted until the
drawing can report them. search.py's weighted sum is experimental only.
"""

from __future__ import annotations

from typing import Any

from .descriptors import (
    DESCRIPTOR_FIELDS,
    MIN_SPLIT_PART_SF,
    MIN_SPLIT_PART_SQM,
    OPTIONAL_DESCRIPTOR_FIELDS,
    PUBLIC_TOKENS,
    _anchor_fit,
    _awkward_floor_splits,
    _fragmentation,
    _leftover,
    _likeness,
    _public_on_grade,
    _spread,
    _street_edge,
    awkward_split_violations,
    describe_result,
)

# LEARN / BT axes — soft only; never unlock a must.
EVAL_AXIS_NAMES = (
    "program_coherence",
    "preference_alignment",
    "performance_efficiency",
    "robustness",
)

# Back-compat alias used by novelty_versus_archive / older callers.
TRAIT_KEYS = EVAL_AXIS_NAMES

def _is_hard_gate_check(check: str) -> bool:
    """Site caps, exact requirements, and program-split deal-breakers."""
    name = str(check or "")
    if name.startswith("site_length") or name.startswith("site_width"):
        return True
    if name in {"site_total_length", "site_total_width"} or name.startswith("site_total_"):
        return True
    if name.startswith("required_width") or name.startswith("min_edge"):
        return True
    if name.startswith("ratio_band") or name.startswith("edge_sum"):
        return True
    if name.startswith("program_split"):
        return True
    if name.startswith("step_align") or name.startswith("step_stack"):
        return True
    if name.startswith("step_plate_types") or name.startswith("step_void"):
        return True
    if name.startswith("step_cantilever"):
        return True
    if name.startswith("volume_collision"):
        return True
    return False


def entry_has_awkward_split(entry: dict[str, Any] | None) -> bool:
    """True when performance recorded any awkward multi-floor dept split."""
    if not entry:
        return False
    try:
        return float((entry.get("performance") or {}).get("awkward_splits") or 0.0) > 1e-9
    except (TypeError, ValueError):
        return False


def entry_fragmentation(entry: dict[str, Any] | None) -> float:
    if not entry:
        return 0.0
    try:
        return float((entry.get("performance") or {}).get("fragmentation") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def prefer_clean_splits(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Weird program splits are a deal-breaker — never promote them.

    Contiguous multi-floor stacking is allowed. If every cell is awkward,
    return an empty list (callers show "no legal clean scheme").
    """
    if not entries:
        return entries
    clean = [e for e in entries if not entry_has_awkward_split(e)]
    return clean if clean else []


def measure(result: Any, session: Any = None, archive: dict[str, Any] | None = None) -> dict[str, Any]:
    failed = [c for c in (getattr(result, "validation", None) or []) if not c.passed]
    limit_fails = [c for c in failed if _is_hard_gate_check(str(c.check))]
    descriptors = describe_result(
        result,
        session,
        preference_distance=preference_distance(result, session),
    )
    awkward = float(descriptors["awkward_splits"])
    # Deal breaker: any awkward program split is illegal, even if an older
    # solve path omitted the program_split validation row.
    awkward_fail = awkward > 1e-9
    split_in_limits = any(str(c.check).startswith("program_split") for c in limit_fails)
    effective_limit_fails = len(limit_fails) + (0 if split_in_limits or not awkward_fail else 1)
    anchor_fail = any(str(c.check).startswith("anchor") and not c.passed for c in failed)
    hard_ok = effective_limit_fails == 0
    # One acceptance gate: hard limits + anchors + no remaining validation fails.
    accepted = bool(hard_ok and not anchor_fail and not failed and not awkward_fail)
    vector: dict[str, Any] = {
        "feasible": accepted,
        "accepted": accepted,
        "hard_limits_ok": hard_ok,
        # Archive / search "legal" means fully accepted — not hard-limits alone.
        "fits_limitations": accepted,
        "failed_checks": len(failed) + (0 if split_in_limits or not awkward_fail else 1),
        "limit_fails": effective_limit_fails,
        "failed_kinds": sorted(
            {str(c.check).split(":")[0] for c in failed}
            | ({"program_split"} if awkward_fail else set())
        ),
        # Canonical nested record. Flat fields below remain for stored-study,
        # UI, and plugin compatibility during the layer migration.
        "descriptors": descriptors,
        **descriptors,
    }
    if "street_edge" in descriptors:
        # Diagnostic only — a length/frontage cap is not a fill target.
        vector["street_edge_role"] = "diagnostic"

    vector.update(evaluate_descriptors(descriptors, session))
    if descriptors.get("robustness_status") is not None:
        vector["robustness_status"] = descriptors["robustness_status"]
    vector["novelty"] = novelty_versus_archive(vector, archive)
    from .feasibility import attach_feasibility

    attach_feasibility(vector, result, session, awkward=awkward_fail)
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in vector.items()}


def evaluate_descriptors(
    descriptors: dict[str, Any], session: Any = None
) -> dict[str, float]:
    """Map realized descriptors to four soft axes; legality stays separate."""
    # Fragmentation here means disrupted (non-contiguous) stacks only.
    frag = float(descriptors.get("fragmentation") or 0.0)
    public = descriptors.get("public_on_grade")
    public_score = float(public) if public is not None else 0.7
    program_coherence = 0.40 * (1.0 - min(1.0, frag)) + 0.60 * public_score

    pref_dist = float(descriptors.get("preference_distance") or 0.0)
    preference_alignment = 1.0 - min(1.0, max(0.0, pref_dist))

    leftover = float(descriptors.get("leftover_area") or 0.0)
    likeness = float(
        descriptors.get("footprint_likeness")
        if descriptors.get("footprint_likeness") is not None
        else 0.5
    )
    # Frontage fill is diagnostic only — a length cap is not a target.
    performance_efficiency = 0.65 * (1.0 - leftover) + 0.35 * likeness

    robustness = _robustness_score(descriptors, session)

    return {
        "program_coherence": max(0.0, min(1.0, program_coherence)),
        "preference_alignment": max(0.0, min(1.0, preference_alignment)),
        "performance_efficiency": max(0.0, min(1.0, performance_efficiency)),
        "robustness": max(0.0, min(1.0, robustness)),
    }


def eval_composites(vector: dict[str, Any], session: Any = None) -> dict[str, float]:
    """Compatibility entry point accepting flat or nested descriptor records."""
    nested = vector.get("descriptors")
    descriptors = nested if isinstance(nested, dict) else vector
    # Preserve explicit probe metadata supplied on the legacy flat record.
    for key in ("_robustness_probe", "robustness_status"):
        if key in vector and key not in descriptors:
            descriptors[key] = vector[key]
    evaluated = evaluate_descriptors(descriptors, session)
    if descriptors.get("robustness_status") is not None:
        vector["robustness_status"] = descriptors["robustness_status"]
    return evaluated


def preference_distance(result: Any, session: Any = None) -> float:
    """0 matches stated preferences. 1 is far. Unused until the user compares."""
    if session is None:
        return 0.0
    scores: list[float] = []
    pins = dict(getattr(session, "floor_pins", None) or {})
    levels = _department_levels(result)
    for dept, want in pins.items():
        got = levels.get(dept)
        if got is None:
            scores.append(1.0)
        else:
            scores.append(0.0 if int(got) == int(want) else min(1.0, abs(int(got) - int(want)) / 3.0))
    from ..aspect import aspect_band_distance, aspect_target_distance

    ratio = session.constraints.get("length_over_width")
    if ratio:
        want = float(ratio)
        for mass in getattr(result, "masses", None) or []:
            floors = list(getattr(mass, "floors", None) or [])
            if not floors or not floors[0].width_ft:
                continue
            actual = float(floors[0].length_ft) / float(floors[0].width_ft)
            # 3:5 and 5:3 score the same.
            scores.append(aspect_target_distance(actual, want))
    band = session.constraints.get("ratio_band")
    band_role = str(session.constraints.get("ratio_band_role") or "limitation")
    if isinstance(band, (list, tuple)) and len(band) >= 2 and band_role == "preference":
        try:
            lo = float(band[0])
            hi = float(band[1])
        except (TypeError, ValueError):
            lo = hi = None
        if lo is not None and hi is not None:
            for mass in getattr(result, "masses", None) or []:
                floors = list(getattr(mass, "floors", None) or [])
                if not floors or not floors[0].width_ft:
                    continue
                actual = float(floors[0].length_ft) / float(floors[0].width_ft)
                scores.append(aspect_band_distance(actual, lo, hi))
    for rel in session.constraints.get("stack_above") or []:
        if not isinstance(rel, dict):
            continue
        above = levels.get(str(rel.get("above") or ""))
        below = levels.get(str(rel.get("below") or ""))
        if above is None or below is None:
            scores.append(1.0)
        elif int(above) > int(below):
            scores.append(0.0)
        else:
            scores.append(min(1.0, (int(below) - int(above) + 1) / 3.0))
    preferred_stories = session.constraints.get("preferred_stories")
    if preferred_stories is not None:
        want = max(1, int(round(float(preferred_stories))))
        locks = dict(session.constraints.get("story_lock") or {})
        for mass in getattr(result, "masses", None) or []:
            mass_id = str(getattr(mass, "id", "") or "")
            if mass_id and mass_id in locks:
                continue
            floors = list(getattr(mass, "floors", None) or [])
            if not floors:
                continue
            got = len(floors)
            scores.append(min(1.0, abs(got - want) / max(float(want), 1.0)))
    briefing = session.constraints.get("briefing") or {}
    for clause in briefing.get("preferences") or []:
        lever = str(clause.get("lever") or "")
        text = str(clause.get("text") or "").lower()
        if lever == "low_rise" or (
            lever in {"scheme_preference", "elongated", "loose", "looser", "spread"}
            and any(w in text for w in ("low", "loose", "elongat", "spread"))
        ):
            stories = [
                len(list(m.floors or []))
                for m in (getattr(result, "masses", None) or [])
                if m.floors
            ]
            if stories:
                scores.append(min(1.0, max(0.0, (max(stories) - 2) / 3.0)))
        if lever == "compact" or (
            lever in {"scheme_preference", "smaller_footprint"}
            and ("compact" in text or "small" in text)
        ):
            aspects: list[float] = []
            for mass in getattr(result, "masses", None) or []:
                floors = list(getattr(mass, "floors", None) or [])
                if not floors or not floors[0].width_ft:
                    continue
                w = float(floors[0].width_ft or 0)
                length = float(floors[0].length_ft or 0)
                if w <= 0:
                    continue
                asp = length / w
                aspects.append(max(asp, 1.0 / asp if asp else 1.0))
            if aspects:
                mean_asp = sum(aspects) / len(aspects)
                # Prefer squarer / more compact plates.
                scores.append(min(1.0, max(0.0, (mean_asp - 1.0) / 3.0)))
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def novelty_versus_archive(vector: dict[str, Any], archive: dict[str, Any] | None) -> float:
    """1 is unlike anything already legal in the archive. 0 is a duplicate eval point."""
    if not archive:
        return 1.0
    others = [
        e.get("performance") or {}
        for e in (archive.get("cells") or {}).values()
        if e.get("fits_limitations")
    ]
    if not others:
        return 1.0
    here = _trait_point(vector)
    nearest = min(_euclid(here, _trait_point(p)) for p in others)
    return min(1.0, nearest)


def _trait_point(vector: dict[str, Any]) -> tuple[float, ...]:
    return tuple(float(vector.get(name, 0.0) or 0.0) for name in EVAL_AXIS_NAMES)


def _euclid(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _robustness_score(vector: dict[str, Any], session: Any = None) -> float:
    """Explicit probe when present; otherwise a labeled-untested mid proxy — never 1.0."""
    if vector.get("_robustness_probe") is not None:
        return float(vector["_robustness_probe"])
    status = str(vector.get("robustness_status") or "untested")
    leftover = float(vector.get("leftover_area") or 0.0)
    # Untested → mid headroom from leftover only. Full utilization ≠ proven robust.
    proxy = max(0.0, min(1.0, 0.50 + 0.25 * (1.0 - leftover) - 0.15 * leftover))
    if status != "probed":
        vector["robustness_status"] = "untested"
    return proxy


def _department_levels(result: Any) -> dict[str, int]:
    levels: dict[str, int] = {}
    for mass in getattr(result, "masses", None) or []:
        for floor in getattr(mass, "floors", None) or []:
            level = int(getattr(floor, "level", 0) or 0)
            for alloc in getattr(floor, "allocations", None) or []:
                name = str(alloc.department)
                levels[name] = min(level, levels.get(name, level))
    return levels
