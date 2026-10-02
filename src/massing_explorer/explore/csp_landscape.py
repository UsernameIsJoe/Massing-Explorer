"""Cheap, reproducible reading and sampling of the CSP partition landscape.

This module owns the stage *before* the init-P shortlist.  It deliberately
does not rank final organizations.  Instead it:

1. samples every allowed mass-count stratum across its full combinatorial
   extent (rather than accepting a depth-first prefix),
2. describes each sampled partition with factual, label-invariant coordinates,
3. groups nearby descriptions into readable regions, and
4. protects broad coverage before using the brief to allocate extra samples.

The sampler is pseudo-random only as a space-filling mechanism.  Its seed is a
stable digest of the atoms and constraints, so identical inputs produce the
same landscape and the same downstream shortlist.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
import hashlib
import heapq
import math
import random
from typing import Any


PROPOSAL_MULTIPLIER = 1.6
COVERAGE_FLOOR_SHARE = 0.25
ATTENTION_WEIGHTS = {
    "brief_relevance": 0.45,
    "capacity_plausibility": 0.35,
    "uncertainty": 0.20,
}
REGION_WEIGHTS = {"mean_attention": 0.85, "rarity": 0.15}
MIN_REGION_MAX_SHARE = 0.35
REGION_SHARE_HEADROOM = 0.15


def stirling_second(n: int, k: int) -> int:
    """Number of partitions of ``n`` labeled atoms into ``k`` nonempty sets."""
    if n < 0 or k < 0 or k > n:
        return 0
    row = [0] * (k + 1)
    row[0] = 1
    for size in range(1, n + 1):
        nxt = [0] * (k + 1)
        for blocks in range(1, min(size, k) + 1):
            nxt[blocks] = row[blocks - 1] + blocks * row[blocks]
        row = nxt
    return row[k]


def build_partition_landscape(
    atoms: list[dict[str, Any]],
    *,
    k_min: int,
    k_max: int,
    apart_pairs: list[tuple[int, int]],
    budget: int,
    preferred_mass_count: int | None = None,
    session: Any | None = None,
    records_out: list[dict[str, Any]] | None = None,
) -> tuple[list[list[int]], list[list[int]], dict[str, Any]]:
    """Return the pre-shortlist sample, rejected examples, and diagnostics.

    Small spaces are still exhaustively enumerated.  Large spaces use a stable
    space-wide proposal stream, then descriptor-region allocation.  The second
    returned list contains a few keep-apart failures for the existing report.
    """
    n = len(atoms)
    budget = max(1, int(budget))
    totals = {k: stirling_second(n, k) for k in range(k_min, k_max + 1)}
    unconstrained_total = sum(totals.values())
    seed_text = _seed_text(atoms, apart_pairs, k_min, k_max)

    if unconstrained_total <= budget:
        feasible: list[list[int]] = []
        rejected: list[list[int]] = []
        strata: dict[int, dict[str, Any]] = {}
        for k in range(k_min, k_max + 1):
            checked = valid = 0
            for assign in _restricted_growth_fixed(n, k):
                checked += 1
                if _respects_apart(assign, apart_pairs):
                    feasible.append(assign)
                    valid += 1
                elif len(rejected) < 4:
                    rejected.append(assign)
            strata[k] = _stratum_report(
                total=totals[k],
                checked=checked,
                valid=valid,
                proposed=valid,
                retained=valid,
                exact=True,
            )
        records = [
            _selection_record(atoms, assign, session, preferred_mass_count, seed_text)
            for assign in feasible
        ]
        if records_out is not None:
            records_out.extend(records)
        regions = _region_report(records, records)
        return feasible, rejected, {
            "method": "exhaustive",
            "deterministic": True,
            "space_unconstrained": unconstrained_total,
            "feasible_count_exact": True,
            "estimated_feasible_count": len(feasible),
            "proposal_budget": unconstrained_total,
            "proposal_attempts": unconstrained_total,
            "proposal_unique_checked": unconstrained_total,
            "sample_budget": budget,
            "sampled": len(feasible),
            "coverage_floor_share": 1.0,
            "brief_conditioned": False,
            "policy": _policy_report(),
            "strata": strata,
            "regions": regions,
            "stopping_reason": "entire bounded partition space was evaluated",
        }

    proposal_budget = max(budget, int(math.ceil(budget * PROPOSAL_MULTIPLIER)))
    quotas = _proposal_quotas(
        totals,
        proposal_budget,
        preferred=preferred_mass_count,
    )
    proposals: list[list[int]] = []
    rejected = []
    strata = {}
    total_attempts = 0
    total_unique_checked = 0
    for k in range(k_min, k_max + 1):
        target = min(int(quotas.get(k, 0)), totals[k])
        found, failed, stats = _sample_stratum(
            n,
            k,
            target=target,
            total=totals[k],
            apart_pairs=apart_pairs,
            seed_text=seed_text,
        )
        proposals.extend(found)
        for assign in failed:
            if len(rejected) < 4:
                rejected.append(assign)
        total_attempts += int(stats["attempts"])
        total_unique_checked += int(stats["checked"])
        strata[k] = _stratum_report(
            total=totals[k],
            checked=int(stats["checked"]),
            valid=len(found),
            proposed=len(found),
            retained=0,
            exact=bool(stats["exact"]),
        )

    records = [
        _selection_record(atoms, assign, session, preferred_mass_count, seed_text)
        for assign in proposals
    ]
    selected_records = _allocate_landscape(records, budget)
    if records_out is not None:
        records_out.extend(selected_records)
    selected = [record["assignment"] for record in selected_records]
    retained_by_k: dict[int, int] = defaultdict(int)
    for record in selected_records:
        retained_by_k[int(record["descriptor"]["structure"]["mass_count"])] += 1
    for k, count in retained_by_k.items():
        strata[k]["retained"] = count

    estimate = 0.0
    estimate_confidence = "low"
    enough = 0
    for k, row in strata.items():
        checked = int(row["unique_checked"])
        rate = float(row["observed_valid_rate"])
        estimate += totals[k] * rate
        enough += checked
    if enough >= 5000:
        estimate_confidence = "high"
    elif enough >= 500:
        estimate_confidence = "medium"

    return selected, rejected, {
        "method": "deterministic_stratified_landscape",
        "deterministic": True,
        "space_unconstrained": unconstrained_total,
        "feasible_count_exact": False,
        "estimated_feasible_count": int(round(estimate)),
        "estimate_confidence": estimate_confidence,
        "proposal_budget": proposal_budget,
        "proposal_attempts": total_attempts,
        "proposal_unique_checked": total_unique_checked,
        "sample_budget": budget,
        "sampled": len(selected),
        "coverage_floor_share": COVERAGE_FLOOR_SHARE,
        "brief_conditioned": session is not None,
        "policy": _policy_report(),
        "strata": strata,
        "regions": _region_report(records, selected_records),
        "stopping_reason": (
            "coverage floor was protected; remaining seats followed brief relevance, "
            "capacity plausibility, uncertainty, and diminishing regional returns"
        ),
    }


def describe_partition(
    atoms: list[dict[str, Any]],
    assignment: list[int],
    session: Any | None = None,
    preferred_mass_count: int | None = None,
) -> dict[str, Any]:
    """Cheap, label-invariant coordinates for one P candidate.

    Coordinates are factual.  The nested ``brief_lens`` is kept separate so a
    preference can change sampling attention without rewriting what P *is*.
    """
    blocks = _blocks(atoms, assignment)
    k = len(blocks)
    department_counts = sorted((len(depts) for depts in blocks), reverse=True)
    singleton_count = sum(1 for size in department_counts if size == 1)
    structure = {
        "mass_count": k,
        "department_counts": department_counts,
        "singleton_masses": singleton_count,
        "largest_department_count": max(department_counts, default=0),
        "singleton_share": _round(singleton_count / k if k else 0.0),
    }

    gsf_map, gsf_source = _department_gsf(session)
    all_departments = [dept for block in blocks for dept in block]
    unknown = [dept for dept in all_departments if dept not in gsf_map]
    mass_gsf = [sum(gsf_map.get(dept, 0.0) for dept in block) for block in blocks]
    total_gsf = sum(mass_gsf)
    shares = sorted(
        ((area / total_gsf) for area in mass_gsf),
        reverse=True,
    ) if total_gsf > 0 else []
    equal_share = 1.0 / k if k else 0.0
    dominance = (max(shares) / equal_share) if shares and equal_share else None
    area = {
        "known_total_gsf": _round(total_gsf, 1),
        "mass_gsf": sorted((_round(value, 1) for value in mass_gsf), reverse=True),
        "mass_shares": [_round(value) for value in shares],
        "largest_mass_share": _round(max(shares)) if shares else None,
        "dominance_vs_equal": _round(dominance) if dominance is not None else None,
        "concentration_hhi": _round(sum(value * value for value in shares)) if shares else None,
        "unknown_gsf_departments": sorted(unknown),
    }

    pressure = _pressure_coordinates(session, blocks, gsf_map, unknown)
    relationships = _relationship_coordinates(session, blocks)
    confidence = {
        "gsf": (
            "unknown"
            if not gsf_map
            else "partial"
            if unknown
            else "program-derived"
        ),
        "gsf_sources": gsf_source,
        "capacity": pressure.pop("capacity_confidence"),
        "relationship": "exact-from-partition",
    }
    factual = {
        "structure": structure,
        "area_distribution": area,
        "constraint_pressure": pressure,
        "relationships": relationships,
        "confidence": confidence,
    }
    region = _region_of(factual)
    brief_lens = _brief_lens(
        session,
        blocks,
        factual,
        preferred_mass_count=preferred_mass_count,
    )
    return {
        **factual,
        "region": region,
        "brief_lens": brief_lens,
    }


def _sample_stratum(
    n: int,
    k: int,
    *,
    target: int,
    total: int,
    apart_pairs: list[tuple[int, int]],
    seed_text: str,
) -> tuple[list[list[int]], list[list[int]], dict[str, Any]]:
    if target <= 0 or total <= 0:
        return [], [], {"attempts": 0, "checked": 0, "exact": False}
    if total <= target:
        found: list[list[int]] = []
        failed: list[list[int]] = []
        checked = 0
        for assign in _restricted_growth_fixed(n, k):
            checked += 1
            if _respects_apart(assign, apart_pairs):
                found.append(assign)
            elif len(failed) < 4:
                failed.append(assign)
        return found, failed, {"attempts": checked, "checked": checked, "exact": True}

    seed = int.from_bytes(
        hashlib.sha256(f"{seed_text}|k={k}".encode("utf-8")).digest()[:8],
        "big",
    )
    rng = random.Random(seed)
    seen: set[tuple[int, ...]] = set()
    found = []
    failed = []
    checked = attempts = 0
    attempt_limit = max(2000, target * 40)
    while len(found) < target and attempts < attempt_limit and len(seen) < total:
        attempts += 1
        raw = [rng.randrange(k) for _ in range(n)]
        if len(set(raw)) != k:
            continue
        assign = _canonicalize(raw)
        key = tuple(assign)
        if key in seen:
            continue
        seen.add(key)
        checked += 1
        if _respects_apart(assign, apart_pairs):
            found.append(assign)
        elif len(failed) < 4:
            failed.append(assign)
    return found, failed, {"attempts": attempts, "checked": checked, "exact": False}


def _proposal_quotas(
    totals: dict[int, int],
    budget: int,
    *,
    preferred: int | None,
) -> dict[int, int]:
    """Half broad stratum coverage, half evidence/brief-directed depth."""
    active = [k for k, count in totals.items() if count > 0]
    if not active or budget <= 0:
        return {}
    quotas = {k: 0 for k in active}
    coverage_budget = min(budget, max(len(active), budget // 2))
    base = coverage_budget // len(active)
    for k in active:
        quotas[k] = min(totals[k], base)
    used = sum(quotas.values())

    max_log = max(math.log1p(totals[k]) for k in active) or 1.0
    while used < budget:
        best_k: int | None = None
        best_score = -1.0
        scale = max(1.0, budget / len(active))
        for k in active:
            if quotas[k] >= totals[k]:
                continue
            size_evidence = math.log1p(totals[k]) / max_log
            brief_pull = (
                1.0 / (1.0 + abs(k - preferred)) if preferred is not None else 0.5
            )
            weight = 0.55 + 0.25 * size_evidence + 0.20 * brief_pull
            score = weight / (1.0 + quotas[k] / scale)
            if score > best_score or (score == best_score and (best_k is None or k < best_k)):
                best_score = score
                best_k = k
        if best_k is None:
            break
        quotas[best_k] += 1
        used += 1
    return quotas


def _allocate_landscape(records: list[dict[str, Any]], budget: int) -> list[dict[str, Any]]:
    if len(records) <= budget:
        return records
    by_region: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_region[str(record["descriptor"]["region"]["id"])].append(record)
    for pool in by_region.values():
        pool.sort(key=lambda row: (-float(row["attention"]), str(row["stable_key"])))

    region_ids = sorted(by_region)
    quotas = {region: 0 for region in region_ids}
    floor_budget = min(budget, max(len(region_ids), int(round(budget * COVERAGE_FLOOR_SHARE))))
    while sum(quotas.values()) < floor_budget:
        moved = False
        for region in region_ids:
            if sum(quotas.values()) >= floor_budget:
                break
            if quotas[region] < len(by_region[region]):
                quotas[region] += 1
                moved = True
        if not moved:
            break

    remaining = budget - sum(quotas.values())
    if remaining > 0:
        region_count = max(1, len(region_ids))
        max_share = min(
            1.0,
            max(MIN_REGION_MAX_SHARE, 1.0 / region_count + REGION_SHARE_HEADROOM),
        )
        max_per_region = max(1, int(math.ceil(budget * max_share)))
        scale = max(1.0, remaining / region_count)
        heap: list[tuple[float, str]] = []
        weights: dict[str, float] = {}
        extras = {region: 0 for region in region_ids}
        total_records = len(records)
        for region in region_ids:
            pool = by_region[region]
            attention = sum(float(row["attention"]) for row in pool) / len(pool)
            rarity = 1.0 - len(pool) / total_records
            weights[region] = (
                REGION_WEIGHTS["mean_attention"] * attention
                + REGION_WEIGHTS["rarity"] * rarity
            )
            heapq.heappush(heap, (-weights[region], region))
        while remaining > 0 and heap:
            _, region = heapq.heappop(heap)
            if quotas[region] >= len(by_region[region]) or quotas[region] >= max_per_region:
                continue
            quotas[region] += 1
            extras[region] += 1
            remaining -= 1
            if quotas[region] < len(by_region[region]) and quotas[region] < max_per_region:
                diminished = weights[region] / (1.0 + extras[region] / scale)
                heapq.heappush(heap, (-diminished, region))

    # If concentration caps leave seats unused, fill them without erasing the
    # already-protected regional floor.
    remaining = budget - sum(quotas.values())
    while remaining > 0:
        candidates = [r for r in region_ids if quotas[r] < len(by_region[r])]
        if not candidates:
            break
        region = max(
            candidates,
            key=lambda r: (
                float(by_region[r][quotas[r]]["attention"]),
                -quotas[r],
                r,
            ),
        )
        quotas[region] += 1
        remaining -= 1

    selected = []
    for region in region_ids:
        selected.extend(by_region[region][: quotas[region]])
    selected.sort(key=lambda row: str(row["stable_key"]))
    return selected


def _selection_record(
    atoms: list[dict[str, Any]],
    assign: list[int],
    session: Any | None,
    preferred_mass_count: int | None,
    seed_text: str,
) -> dict[str, Any]:
    descriptor = describe_partition(
        atoms,
        assign,
        session=session,
        preferred_mass_count=preferred_mass_count,
    )
    stable_key = hashlib.sha256(
        f"{seed_text}|{','.join(str(v) for v in assign)}".encode("utf-8")
    ).hexdigest()
    return {
        "assignment": assign,
        "descriptor": descriptor,
        "attention": float(descriptor["brief_lens"]["sampling_attention"]),
        "stable_key": stable_key,
    }


def _region_report(
    proposals: list[dict[str, Any]],
    selected: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    proposed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    retained: dict[str, int] = defaultdict(int)
    for row in proposals:
        proposed[str(row["descriptor"]["region"]["id"])].append(row)
    for row in selected:
        retained[str(row["descriptor"]["region"]["id"])] += 1
    out = []
    for region_id in sorted(proposed):
        rows = proposed[region_id]
        sample = rows[0]["descriptor"]
        out.append(
            {
                "id": region_id,
                "label": sample["region"]["label"],
                "proposed": len(rows),
                "retained": retained.get(region_id, 0),
                "mean_attention": _round(
                    sum(float(row["attention"]) for row in rows) / len(rows)
                ),
            }
        )
    return out


def _stratum_report(
    *,
    total: int,
    checked: int,
    valid: int,
    proposed: int,
    retained: int,
    exact: bool,
) -> dict[str, Any]:
    rate = valid / checked if checked else 0.0
    return {
        "unconstrained_partitions": total,
        "unique_checked": checked,
        "valid_unique": valid,
        "observed_valid_rate": _round(rate),
        "proposed": proposed,
        "retained": retained,
        "exact": exact,
    }


def _pressure_coordinates(
    session: Any | None,
    blocks: list[list[str]],
    gsf_map: dict[str, float],
    unknown_gsf: list[str],
) -> dict[str, Any]:
    constraints = dict(getattr(session, "constraints", None) or {})
    pins = dict(getattr(session, "floor_pins", None) or {})
    ground = {str(dept) for dept, level in pins.items() if _as_int(level) == 0}
    double_height = {str(dept) for dept in constraints.get("double_height_departments") or []}
    room_names = {str(name) for name in getattr(session, "double_height_rooms", None) or []}
    for room in getattr(getattr(session, "program", None), "rooms", None) or []:
        if str(getattr(room, "room_name", "")) in room_names:
            double_height.add(str(getattr(room, "department", "")))

    ground_gsf = [sum(gsf_map.get(dept, 0.0) for dept in block if dept in ground) for block in blocks]
    dh_gsf = [
        sum(gsf_map.get(dept, 0.0) for dept in block if dept in double_height)
        for block in blocks
    ]
    block_gsf = [sum(gsf_map.get(dept, 0.0) for dept in block) for block in blocks]
    ground_total = sum(ground_gsf)
    dh_total = sum(dh_gsf)
    dh_rider_gsf = sum(
        max(0.0, block_gsf[i] - dh_gsf[i])
        for i in range(len(blocks))
        if dh_gsf[i] > 0
    )

    widths = {
        str(dept): float(value)
        for dept, value in (constraints.get("department_widths") or {}).items()
        if _positive(value) is not None
    }
    width_conflicts = 0
    for block in blocks:
        values = {round(widths[dept], 6) for dept in block if dept in widths}
        if len(values) > 1:
            width_conflicts += 1
    widths_by_value: dict[float, list[str]] = defaultdict(list)
    for dept, value in widths.items():
        widths_by_value[round(value, 6)].append(dept)
    compatible_width_pairs = sum(
        len(depts) * (len(depts) - 1) // 2
        for depts in widths_by_value.values()
    )
    homes = {dept: i for i, block in enumerate(blocks) for dept in block}
    compatible_width_pairs_colocated = 0
    for depts in widths_by_value.values():
        for i, left in enumerate(depts):
            for right in depts[i + 1 :]:
                if left in homes and right in homes and homes[left] == homes[right]:
                    compatible_width_pairs_colocated += 1

    max_edge = _positive(constraints.get("max_edge_ft"))
    max_length = _minimum_positive(
        constraints.get("max_building_length_ft"),
        max_edge,
    )
    max_width = _minimum_positive(
        constraints.get("max_building_width_ft"),
        max_edge,
    )
    max_stories = _positive(constraints.get("max_stories"))
    all_known = bool(blocks) and not unknown_gsf and bool(gsf_map)
    story_lower_bounds: list[int] = []
    capacity_confidence = "unknown"
    if max_length and max_width and all_known:
        capacity_confidence = "hard-envelope-lower-bound"
        max_plate = max_length * max_width
        for block in blocks:
            area = sum(gsf_map.get(dept, 0.0) for dept in block)
            story_lower_bounds.append(max(1, int(math.ceil(area / max_plate))))
    elif max_length or max_width or max_stories:
        capacity_confidence = "partial-input"

    width_over_limit = sum(
        1 for value in widths.values() if max_width is not None and value > max_width
    )
    max_story_lb = max(story_lower_bounds, default=None)
    story_pressure = (
        max_story_lb / max_stories
        if max_story_lb is not None and max_stories is not None
        else None
    )
    proven_impossible = bool(
        width_over_limit
        or (
            max_story_lb is not None
            and max_stories is not None
            and max_story_lb > max_stories
        )
    )
    return {
        "ground_required_gsf": _round(ground_total, 1),
        "ground_concentration": _round(max(ground_gsf) / ground_total) if ground_total else None,
        "double_height_gsf": _round(dh_total, 1),
        "double_height_concentration": _round(max(dh_gsf) / dh_total) if dh_total else None,
        "double_height_rider_gsf": _round(dh_rider_gsf, 1),
        "double_height_rider_share": (
            _round(dh_rider_gsf / (dh_total + dh_rider_gsf))
            if dh_total + dh_rider_gsf > 0
            else None
        ),
        "width_locked_departments": len(widths),
        "mixed_exact_width_masses": width_conflicts,
        "compatible_width_pairs": compatible_width_pairs,
        "compatible_width_pairs_colocated": compatible_width_pairs_colocated,
        "widths_over_global_limit": width_over_limit,
        "story_lower_bounds": sorted(story_lower_bounds, reverse=True),
        "max_story_lower_bound": max_story_lb,
        "story_pressure": _round(story_pressure) if story_pressure is not None else None,
        "proven_capacity_impossible": proven_impossible,
        "capacity_confidence": capacity_confidence,
    }


def _relationship_coordinates(
    session: Any | None,
    blocks: list[list[str]],
) -> dict[str, Any]:
    """Exact P relationships, without deciding whether they are desirable."""
    homes = {dept: i for i, block in enumerate(blocks) for dept in block}
    department_count = len(homes)
    possible_pairs = department_count * (department_count - 1) // 2
    colocated_pairs = sum(len(block) * (len(block) - 1) // 2 for block in blocks)
    stated = []
    briefing = (getattr(session, "constraints", None) or {}).get("briefing") or {}
    for kind in ("requirements", "limitations", "preferences"):
        for clause in briefing.get(kind) or []:
            lever = str(clause.get("lever") or "")
            depts = [str(value) for value in clause.get("departments") or []]
            if lever not in {"same_mass", "keep_together", "keep_apart", "alone"}:
                continue
            realized = _preference_satisfaction(clause, blocks, len(blocks))
            stated.append(
                {
                    "kind": kind[:-1] if kind.endswith("s") else kind,
                    "lever": lever,
                    "departments": depts,
                    "realized": realized,
                }
            )
    return {
        "possible_department_pairs": possible_pairs,
        "colocated_department_pairs": colocated_pairs,
        "colocation_share": _round(colocated_pairs / possible_pairs) if possible_pairs else 0.0,
        "cross_mass_department_pairs": possible_pairs - colocated_pairs,
        "stated_relationships": stated,
    }


def _region_of(factual: dict[str, Any]) -> dict[str, str]:
    structure = factual["structure"]
    area = factual["area_distribution"]
    pressure = factual["constraint_pressure"]
    k = int(structure["mass_count"])

    dominance = area.get("dominance_vs_equal")
    if dominance is None:
        area_band = "unknown-area"
    elif dominance <= 1.25:
        area_band = "balanced-area"
    elif dominance <= 1.75:
        area_band = "uneven-area"
    else:
        area_band = "dominant-mass"

    ground_band = _concentration_band(pressure.get("ground_concentration"), "ground")
    dh_rider_share = pressure.get("double_height_rider_share")
    if dh_rider_share is None:
        dh_band = "no-double-height-demand"
    elif float(dh_rider_share) <= 0.05:
        dh_band = "isolated-double-height"
    elif float(dh_rider_share) <= 0.35:
        dh_band = "light-double-height-riders"
    else:
        dh_band = "heavy-double-height-riders"
    story_pressure = pressure.get("story_pressure")
    if pressure.get("proven_capacity_impossible"):
        capacity_band = "proven-capacity-conflict"
    elif story_pressure is None:
        capacity_band = "unknown-capacity"
    elif story_pressure <= 0.65:
        capacity_band = "capacity-slack"
    else:
        capacity_band = "capacity-pressured"

    singleton_share = float(structure.get("singleton_share") or 0.0)
    mix_band = "singleton-heavy" if singleton_share >= 0.5 else "mostly-mixed"
    parts = [f"k{k}", area_band, ground_band, dh_band, capacity_band, mix_band]
    return {
        "id": "|".join(parts),
        "label": "; ".join(
            [f"{k} masses", area_band, ground_band, dh_band, capacity_band, mix_band]
        ),
    }


def _brief_lens(
    session: Any | None,
    blocks: list[list[str]],
    factual: dict[str, Any],
    *,
    preferred_mass_count: int | None,
) -> dict[str, Any]:
    reasons: list[str] = []
    relevance_parts: list[float] = []
    k = int(factual["structure"]["mass_count"])
    if preferred_mass_count is not None:
        closeness = 1.0 / (1.0 + abs(k - int(preferred_mass_count)))
        relevance_parts.append(closeness)
        reasons.append(f"mass-count proximity {closeness:.2f}")

    constraints = dict(getattr(session, "constraints", None) or {})
    briefing = constraints.get("briefing") or {}
    for clause in briefing.get("preferences") or []:
        satisfaction = _preference_satisfaction(clause, blocks, k)
        if satisfaction is None:
            continue
        relevance_parts.append(satisfaction)
        lever = str(clause.get("lever") or "preference")
        reasons.append(f"{lever} preference {satisfaction:.2f}")

    preferred_stories = _positive(constraints.get("preferred_stories"))
    story_lb = factual["constraint_pressure"].get("max_story_lower_bound")
    if preferred_stories is not None and story_lb is not None:
        story_fit = max(0.0, 1.0 - abs(story_lb - preferred_stories) / preferred_stories)
        relevance_parts.append(story_fit)
        reasons.append(f"story lower-bound fit {story_fit:.2f}")

    relevance = sum(relevance_parts) / len(relevance_parts) if relevance_parts else 0.5
    pressure = factual["constraint_pressure"]
    if pressure.get("proven_capacity_impossible"):
        plausibility = 0.0
    elif pressure.get("story_pressure") is None:
        plausibility = 0.5
    else:
        story_pressure = float(pressure["story_pressure"])
        plausibility = max(0.0, min(1.0, 1.0 - max(0.0, story_pressure - 0.5)))
        if pressure.get("mixed_exact_width_masses"):
            plausibility *= 0.85
        dh_rider_share = pressure.get("double_height_rider_share")
        if dh_rider_share is not None:
            plausibility *= max(0.45, 1.0 - 0.65 * float(dh_rider_share))
        compatible = int(pressure.get("compatible_width_pairs") or 0)
        if compatible:
            colocated = int(pressure.get("compatible_width_pairs_colocated") or 0)
            plausibility *= 0.90 + 0.10 * colocated / compatible

    area = factual["area_distribution"]
    total_departments = sum(factual["structure"]["department_counts"])
    missing_share = len(area.get("unknown_gsf_departments") or []) / max(1, total_departments)
    capacity_unknown = 1.0 if factual["confidence"]["capacity"] != "hard-envelope-lower-bound" else 0.0
    uncertainty = 0.6 * missing_share + 0.4 * capacity_unknown
    attention = (
        ATTENTION_WEIGHTS["brief_relevance"] * relevance
        + ATTENTION_WEIGHTS["capacity_plausibility"] * plausibility
        + ATTENTION_WEIGHTS["uncertainty"] * uncertainty
    )
    return {
        "relevance": _round(relevance),
        "capacity_plausibility": _round(plausibility),
        "uncertainty": _round(uncertainty),
        "sampling_attention": _round(attention),
        "reasons": reasons,
    }


def _preference_satisfaction(
    clause: dict[str, Any],
    blocks: list[list[str]],
    mass_count: int,
) -> float | None:
    lever = str(clause.get("lever") or "")
    depts = [str(value) for value in clause.get("departments") or []]
    homes = {dept: i for i, block in enumerate(blocks) for dept in block}
    if lever in {"same_mass", "keep_together"} and len(depts) >= 2:
        known = [homes[d] for d in depts if d in homes]
        return 1.0 if len(known) >= 2 and len(set(known)) == 1 else 0.0
    if lever == "keep_apart" and len(depts) >= 2:
        known = [homes[d] for d in depts if d in homes]
        return 1.0 if len(known) >= 2 and len(set(known)) == len(known) else 0.0
    if lever == "alone" and depts:
        dept = depts[0]
        if dept not in homes:
            return None
        return 1.0 if len(blocks[homes[dept]]) == 1 else 0.0
    if lever == "mass_count":
        wanted = _as_int(clause.get("value"))
        if wanted and wanted > 0:
            return 1.0 / (1.0 + abs(mass_count - wanted))
    return None


def _department_gsf(session: Any | None) -> tuple[dict[str, float], dict[str, int]]:
    out: dict[str, float] = {}
    sources: dict[str, int] = defaultdict(int)
    for dept in getattr(getattr(session, "program", None), "departments", None) or []:
        name = str(getattr(dept, "name", ""))
        target = _positive(getattr(dept, "target_gsf", None))
        nfa = _positive(getattr(dept, "nfa_sf", None))
        if target is not None:
            out[name] = target
            sources["target_gsf"] += 1
        elif nfa is not None:
            out[name] = nfa
            sources["nfa_fallback"] += 1
    return out, dict(sources)


def _blocks(atoms: list[dict[str, Any]], assignment: list[int]) -> list[list[str]]:
    grouped: dict[int, list[str]] = defaultdict(list)
    for i, block in enumerate(assignment):
        grouped[int(block)].extend(str(d) for d in atoms[i].get("departments") or [])
    return [sorted(grouped[key]) for key in sorted(grouped)]


def _restricted_growth_fixed(n: int, k: int) -> Iterable[list[int]]:
    if n <= 0 or k <= 0 or k > n:
        return
    assign = [0] * n

    def rec(i: int, blocks: int) -> Iterable[list[int]]:
        if blocks > k or blocks + (n - i) < k:
            return
        if i == n:
            if blocks == k:
                yield assign[:]
            return
        for block in range(blocks):
            assign[i] = block
            yield from rec(i + 1, blocks)
        if blocks < k:
            assign[i] = blocks
            yield from rec(i + 1, blocks + 1)

    yield from rec(1, 1)


def _canonicalize(labels: list[int]) -> list[int]:
    remap: dict[int, int] = {}
    out = []
    for label in labels:
        if label not in remap:
            remap[label] = len(remap)
        out.append(remap[label])
    return out


def _respects_apart(assign: list[int], pairs: list[tuple[int, int]]) -> bool:
    return all(assign[i] != assign[j] for i, j in pairs)


def _seed_text(
    atoms: list[dict[str, Any]],
    apart_pairs: list[tuple[int, int]],
    k_min: int,
    k_max: int,
) -> str:
    atom_text = "|".join(
        "+".join(sorted(str(d) for d in atom.get("departments") or []))
        for atom in atoms
    )
    pair_text = "|".join(f"{i}:{j}" for i, j in sorted(apart_pairs))
    return hashlib.sha256(
        f"{atom_text}::{pair_text}::{k_min}:{k_max}".encode("utf-8")
    ).hexdigest()


def _policy_report() -> dict[str, Any]:
    """Expose policy constants so sampling behavior is inspectable and tunable."""
    return {
        "proposal_multiplier": PROPOSAL_MULTIPLIER,
        "coverage_floor_share": COVERAGE_FLOOR_SHARE,
        "attention_weights": dict(ATTENTION_WEIGHTS),
        "region_weights": dict(REGION_WEIGHTS),
        "minimum_region_max_share": MIN_REGION_MAX_SHARE,
        "region_share_headroom": REGION_SHARE_HEADROOM,
    }


def _concentration_band(value: Any, name: str) -> str:
    if value is None:
        return f"no-{name}-demand"
    return f"distributed-{name}" if float(value) <= 0.60 else f"concentrated-{name}"


def _minimum_positive(*values: Any) -> float | None:
    found = [value for raw in values if (value := _positive(raw)) is not None]
    return min(found) if found else None


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)
