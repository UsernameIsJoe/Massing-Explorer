"""
Constraint satisfaction over program partitions.

Variables are family atoms (the masses already on the study). An assignment
is a restricted-growth string: atom i joins an existing block or opens a
new one. That enumerates distinct set partitions, not labeled permutations.

Hard constraints: keep-together (pre-glued), keep-apart (blocks cannot
share), coverage (every atom assigned). Site fit is not a CSP constraint;
the engine still filters.

The LLM does not invent P. mass_count, keep-together, and alone constrain
the partitions this module returns. They do not freeze P unless the session
sets partition_locked.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from ..group import _family_of, _title
from .csp_landscape import build_partition_landscape, describe_partition
from .strategy import (
    grouping_is_required,
    preferred_mass_count,
    required_alone,
    required_apart,
    required_mass_bounds,
    required_together,
)

PARTITION_CAP = 5  # back-compat alias for UI presentation
UI_PARTITION_CAP = 5  # human-facing CSP board / report shortlist
MAX_ENUM = 25000  # practical ceiling; truncated=True when hit

SHORTLIST_WEIGHTS = {
    "new_region": 0.22,
    "relationship_coverage": 0.20,
    "strategic_difference": 0.20,
    "capacity_plausibility": 0.26,
    "information_value": 0.08,
    "brief_tiebreak": 0.04,
}

_ARCHETYPE_ORDER = ("arts_with_academic", "arts_separate", "other", "school_bars")


def _csp_inputs(session: Any) -> dict[str, Any]:
    """Atoms and P constraints shared by the UI report and the ordered stream."""
    locked = grouping_is_required(session)
    atoms = [] if locked else department_atoms(session)
    if not atoms:
        atoms = atoms_from_session(session)
    apart = list(required_apart(session))
    alone = required_alone(session)
    apart.extend(_alone_as_apart(atoms, alone))
    return {
        "locked": locked,
        "atoms": atoms,
        "apart": apart,
        "together": required_together(session),
        "alone": alone,
        "bounds": required_mass_bounds(session),
        "preferred": preferred_mass_count(session),
    }


def describe_csp(session: Any, cap: int = UI_PARTITION_CAP) -> dict[str, Any]:
    """Report for the archive, planner, and the Phase 6 board (UI shortlist)."""
    inputs = _csp_inputs(session)
    locked = inputs["locked"]
    atoms = inputs["atoms"]
    apart = inputs["apart"]
    together = inputs["together"]
    alone = inputs["alone"]
    bounds = inputs["bounds"]
    preferred = inputs["preferred"]
    if not atoms:
        return {
            "ran": True,
            "locked": locked,
            "source": "csp",
            "atoms": [],
            "apart": [sorted(p) for p in apart],
            "together": [sorted(p) for p in together],
            "alone": list(alone),
            "mass_bounds": list(bounds) if bounds else None,
            "preferred_mass_count": preferred,
            "feasible_count": 0,
            "feasible_count_exact": True,
            "estimated_feasible_count": 0,
            "enumerated": 0,
            "truncated": False,
            "landscape": None,
            "shortlist": {
                "method": "marginal_portfolio",
                "requested": max(0, int(cap)),
                "selected": 0,
            },
            "shown": 0,
            "chosen": [],
            "rejected": [],
            "note": "No program atoms, so the constraint solver has no partition.",
        }
    if locked:
        chosen = [_from_atoms(atoms, list(range(len(atoms))), "stated grouping")]
        return {
            "ran": True,
            "locked": True,
            "source": "csp",
            "atoms": [_atom_view(a) for a in atoms],
            "apart": [sorted(p) for p in apart],
            "together": [sorted(p) for p in together],
            "alone": list(alone),
            "mass_bounds": list(bounds) if bounds else None,
            "preferred_mass_count": preferred,
            "feasible_count": 1,
            "feasible_count_exact": True,
            "estimated_feasible_count": 1,
            "enumerated": 1,
            "truncated": False,
            "landscape": {
                "method": "locked",
                "deterministic": True,
                "sampled": 1,
                "stopping_reason": "the brief locked P",
            },
            "shortlist": {
                "method": "locked",
                "requested": max(0, int(cap)),
                "selected": 1,
            },
            "shown": 1,
            "chosen": chosen,
            "rejected": [],
            "note": (
                "P is locked. The constraint solver kept the stated grouping "
                "and did not sample other partitions."
            ),
        }

    solved = solve_partitions(
        atoms,
        apart=apart,
        together=together,
        cap=cap,
        mass_bounds=bounds,
        preferred_mass_count=preferred,
        session=session,
    )
    return {
        "ran": True,
        "locked": False,
        "source": "csp",
        "atoms": [_atom_view(a) for a in atoms],
        "apart": [sorted(p) for p in apart],
        "together": [sorted(p) for p in together],
        "alone": list(alone),
        "mass_bounds": list(bounds) if bounds else None,
        "preferred_mass_count": preferred,
        "feasible_count": solved["feasible_count"],
        "feasible_count_exact": solved["feasible_count_exact"],
        "estimated_feasible_count": solved["estimated_feasible_count"],
        "enumerated": solved["enumerated"],
        "truncated": solved["truncated"],
        "landscape": solved["landscape"],
        "shortlist": solved["shortlist"],
        "shown": len(solved["chosen"]),
        "chosen": solved["chosen"],
        "rejected": solved["rejected"],
        "note": solved["note"],
    }


def ordered_partition_candidates(
    session: Any,
    *,
    cap: int,
    exclude: Callable[[list[dict[str, Any]]], bool] | None = None,
) -> list[dict[str, Any]]:
    """
    The same coverage-ordered stream the CSP shortlist admits, for P-pool growth.

    `exclude` marks partitions the caller already holds: they never take a seat,
    but their relationship features count as covered, so expansion reaches for
    organizations the pool is still missing instead of rank-tail neighbours.
    """
    inputs = _csp_inputs(session)
    if inputs["locked"] or not inputs["atoms"] or cap <= 0:
        return []
    solved = solve_partitions(
        inputs["atoms"],
        apart=inputs["apart"],
        together=inputs["together"],
        cap=cap,
        mass_bounds=inputs["bounds"],
        preferred_mass_count=inputs["preferred"],
        exclude=exclude,
        session=session,
    )
    return list(solved["chosen"])


def solve_partitions(
    atoms: list[dict[str, Any]],
    apart: list[frozenset[str]] | None = None,
    together: list[frozenset[str]] | None = None,
    cap: int = UI_PARTITION_CAP,
    mass_bounds: tuple[int, int] | None = None,
    preferred_mass_count: int | None = None,
    exclude: Callable[[list[dict[str, Any]]], bool] | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """Construct the feasible P landscape, then diversity-select up to `cap`."""
    glued = _glue(atoms, together or [])
    n = len(glued)
    apart_pairs = _atom_apart_pairs(glued, apart or [])
    if mass_bounds:
        k_min = max(1, min(int(mass_bounds[0]), n or 1))
        k_max = max(k_min, min(int(mass_bounds[1]), n or 1))
    else:
        k_min, k_max = 1, max(n, 1)
    preferred = None
    if preferred_mass_count is not None:
        try:
            pref = int(preferred_mass_count)
        except (TypeError, ValueError):
            pref = 0
        if pref > 0:
            preferred = max(k_min, min(k_max, pref))
    landscape_records: list[dict[str, Any]] = []
    feasible, rejected_assignments, landscape = build_partition_landscape(
        glued,
        k_min=k_min,
        k_max=k_max,
        apart_pairs=apart_pairs,
        budget=MAX_ENUM,
        preferred_mass_count=preferred,
        session=session,
        records_out=landscape_records,
    )
    rejected = [
        {
            "label": _assignment_label(glued, assign),
            "why": "broke keep-apart",
        }
        for assign in rejected_assignments[:4]
    ]
    truncated = not bool(landscape["feasible_count_exact"])
    enumerated = len(feasible)

    ranked = sorted(
        feasible,
        key=lambda a: _score(glued, a, preferred_mass_count=preferred),
        reverse=True,
    )
    chosen = _pick_shortlist(
        glued,
        ranked,
        cap=cap,
        k_min=k_min,
        k_max=k_max,
        preferred_mass_count=preferred,
        exclude=exclude,
        landscape_records=landscape_records,
    )
    shortlist = _shortlist_report(chosen, cap=cap)

    extra = (
        " The feasible count is an estimate; the shortlist input is a "
        "deterministic, space-wide landscape sample rather than a DFS prefix."
        if truncated
        else ""
    )
    bound = f" with |P| in {k_min}–{k_max}" if mass_bounds else ""
    pref_note = (
        f" Preferred |P|={preferred} from the brief."
        if preferred is not None
        else " No preferred mass count, so higher |P| is not ranked above lower |P|."
    )
    note = (
        f"CSP: {len(feasible)} feasible partition(s) in the pre-shortlist "
        f"landscape of {n} atom(s){bound}; "
        f"shortlist {len(chosen)} as a marginal-value portfolio with |P| "
        f"coverage, descriptor regions, relationship evidence, partition "
        f"difference, capacity plausibility, and information value. Brief fit "
        f"is only a tie-break because it already guided landscape sampling. "
        f"Constraints filter P; they do not freeze it."
        f"{pref_note}{extra}"
    )
    return {
        "atoms": glued,
        "feasible_count": len(feasible),
        "feasible_count_exact": bool(landscape["feasible_count_exact"]),
        "estimated_feasible_count": int(landscape["estimated_feasible_count"]),
        "enumerated": enumerated,
        "truncated": truncated,
        "landscape": landscape,
        "shortlist": shortlist,
        "chosen": chosen,
        "rejected": rejected,
        "preferred_mass_count": preferred,
        "note": note,
    }


def _pick_shortlist(
    atoms: list[dict[str, Any]],
    ranked: list[list[int]],
    *,
    cap: int,
    k_min: int,
    k_max: int,
    preferred_mass_count: int | None = None,
    exclude: Callable[[list[dict[str, Any]]], bool] | None = None,
    landscape_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build a small portfolio from the sampled P landscape.

    Mass-count coverage is protected first.  Seats within each stratum are
    selected by their *marginal* contribution: new descriptor region, new
    relationship evidence, distance from organizations already represented,
    bounded capacity plausibility, and information value.  Brief relevance is
    intentionally only a light tie-break because it already guided landscape
    sampling.  The older school-shaped score is now a final deterministic
    tie-break, not a source of shortlist seats.
    """
    if cap <= 0:
        return []

    descriptor_by_assignment = {
        tuple(record.get("assignment") or []): record.get("descriptor") or {}
        for record in landscape_records or []
    }
    buckets: dict[int, list[dict[str, Any]]] = {
        k: [] for k in range(k_min, k_max + 1)
    }
    covered_regions: set[tuple[str, str]] = set()
    covered_relationships: dict[int, set[tuple[str, ...]]] = {
        k: set() for k in range(k_min, k_max + 1)
    }
    represented_pairs: dict[int, list[frozenset[frozenset[str]]]] = {
        k: [] for k in range(k_min, k_max + 1)
    }
    represented_mass_counts: set[int] = set()

    for rank_index, assign in enumerate(ranked):
        mass_count = len(set(assign))
        if mass_count not in buckets:
            continue
        descriptor = descriptor_by_assignment.get(tuple(assign))
        if not descriptor:
            descriptor = describe_partition(
                atoms,
                assign,
                preferred_mass_count=preferred_mass_count,
            )
        signature = _assign_signature(atoms, assign)
        candidate = {
            "assignment": assign,
            "descriptor": descriptor,
            "signature": signature,
            "pair_set": _coexist_pairs(signature),
            "mass_count": mass_count,
            "region": str((descriptor.get("region") or {}).get("id") or f"k{mass_count}"),
            "region_keys": _portfolio_region_keys(descriptor),
            "relationship_keys": _portfolio_relationship_keys(atoms, assign, descriptor),
            "rank_index": rank_index,
            "proven_impossible": bool(
                (descriptor.get("constraint_pressure") or {}).get(
                    "proven_capacity_impossible"
                )
            ),
        }
        groups = _from_atoms(atoms, assign, "")["groups"]
        if exclude is not None and exclude(groups):
            covered_regions.update(candidate["region_keys"])
            covered_relationships[mass_count].update(candidate["relationship_keys"])
            represented_pairs[mass_count].append(candidate["pair_set"])
            represented_mass_counts.add(mass_count)
            continue
        buckets[mass_count].append(candidate)

    active = [k for k in range(k_min, k_max + 1) if buckets.get(k)]
    if not active:
        return []
    available = {k: len(buckets[k]) for k in active}
    if cap < len(active):
        protected = _evenly_spaced_strata(active, cap)
        mass_quotas = {k: (1 if k in protected else 0) for k in active}
    else:
        # No preferred-|P| bonus here: it already affected landscape sampling.
        mass_quotas = _stratum_quotas(active, cap, available=available)

    selected_candidates: list[dict[str, Any]] = []
    chosen: list[dict[str, Any]] = []
    seen: set[frozenset[frozenset[str]]] = set()
    taken: dict[int, int] = {k: 0 for k in active}

    def push(candidate: dict[str, Any], role: str, metrics: dict[str, Any]) -> bool:
        signature = candidate["signature"]
        if signature in seen:
            return False
        assign = candidate["assignment"]
        k = int(candidate["mass_count"])
        item = _from_atoms(atoms, assign, _reason(atoms, assign))
        seen.add(signature)
        selected_candidates.append(candidate)
        represented_pairs[k].append(candidate["pair_set"])
        represented_mass_counts.add(int(candidate["mass_count"]))
        covered_regions.update(candidate["region_keys"])
        covered_relationships[k].update(candidate["relationship_keys"])
        item["shortlist_selection"] = _selection_explanation(
            candidate,
            role=role,
            metrics=metrics,
        )
        chosen.append(item)
        taken[k] = taken.get(k, 0) + 1
        return True

    # Keep the base organization as a reference when it belongs to the bounded
    # landscape.  It consumes a real seat and does not bypass mass-count balance.
    for k in active:
        for candidate in list(buckets[k]):
            if _reason(atoms, candidate["assignment"]) != "stated grouping":
                continue
            buckets[k].remove(candidate)
            metrics = _portfolio_metrics(
                candidate,
                represented_pairs=represented_pairs[k],
                represented_mass_counts=represented_mass_counts,
                covered_regions=covered_regions,
                covered_relationships=covered_relationships[k],
            )
            push(candidate, "baseline", metrics)
            break

    for k in active:
        quota = int(mass_quotas.get(k, 0) or 0)

        # Protect broad organizational archetypes only when this stratum has
        # enough seats.  The archetype is a floor, not the ranking objective:
        # the remaining seats still use the marginal portfolio score below.
        archetype_buckets: dict[str, list[dict[str, Any]]] = {}
        for candidate in buckets[k]:
            archetype_buckets.setdefault(
                _relationship_family(atoms, candidate["assignment"]), []
            ).append(candidate)
        archetypes = [
            family for family in _ARCHETYPE_ORDER if family in archetype_buckets
        ] + sorted(family for family in archetype_buckets if family not in _ARCHETYPE_ORDER)
        floor = min(len(archetypes), max(0, quota - taken[k]))
        if floor and floor == len(archetypes):
            for archetype in archetypes:
                if taken[k] >= quota:
                    break
                pool = archetype_buckets[archetype]
                if not pool:
                    continue
                candidate = pool[0]
                metrics = _portfolio_metrics(
                    candidate,
                    represented_pairs=represented_pairs.get(k, []),
                    represented_mass_counts=represented_mass_counts,
                    covered_regions=covered_regions,
                    covered_relationships=covered_relationships.get(k, set()),
                )
                buckets[k].remove(candidate)
                pool.remove(candidate)
                push(candidate, "archetype", metrics)

        while taken[k] < quota and buckets[k]:
            picked = _best_portfolio_candidate(
                buckets[k],
                represented_pairs=represented_pairs,
                represented_mass_counts=represented_mass_counts,
                covered_regions=covered_regions,
                covered_relationships=covered_relationships,
            )
            if picked is None:
                break
            candidate, metrics = picked
            buckets[k].remove(candidate)
            push(candidate, _selection_role(metrics), metrics)

    # Spill only when a protected stratum ran dry.  The same marginal portfolio
    # value chooses the replacement; dense sampled regions receive no bonus.
    while len(chosen) < cap:
        pool = [candidate for k in active for candidate in buckets[k]]
        picked = _best_portfolio_candidate(
            pool,
            represented_pairs=represented_pairs,
            represented_mass_counts=represented_mass_counts,
            covered_regions=covered_regions,
            covered_relationships=covered_relationships,
        )
        if picked is None:
            break
        candidate, metrics = picked
        buckets[int(candidate["mass_count"])].remove(candidate)
        push(candidate, _selection_role(metrics), metrics)

    chosen.sort(
        key=lambda item: (
            0 if (item.get("reason") or "") == "stated grouping" else 1,
            len(item.get("groups") or []),
        )
    )
    return chosen


