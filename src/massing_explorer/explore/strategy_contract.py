"""Executable contract for the finite strategy space.

The contract describes what search may change, where values come from, what
locks them, and how each control is traversed. It is introspection, not a new
sampler: CSP, COVER, MCTS, and REALIZE keep their current behavior.
"""

from __future__ import annotations

from typing import Any

from .strategy import (
    grouping_is_required,
    preferred_mass_count,
    required_alone,
    required_apart,
    required_mass_bounds,
    required_together,
    topology_of,
)
from .topology import (
    UNSUPPORTED_D,
    UNSUPPORTED_T,
    paired_bars_drawable,
    stated_frontage_ft,
    topology_is_required,
)

CONTRACT_VERSION = 1

# Shared finite domains. COVER and typed actions import these values so the
# contract cannot drift away from the code that actually explores them.
LOADING_VALUES = ("double", "single")
ENVELOPE_VALUES = ("balanced", "compact", "elongated")
PLATE_PROFILE_VALUES = ("uniform", "step")
TOPOLOGY_VALUES = ("independent_bars", "paired_bars")

CONTROL_ORDER = (
    "program_organization",
    "story_pattern",
    "topology",
    "loading",
    "envelope",
    "plate_profile",
    "vertical_pins",
)


def strategy_space_contract(session: Any) -> dict[str, Any]:
    """Describe the active strategy grammar for one study as JSON-safe data."""
    constraints = dict(getattr(session, "constraints", None) or {})
    masses = list(getattr(session, "masses", None) or [])
    departments = _department_names(session, masses)
    story_cap = max(1, int(constraints.get("max_stories") or 4))
    story_locks = {
        str(key): int(value)
        for key, value in (constraints.get("story_lock") or {}).items()
    }
    partition_locked = grouping_is_required(session)
    topology_locked = topology_is_required(session)
    current_topology = topology_of(session)
    loading = str(constraints.get("loading") or "double")
    envelope = str(constraints.get("cover_envelope") or "balanced")
    plate_profile = _plate_profile(session)

    controls = [
        _program_control(session, masses, partition_locked),
        _story_control(masses, story_cap, story_locks),
        _topology_control(
            session,
            current=current_topology,
            locked=topology_locked,
        ),
        {
            "id": "loading",
            "group": "G",
            "meaning": "Single- or double-loaded circulation strategy.",
            "current": loading,
            "domain": [loading]
            if constraints.get("loading_required")
            else list(LOADING_VALUES),
            "domain_kind": "finite",
            "source": "brief or COVER",
            "locked": bool(constraints.get("loading_required")),
            "lock_rule": "loading_required",
            "identity_rule": "G.loading",
            "generator": "cover.build_cover_plan",
            "actions": []
            if constraints.get("loading_required")
            else ["SET_LOADING"],
            "neighbor_operation": "toggle single/double",
            "hard_pruning": ["required loading"],
            "searchable": not bool(constraints.get("loading_required")),
        },
        {
            "id": "envelope",
            "group": "G",
            "meaning": "Compactness family used to generate plate dimensions.",
            "current": envelope,
            "domain": list(ENVELOPE_VALUES),
            "domain_kind": "finite",
            "source": "COVER",
            "locked": False,
            "lock_rule": None,
            "identity_rule": "G.envelope",
            "generator": "cover.build_cover_plan",
            "actions": ["SET_ENVELOPE"],
            "neighbor_operation": "switch envelope family",
            "hard_pruning": [],
            "searchable": True,
        },
        {
            "id": "plate_profile",
            "group": "G",
            "meaning": "Uniform plate or a monotone stepped plate profile.",
            "current": plate_profile,
            "domain": list(PLATE_PROFILE_VALUES),
            "domain_kind": "finite",
            "source": "COVER",
            "locked": False,
            "lock_rule": None,
            "identity_rule": "G.plate_profile",
            "generator": "cover.build_cover_plan",
            "actions": [],
            "neighbor_operation": None,
            "hard_pruning": ["step collapses to uniform for one-story masses"],
            "searchable": True,
            "gap": "COVER samples this control, but MCTS has no typed plate-profile action.",
        },
        _vertical_control(session, departments),
    ]

    return {
        "version": CONTRACT_VERSION,
        "grammar": "S=(P,T,V,G,D)",
        "controls": controls,
        "control_order": list(CONTROL_ORDER),
        "coverage_product": [
            "program_organization",
            "story_pattern",
            "topology",
            "loading",
            "envelope",
            "plate_profile",
        ],
        "context": {
            "site_disposition": {
                "frontage_ft": stated_frontage_ft(session),
                "max_building_length_ft": constraints.get("max_building_length_ft"),
                "max_building_width_ft": constraints.get("max_building_width_ft"),
                "unsupported": list(UNSUPPORTED_D),
            },
            "double_height": list(getattr(session, "double_height_rooms", None) or []),
        },
        "realization_variables": [
            "width_ft",
            "length_ft",
            "floor_plate_area",
            "allocation",
        ],
        "unsupported_strategy": list(UNSUPPORTED_T),
        "known_gaps": [
            control["gap"] for control in controls if control.get("gap")
        ],
    }


def control_by_id(contract: dict[str, Any], control_id: str) -> dict[str, Any]:
    """Return one named control, or an empty record when absent."""
    for control in contract.get("controls") or []:
        if control.get("id") == control_id:
            return control
    return {}