def _portfolio_relationship_keys(
    atoms: list[dict[str, Any]],
    assign: list[int],
    descriptor: dict[str, Any],
) -> set[tuple[str, ...]]:
    """Generic stated/gross relationships plus current readable school roles."""
    # Cover each readable relationship value once.  Pairwise combinations and
    # full motifs are left to partition distance; treating every combination as
    # a separate quota recreates thousands of micro-regions and wastes seats.
    features = _relationship_features(atoms, assign)
    keys = {
        ("role", name, value)
        for name, value in features.items()
        if value
    }
    # Keep a small, interpretable set of cross-relations: where a placement
    # sits versus the two structural relationships.  Do not restore every
    # pairwise combination or the full motif cube.
    for placement in _ROLE_FEATURES:
        for structural in ("gym_dining", "academic"):
            if features.get(placement) and features.get(structural):
                keys.add(
                    (
                        "role_pair",
                        placement,
                        features[placement],
                        structural,
                        features[structural],
                    )
                )
    relationships = descriptor.get("relationships") or {}
    share = float(relationships.get("colocation_share") or 0.0)
    band = "sparse" if share <= 0.25 else "mixed" if share <= 0.50 else "dense"
    keys.add(("colocation", band))
    for relation in relationships.get("stated_relationships") or []:
        departments = tuple(sorted(str(d) for d in relation.get("departments") or []))
        keys.add(
            (
                "stated",
                str(relation.get("kind") or ""),
                str(relation.get("lever") or ""),
                *departments,
                f"realized={relation.get('realized')}",
            )
        )
    return keys