def _program_control(
    session: Any,
    masses: list[Any],
    locked: bool,
) -> dict[str, Any]:
    bounds = required_mass_bounds(session)
    current_partition = sorted(
        [sorted(str(dept) for dept in (mass.departments or [])) for mass in masses]
    )
    hard_rules: list[str] = ["every program atom is assigned exactly once"]
    if bounds:
        hard_rules.append("required mass-count bounds")
    if required_together(session):
        hard_rules.append("required keep-together groups")
    if required_apart(session):
        hard_rules.append("required keep-apart pairs")
    if required_alone(session):
        hard_rules.append("required alone programs")
    return {
        "id": "program_organization",
        "group": "P",
        "meaning": "Partition all program atoms into building masses.",
        "current": {
            "mass_count": len(masses),
            "partition": current_partition,
        },
        "domain": {
            "kind": "csp_enumerated_partitions",
            "mass_count_bounds": list(bounds) if bounds else None,
            "preferred_mass_count": preferred_mass_count(session),
            "together": [sorted(group) for group in required_together(session)],
            "apart": [sorted(group) for group in required_apart(session)],
            "alone": sorted(required_alone(session)),
        },
        "domain_kind": "finite_enumerated",
        "source": "CSP",
        "locked": locked,
        "lock_rule": "partition_locked",
        "identity_rule": "sorted sets of department names; mass labels ignored",
        "generator": "csp.ordered_partition_candidates",
        "actions": [] if locked else ["APPLY_PARTITION"],
        "neighbor_operation": None
        if locked
        else "local_partition_candidates plus COVER-pool jumps",
        "hard_pruning": hard_rules,
        "searchable": not locked,
    }


def _story_control(
    masses: list[Any],
    cap: int,
    locks: dict[str, int],
) -> dict[str, Any]:
    per_mass: list[dict[str, Any]] = []
    for mass in masses:
        mass_id = str(mass.id)
        locked = mass_id in locks
        per_mass.append(
            {
                "mass_id": mass_id,
                "current": int(mass.story_count),
                "domain": [int(locks[mass_id])]
                if locked
                else list(range(1, cap + 1)),
                "locked": locked,
            }
        )
    fully_locked = bool(per_mass) and all(item["locked"] for item in per_mass)
    return {
        "id": "story_pattern",
        "group": "G",
        "meaning": "Exact story count owned by each mass.",
        "current": {str(mass.id): int(mass.story_count) for mass in masses},
        "domain": per_mass,
        "domain_kind": "finite_joint_vector",
        "source": "brief limits and COVER story-pattern library",
        "locked": fully_locked,
        "partially_locked": any(item["locked"] for item in per_mass),
        "lock_rule": "story_lock per mass",
        "identity_rule": "G.stories keyed by stable mass id",
        "generator": "cover.story_pattern_library",
        "actions": [] if fully_locked else ["SET_STORIES"],
        "neighbor_operation": "increment or decrement one unlocked mass",
        "hard_pruning": [f"1 <= stories <= {cap}", "per-mass story locks"],
        "searchable": not fully_locked,
    }


def _topology_control(
    session: Any,
    *,
    current: str,
    locked: bool,
) -> dict[str, Any]:
    if locked:
        domain = [current]
    else:
        domain = ["independent_bars"]
        if paired_bars_drawable(session):
            domain.append("paired_bars")
    if locked:
        actions: list[str] = []
    elif current == "paired_bars":
        actions = ["CLEAR_PAIRINGS"]
    elif "paired_bars" in domain:
        actions = ["PAIR_MASSES"]
    else:
        actions = []
    return {
        "id": "topology",
        "group": "T",
        "meaning": "Drawable relationship among realized masses.",
        "current": current,
        "domain": domain,
        "domain_kind": "finite_conditional",
        "source": "stated site frontage and topology engine",
        "locked": locked,
        "lock_rule": "topology_locked",
        "identity_rule": "T.kind",
        "generator": "cover.build_cover_plan and topology.pairing_proposals",
        "actions": actions,
        "neighbor_operation": None if locked else "pair or clear pairing",
        "hard_pruning": [
            "paired bars require at least two masses",
            "paired bars require a stated frontage",
        ],
        "searchable": not locked and len(domain) > 1,
        "derived": ["l_leftover from a realized double-height void"],
    }


def _vertical_control(session: Any, departments: list[str]) -> dict[str, Any]:
    pins = {
        str(key): int(value)
        for key, value in (getattr(session, "floor_pins", None) or {}).items()
    }
    eligible = [department for department in departments if department not in pins]
    return {
        "id": "vertical_pins",
        "group": "V",
        "meaning": "Explicit department-to-level requirements or search probes.",
        "current": pins,
        "domain": {
            "existing_locked": pins,
            "search_neighbors": [
                {"department": department, "level": 0} for department in eligible
            ],
        },
        "domain_kind": "finite_monotone_neighbors",
        "source": "brief plus MCTS ground-pin probes",
        "locked": not bool(eligible),
        "lock_rule": "existing pins are preserved; search only adds a ground pin",
        "identity_rule": "V.pins sorted by department and exact level",
        "generator": "mcts.catalog_actions",
        "actions": ["PIN_GROUND"] if eligible else [],
        "neighbor_operation": "add one ground-floor pin",
        "hard_pruning": ["existing brief pins cannot be overwritten"],
        "searchable": bool(eligible),
    }


def _department_names(session: Any, masses: list[Any]) -> list[str]:
    method = getattr(session, "department_names", None)
    if callable(method):
        return sorted(str(name) for name in method())
    return sorted(
        {str(dept) for mass in masses for dept in (mass.departments or [])}
    )


def _plate_profile(session: Any) -> str:
    if getattr(session, "floor_tapers", None) or getattr(session, "floor_steps", None):
        return "step"
    return "uniform"