def _portfolio_region_keys(descriptor: dict[str, Any]) -> set[tuple[str, str]]:
    """Coordinate values, not composite micro-regions, earn coverage credit."""
    region_id = str((descriptor.get("region") or {}).get("id") or "")
    parts = region_id.split("|")
    axes = ("mass_count", "area", "ground", "double_height", "capacity", "mix")
    return {
        (axis, value)
        for axis, value in zip(axes, parts)
        if axis != "mass_count" and value
    }


def _portfolio_metrics(
    candidate: dict[str, Any],
    *,
    represented_pairs: list[frozenset[frozenset[str]]],
    represented_mass_counts: set[int],
    covered_regions: set[tuple[str, str]],
    covered_relationships: set[tuple[str, ...]],
) -> dict[str, Any]:
    descriptor = candidate["descriptor"]
    lens = descriptor.get("brief_lens") or {}
    new_keys = candidate["relationship_keys"] - covered_relationships
    relationship_gain = min(
        1.0,
        len(new_keys) / max(1, min(6, len(candidate["relationship_keys"]))),
    )
    novelty = (
        min(_pair_set_distance(candidate["pair_set"], pairs) for pairs in represented_pairs)
        if represented_pairs
        else 1.0
    )
    new_region_keys = candidate["region_keys"] - covered_regions
    parts = {
        "new_region": len(new_region_keys) / max(1, len(candidate["region_keys"])),
        "relationship_coverage": relationship_gain,
        "strategic_difference": novelty,
        "capacity_plausibility": float(lens.get("capacity_plausibility") or 0.0),
        "information_value": float(lens.get("uncertainty") or 0.0),
        "brief_tiebreak": float(lens.get("relevance") or 0.0),
    }
    marginal = sum(SHORTLIST_WEIGHTS[name] * value for name, value in parts.items())
    return {
        **parts,
        "new_mass_count": int(candidate["mass_count"]) not in represented_mass_counts,
        "new_region_keys": len(new_region_keys),
        "new_relationship_keys": len(new_keys),
        "marginal_value": round(marginal, 6),
    }


def _best_portfolio_candidate(
    pool: list[dict[str, Any]],
    *,
    represented_pairs: dict[int, list[frozenset[frozenset[str]]]],
    represented_mass_counts: set[int],
    covered_regions: set[tuple[str, str]],
    covered_relationships: dict[int, set[tuple[str, ...]]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    best: tuple[Any, ...] | None = None
    winner: dict[str, Any] | None = None
    winner_metrics: dict[str, Any] | None = None
    for candidate in pool:
        metrics = _portfolio_metrics(
            candidate,
            represented_pairs=represented_pairs.get(
                int(candidate["mass_count"]), []
            ),
            represented_mass_counts=represented_mass_counts,
            covered_regions=covered_regions,
            covered_relationships=covered_relationships.get(
                int(candidate["mass_count"]), set()
            ),
        )
        score = (
            not candidate["proven_impossible"],
            metrics["marginal_value"],
            metrics["new_region"],
            metrics["relationship_coverage"],
            metrics["strategic_difference"],
            -int(candidate["rank_index"]),
            tuple(candidate["assignment"]),
        )
        if best is None or score > best:
            best = score
            winner = candidate
            winner_metrics = metrics
    if winner is None or winner_metrics is None:
        return None
    return winner, winner_metrics


def _selection_role(metrics: dict[str, Any]) -> str:
    if metrics.get("new_mass_count") or int(metrics.get("new_region_keys") or 0) > 0:
        return "coverage"
    if int(metrics.get("new_relationship_keys") or 0) > 0:
        return "relationship"
    if float(metrics.get("information_value") or 0.0) >= 0.60:
        return "information"
    if float(metrics.get("capacity_plausibility") or 0.0) >= 0.75:
        return "plausibility"
    return "portfolio"


def _selection_explanation(
    candidate: dict[str, Any],
    *,
    role: str,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    additions = []
    if metrics.get("new_mass_count"):
        additions.append(f"new |P|={candidate['mass_count']}")
    new_region_keys = int(metrics.get("new_region_keys") or 0)
    if new_region_keys:
        additions.append(f"{new_region_keys} new descriptor coordinates")
    new_relationships = int(metrics.get("new_relationship_keys") or 0)
    if new_relationships:
        additions.append(f"{new_relationships} new relationship features")
    if not additions:
        additions.append(
            f"partition distance {float(metrics.get('strategic_difference') or 0.0):.2f}"
        )
    return {
        "role": role,
        "why": "; ".join(additions),
        "region": candidate["region"],
        "marginal_value": metrics.get("marginal_value"),
        "contributions": {
            name: round(float(metrics.get(name) or 0.0), 4)
            for name in SHORTLIST_WEIGHTS
        },
        "proven_capacity_impossible": bool(candidate["proven_impossible"]),
    }


def _evenly_spaced_strata(strata: list[int], seats: int) -> set[int]:
    """Protect the whole allowed |P| range when seats are fewer than strata."""
    ordered = sorted(set(int(value) for value in strata))
    if seats <= 0 or not ordered:
        return set()
    if seats >= len(ordered):
        return set(ordered)
    if seats == 1:
        return {ordered[len(ordered) // 2]}
    indexes = {
        round(i * (len(ordered) - 1) / (seats - 1))
        for i in range(seats)
    }
    return {ordered[index] for index in indexes}


def _shortlist_report(chosen: list[dict[str, Any]], *, cap: int) -> dict[str, Any]:
    roles: dict[str, int] = defaultdict(int)
    mass_counts: dict[int, int] = defaultdict(int)
    regions: set[str] = set()
    for item in chosen:
        selection = item.get("shortlist_selection") or {}
        roles[str(selection.get("role") or "unknown")] += 1
        mass_counts[len(item.get("groups") or [])] += 1
        if selection.get("region"):
            regions.add(str(selection["region"]))
    return {
        "method": "marginal_portfolio",
        "requested": max(0, int(cap)),
        "selected": len(chosen),
        "mass_counts": dict(sorted(mass_counts.items())),
        "regions": len(regions),
        "roles": dict(sorted(roles.items())),
        "weights": dict(SHORTLIST_WEIGHTS),
        "brief_is_tiebreak_only": True,
        "density_is_not_quality": True,
    }


def _stratum_quotas(
    strata: list[Any],
    cap: int,
    *,
    preferred: Any | None = None,
    available: dict[Any, int] | None = None,
) -> dict[Any, int]:
    """
    Near-equal slot shares across strata (|P| or relationship archetype).

    Not proportional to feasible-set size — a larger Bell slice must not
    dominate the shortlist. Leftover slots go to `preferred` first when set,
    otherwise round-robin. Quotas never exceed what each stratum still has.
    """
    strata = [k for k in strata if (available or {k: 1}).get(k, 0) > 0]
    if not strata or cap <= 0:
        return {}
    n = len(strata)
    if cap < n:
        # Still cover as many strata as possible (range first).
        order = list(strata)
        if preferred is not None and preferred in order:
            order = [preferred] + [k for k in order if k != preferred]
        return {k: (1 if i < cap else 0) for i, k in enumerate(order)}

    base = cap // n
    rem = cap % n
    quotas = {k: base for k in strata}
    order = list(strata)
    if preferred is not None and preferred in quotas:
        order = [preferred] + [k for k in order if k != preferred]
        quotas[preferred] += rem
    else:
        for i in range(rem):
            quotas[order[i % len(order)]] += 1

    if available:
        spill = 0
        for k in strata:
            room = int(available.get(k, 0))
            if quotas[k] > room:
                spill += quotas[k] - room
                quotas[k] = room
        if spill:
            for k in order:
                room = int(available.get(k, 0)) - quotas[k]
                if room <= 0:
                    continue
                take = min(room, spill)
                quotas[k] += take
                spill -= take
                if spill <= 0:
                    break
    return quotas


def _block_balance(assign: list[int]) -> float:
    """Higher when block sizes are more even (tie-break against mega+alone)."""
    if not assign:
        return 0.0
    counts: dict[int, int] = defaultdict(int)
    for b in assign:
        counts[b] += 1
    vals = list(counts.values())
    if not vals:
        return 0.0
    mean = sum(vals) / len(vals)
    var = sum((s - mean) ** 2 for s in vals) / len(vals)
    return -var


def _coexist_pairs(sig: frozenset[frozenset[str]]) -> frozenset[frozenset[str]]:
    pairs: set[frozenset[str]] = set()
    for block in sig:
        depts = sorted(str(d) for d in block)
        for i, a in enumerate(depts):
            for b in depts[i + 1 :]:
                pairs.add(frozenset({a, b}))
    return frozenset(pairs)


def _partition_distance(
    a: frozenset[frozenset[str]], b: frozenset[frozenset[str]]
) -> float:
    """Jaccard distance on which department pairs share a mass."""
    return _pair_set_distance(_coexist_pairs(a), _coexist_pairs(b))


def _pair_set_distance(
    left: frozenset[frozenset[str]], right: frozenset[frozenset[str]]
) -> float:
    """Jaccard distance on precomputed co-location pairs."""
    if not left and not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left ^ right) / len(union)


def _atom_blob(atom: dict[str, Any]) -> str:
    return " ".join(str(d).lower() for d in (atom.get("departments") or []))


def _academic_block_id(atoms: list[dict[str, Any]], assign: list[int]) -> int | None:
    """Block id that carries core/academic program, if any."""
    core = None
    academic = None
    for i, atom in enumerate(atoms):
        blob = _atom_blob(atom)
        if "core academic" in blob:
            core = assign[i]
            break
        if academic is None and "academic" in _families(atom):
            academic = assign[i]
    if core is not None:
        return core
    return academic


def _program_role(
    atoms: list[dict[str, Any]],
    assign: list[int],
    *,
    tokens: tuple[str, ...],
    academic_block: int | None,
) -> str:
    """
    Where one main program sits: with academic, alone, with athletics, or other.
    """
    idxs = [
        i
        for i, atom in enumerate(atoms)
        if any(tok in _atom_blob(atom) for tok in tokens)
    ]
    if not idxs:
        return "absent"
    block = assign[idxs[0]]
    if academic_block is not None and block == academic_block:
        return "with_academic"
    members = sum(1 for b in assign if b == block)
    if members <= 1:
        return "alone"
    ath_blocks = {
        assign[i]
        for i, atom in enumerate(atoms)
        if _families(atom) & {"athletics", "dining"}
    }
    if block in ath_blocks:
        return "with_athletics"
    return "other"


def _block_motif(atoms: list[dict[str, Any]], assign: list[int]) -> tuple[str, ...]:
    """
    Coarse role pattern for shortlist diversity.

    Tracks where art, media, and admin sit relative to the academic bar —
    enough to tell school-bar variants from art-on-academic / admin-alone
    basins without hardcoding full groupings.
    """
    if not atoms or not assign or len(atoms) != len(assign):
        return ("absent", "absent", "absent")
    academic_block = _academic_block_id(atoms, assign)
    return (
        _program_role(
            atoms, assign, tokens=("art", "music"), academic_block=academic_block
        ),
        _program_role(atoms, assign, tokens=("media",), academic_block=academic_block),
        _program_role(
            atoms,
            assign,
            tokens=("administration", "guidance"),
            academic_block=academic_block,
        ),
    )


def _gym_dining_role(atoms: list[dict[str, Any]], assign: list[int]) -> str:
    """Whether dining+athletics hold a mass of their own (the isolated bar)."""
    idxs = [i for i, a in enumerate(atoms) if _families(a) & {"athletics", "dining"}]
    if not idxs:
        return "absent"
    blocks = {assign[i] for i in idxs}
    if len(blocks) > 1:
        return "split"
    block = next(iter(blocks))
    riders = [i for i, b in enumerate(assign) if b == block and i not in set(idxs)]
    return "shared" if riders else "isolated"


def _academic_cohesion(atoms: list[dict[str, Any]], assign: list[int]) -> str:
    """Whether the academic family (core + special ed) keeps one wing."""
    idxs = [i for i, a in enumerate(atoms) if "academic" in _families(a)]
    if not idxs:
        return "absent"
    if len(idxs) < 2:
        return "single"
    return "together" if len({assign[i] for i in idxs}) == 1 else "split"


# Placement roles retained as readable coordinates for current school programs.
_ROLE_FEATURES: tuple[str, ...] = ("art", "media", "admin")


def _relationship_features(
    atoms: list[dict[str, Any]], assign: list[int]
) -> dict[str, str]:
    """
    Generic relationship features the shortlist must cover.

    Where art, media, and admin sit; whether dining+athletics keep their own
    mass; whether the academic family stays cohesive. Token matching only —
    no hardcoded groupings, so the same features read any program.
    """
    if not atoms or not assign or len(atoms) != len(assign):
        return {}
    art, media, admin = _block_motif(atoms, assign)
    return {
        "art": art,
        "media": media,
        "admin": admin,
        "gym_dining": _gym_dining_role(atoms, assign),
        "academic": _academic_cohesion(atoms, assign),
    }


def _relationship_family(atoms: list[dict[str, Any]], assign: list[int]) -> str:
    """
    Coarse organizational label for reports and diagnostics.

    Shortlist seats come from `_relationship_features` coverage, not from these
    four buckets — they collapse too many distinct organizations into one cell.
    Families (not partition distance, not school-prior score):
      - school_bars
      - arts_with_academic
      - arts_separate
      - other
    """
    if _is_school_bars(atoms, assign):
        return "school_bars"
    art = _block_motif(atoms, assign)[0]
    if art == "with_academic":
        return "arts_with_academic"
    if art == "alone":
        return "arts_separate"
    return "other"


def _relationship_archetype(atoms: list[dict[str, Any]], assign: list[int]) -> str:
    """Backward-compatible alias for relationship-family classification."""
    return _relationship_family(atoms, assign)


def department_atoms(session: Any) -> list[dict[str, Any]]:
    """One atom per department so P can regroup inside the constraints."""
    names: list[str] = []
    if hasattr(session, "department_names"):
        try:
            names = [str(d) for d in (session.department_names() or [])]
        except Exception:
            names = []
    if not names:
        names = [str(d) for m in (session.masses or []) for d in (m.departments or [])]
    home = {str(d): m for m in (session.masses or []) for d in (m.departments or [])}
    atoms: list[dict[str, Any]] = []
    seen: set[str] = set()
    for dept in names:
        if not dept or dept in seen:
            continue
        seen.add(dept)
        mass = home.get(dept)
        atoms.append(
            {
                "id": _slug(dept),
                "name": dept,
                "departments": [dept],
                "story_count": int(getattr(mass, "story_count", 2) or 2),
            }
        )
    return atoms


def _slug(name: str) -> str:
    token = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name)).strip("_")
    return token or "dept"


def _alone_as_apart(
    atoms: list[dict[str, Any]], alone: list[str]
) -> list[frozenset[str]]:
    """An alone department cannot share a mass with anyone."""
    names = [str(d) for atom in atoms for d in atom.get("departments") or []]
    pairs: list[frozenset[str]] = []
    for dept in alone:
        if dept not in names:
            continue
        for other in names:
            if other != dept:
                pairs.append(frozenset({dept, other}))
    return pairs


def atoms_from_session(session: Any) -> list[dict[str, Any]]:
    out = []
    for mass in session.masses or []:
        out.append(
            {
                "id": mass.id,
                "name": mass.name,
                "departments": list(mass.departments),
                "story_count": int(mass.story_count or 2),
            }
        )
    return out


def _glue(atoms: list[dict[str, Any]], together: list[frozenset[str]]) -> list[dict[str, Any]]:
    """Collapse atoms that a keep-together clause already bound."""
    n = len(atoms)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        a, b = find(i), find(j)
        if a != b:
            parent[b] = a

    home: dict[str, int] = {}
    for i, atom in enumerate(atoms):
        for dept in atom["departments"]:
            home[str(dept)] = i
    for pair in together:
        idxs = [home[d] for d in pair if d in home]
        for a, b in zip(idxs, idxs[1:]):
            union(a, b)

    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for i, atom in enumerate(atoms):
        buckets[find(i)].append(atom)
    glued = []
    for members in buckets.values():
        if len(members) == 1:
            glued.append(dict(members[0]))
            continue
        depts: list[str] = []
        stories = 2
        for atom in members:
            depts.extend(atom["departments"])
            stories = max(stories, int(atom.get("story_count") or 2))
        glued.append(_payload(depts, stories))
    return glued


def _atom_apart_pairs(atoms: list[dict[str, Any]], apart: list[frozenset[str]]) -> list[tuple[int, int]]:
    home: dict[str, int] = {}
    for i, atom in enumerate(atoms):
        for dept in atom["departments"]:
            home[str(dept)] = i
    pairs: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for pair in apart:
        idxs = [home.get(d) for d in pair]
        if None in idxs or len(idxs) < 2:
            continue
        a, b = int(idxs[0]), int(idxs[1])
        if a == b:
            continue
        key = (min(a, b), max(a, b))
        if key in seen:
            continue
        seen.add(key)
        pairs.append(key)
    return pairs


def _from_atoms(
    atoms: list[dict[str, Any]], assign: list[int], reason: str
) -> dict[str, Any]:
    blocks: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for i, atom in enumerate(atoms):
        blocks[assign[i]].append(atom)
    groups = []
    for members in blocks.values():
        if len(members) == 1:
            groups.append(
                {
                    "id": members[0]["id"],
                    "name": members[0]["name"],
                    "departments": list(members[0]["departments"]),
                    "story_count": int(members[0].get("story_count") or 2),
                }
            )
            continue
        depts: list[str] = []
        stories = 2
        for atom in members:
            depts.extend(atom["departments"])
            stories = max(stories, int(atom.get("story_count") or 2))
        groups.append(_payload(depts, stories))
    return {"groups": _uniquify(groups), "reason": reason, "source": "csp"}


def _payload(departments: list[str], stories: int) -> dict[str, Any]:
    families = sorted({_family_of(d) for d in departments})
    if len(families) == 1 and families[0] != "other":
        mass_id = families[0]
    else:
        mass_id = "_".join(families) if families else "mass"
    return {
        "id": mass_id,
        "name": _title(mass_id),
        "departments": list(departments),
        "story_count": max(1, int(stories or 2)),
    }


def _uniquify(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    used: set[str] = set()
    out = []
    for group in groups:
        mass_id = str(group["id"])
        base = mass_id
        n = 2
        while mass_id in used:
            mass_id = f"{base}_{n}"
            n += 1
        used.add(mass_id)
        item = dict(group)
        item["id"] = mass_id
        out.append(item)
    return out


def _signature(groups: list[dict[str, Any]]) -> frozenset[frozenset[str]]:
    return frozenset(frozenset(str(d) for d in g["departments"]) for g in groups)


def _assign_signature(
    atoms: list[dict[str, Any]], assign: list[int]
) -> frozenset[frozenset[str]]:
    """Same signature as `_signature`, without building the group payloads."""
    blocks: dict[int, set[str]] = defaultdict(set)
    for i, atom in enumerate(atoms):
        blocks[assign[i]].update(str(d) for d in atom["departments"])
    return frozenset(frozenset(b) for b in blocks.values())


def _families(atom: dict[str, Any]) -> set[str]:
    return {_family_of(d) for d in atom["departments"]}


def _reason(atoms: list[dict[str, Any]], assign: list[int]) -> str:
    if assign == list(range(len(atoms))):
        return "stated grouping"
    blocks: dict[int, list[int]] = defaultdict(list)
    for i, b in enumerate(assign):
        blocks[b].append(i)
    merges = [idxs for idxs in blocks.values() if len(idxs) > 1]
    if len(merges) == 1:
        fams: set[str] = set()
        for i in merges[0]:
            fams |= _families(atoms[i])
        if fams == {"athletics", "dining"}:
            return "colocate gym with dining"
        if fams == {"academic", "arts"}:
            return "colocate academic with arts"
        if fams == {"athletics", "dining", "arts"}:
            return "arts with gym and dining"
        if len(merges[0]) == 2:
            a, b = atoms[merges[0][0]], atoms[merges[0][1]]
            return f"colocate {a['name']} with {b['name']}"
    if len(blocks) == 2:
        fam_sets = [_families(atoms[i]) for i in range(len(atoms))]
        academic_only = [
            i for i, fams in enumerate(fam_sets) if fams == {"academic"}
        ]
        if academic_only and len({assign[i] for i in academic_only}) == 1:
            rest = [i for i in range(len(atoms)) if i not in academic_only]
            if rest and len({assign[i] for i in rest}) == 1:
                return "academic apart from a combined public/support bar"
    # Typical school three-bar: classroom wing | public/arts | athletics+dining.
    if len(blocks) >= 3 and _is_school_bars(atoms, assign):
        return "school bars: academic / public / athletics"
    return f"csp partition: {len(blocks)} masses"


def _is_school_bars(atoms: list[dict[str, Any]], assign: list[int]) -> bool:
    """Academic together, athletics/dining together, arts out of the classroom bar."""
    academic = [i for i, a in enumerate(atoms) if "academic" in _families(a)]
    arts = [i for i, a in enumerate(atoms) if "arts" in _families(a)]
    ath = [
        i
        for i, a in enumerate(atoms)
        if _families(a) & {"athletics", "dining"}
    ]
    if len(academic) < 1 or len(ath) < 1:
        return False
    if len({assign[i] for i in academic}) != 1:
        return False
    if len({assign[i] for i in ath}) != 1:
        return False
    if assign[academic[0]] == assign[ath[0]]:
        return False
    if arts and any(assign[i] == assign[academic[0]] for i in arts):
        return False
    return True


def _shape_bonus(atoms: list[dict[str, Any]], assign: list[int]) -> float:
    """
    Soft school-shaped tiebreak so COVER's 12–20 shortlist is not a random
    slice of hundreds of equally ranked partitions.

    Mass count is still not a quality signal — only organization shape.
    """
    if not atoms or not assign:
        return 0.0
    bonus = 0.0
    academic = [i for i, a in enumerate(atoms) if "academic" in _families(a)]
    arts = [i for i, a in enumerate(atoms) if "arts" in _families(a)]
    ath = [
        i
        for i, a in enumerate(atoms)
        if _families(a) & {"athletics", "dining"}
    ]
    if len(academic) >= 2 and len({assign[i] for i in academic}) == 1:
        bonus += 3.0
    elif len(academic) >= 2:
        bonus -= 1.5
    if ath and len({assign[i] for i in ath}) == 1:
        bonus += 2.0
        # In the school-bars prior the athletics+dining bar *is* its own bar:
        # a double-height gym does not host classrooms or offices.
        if _gym_dining_role(atoms, assign) == "isolated":
            bonus += 1.5
    if academic and arts:
        acad_block = assign[academic[0]]
        if all(assign[i] != acad_block for i in arts):
            bonus += 2.0
        else:
            # Arts jammed into the classroom bar often fights width locks.
            bonus -= 1.0
    # Core academic + special ed share a wing when both are atoms.
    core_i = sped_i = None
    media_i = None
    for i, atom in enumerate(atoms):
        blob = " ".join(str(d).lower() for d in (atom.get("departments") or []))
        if "core academic" in blob:
            core_i = i
        if "special education" in blob:
            sped_i = i
        if "media" in blob:
            media_i = i
    if core_i is not None and sped_i is not None and assign[core_i] == assign[sped_i]:
        bonus += 2.0
    # Media often rides the tall academic bar (top floor) rather than admin.
    if media_i is not None and academic and assign[media_i] == assign[academic[0]]:
        bonus += 1.0
    # Clinic / admin belong with the public bar, not the gym wing.
    for i, atom in enumerate(atoms):
        blob = " ".join(str(d).lower() for d in (atom.get("departments") or []))
        if not any(tok in blob for tok in ("medical", "administration", "guidance")):
            continue
        if ath and assign[i] == assign[ath[0]]:
            bonus -= 0.75
        if arts and assign[i] == assign[arts[0]]:
            bonus += 0.75
    # Light balance only — a glued gym atom as its own mass is common and legal.
    bonus += 0.05 * _block_balance(assign)
    return bonus


def _score(
    atoms: list[dict[str, Any]],
    assign: list[int],
    *,
    preferred_mass_count: int | None = None,
) -> tuple:
    """
    Semantic preference first. Mass count is not a quality signal by itself.

    Any allowed |P| range is flexible: higher does not beat lower unless the
    brief states a preferred mass count, in which case closer |P| ranks above
    farther |P| after the semantic tier. Shape bonus is a soft tiebreak so
    school-like bars surface in the COVER shortlist.
    """
    reason = _reason(atoms, assign)
    rank = {
        "stated grouping": 1000,
        "colocate gym with dining": 900,
        "school bars: academic / public / athletics": 850,
        "colocate academic with arts": 800,
        "arts with gym and dining": 700,
        "academic apart from a combined public/support bar": 600,
    }.get(reason, 200)
    if reason.startswith("colocate ") and rank == 200:
        # Mild note only — not enough to starve other |P| values in the shortlist.
        rank = 250
    shape = _shape_bonus(atoms, assign)
    if preferred_mass_count is None:
        return (rank, 0, shape)
    n_blocks = len(set(assign))
    # Closer to the stated preference wins; direction can be high or low.
    proximity = -abs(n_blocks - int(preferred_mass_count))
    return (rank, proximity, shape)


def _assignment_label(atoms: list[dict[str, Any]], assign: list[int]) -> str:
    blocks: dict[int, list[str]] = defaultdict(list)
    for i, b in enumerate(assign):
        blocks[b].append(str(atoms[i]["id"]))
    return " / ".join("+".join(names) for names in blocks.values())


def _atom_view(atom: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": atom["id"],
        "name": atom["name"],
        "departments": list(atom["departments"]),
    }
