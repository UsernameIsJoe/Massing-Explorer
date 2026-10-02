"""The finite strategy grammar is explicit and synchronized with search."""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

from massing_explorer.explore.cover import ENVELOPES, LOADINGS, PLATE_PROFILES
from massing_explorer.explore.actions import apply_action
from massing_explorer.explore.planner import plan_context
from massing_explorer.explore.strategy_contract import (
    CONTROL_ORDER,
    ENVELOPE_VALUES,
    LOADING_VALUES,
    PLATE_PROFILE_VALUES,
    control_by_id,
    strategy_space_contract,
)
from massing_explorer.study_state import MassGrouping


def _session(**constraint_updates):
    constraints = {
        "max_stories": 3,
        "p_constraints": {
            "mass_count_min": 2,
            "mass_count_max": 3,
            "together": [["GYM", "DINING"]],
            "apart": [["CORE", "ADMIN"]],
            "alone": ["ADMIN"],
            "preferred_mass_count": 3,
        },
        "briefing": {"requirements": [], "limitations": [], "preferences": []},
    }
    constraints.update(constraint_updates)
    masses = [
        MassGrouping(
            id="academic",
            name="Academic",
            departments=["CORE", "ADMIN"],
            story_count=2,
        ),
        MassGrouping(
            id="public",
            name="Public",
            departments=["GYM", "DINING"],
            story_count=3,
        ),
    ]
    return SimpleNamespace(
        constraints=constraints,
        masses=masses,
        pairings=[],
        floor_pins={"ADMIN": 0},
        double_height_rooms=["GYM"],
        floor_tapers={},
        floor_steps={},
        last_massing={},
        department_names=lambda: ["CORE", "ADMIN", "GYM", "DINING"],
    )


class StrategyContractTests(unittest.TestCase):
    def test_contract_separates_controls_context_and_realization(self) -> None:
        contract = strategy_space_contract(_session())
        self.assertEqual(
            [control["id"] for control in contract["controls"]],
            list(CONTROL_ORDER),
        )
        self.assertEqual(contract["grammar"], "S=(P,T,V,G,D)")
        self.assertIn("width_ft", contract["realization_variables"])
        self.assertNotIn("width_ft", contract["control_order"])
        self.assertIn("site_disposition", contract["context"])
        json.dumps(contract)  # planner/UI introspection must remain serializable

    def test_program_contract_records_csp_bounds_and_hard_relations(self) -> None:
        control = control_by_id(
            strategy_space_contract(_session()), "program_organization"
        )
        self.assertEqual(control["domain"]["mass_count_bounds"], [2, 3])
        self.assertEqual(control["domain"]["preferred_mass_count"], 3)
        self.assertEqual(control["domain"]["together"], [["DINING", "GYM"]])
        self.assertEqual(control["domain"]["alone"], ["ADMIN"])
        self.assertFalse(control["locked"])
        self.assertEqual(control["actions"], ["APPLY_PARTITION"])

    def test_domains_share_one_source_with_cover(self) -> None:
        self.assertIs(ENVELOPES, ENVELOPE_VALUES)
        self.assertIs(LOADINGS, LOADING_VALUES)
        self.assertIs(PLATE_PROFILES, PLATE_PROFILE_VALUES)
        contract = strategy_space_contract(_session(max_total_length_ft=300.0))
        self.assertEqual(
            control_by_id(contract, "loading")["domain"], list(LOADINGS)
        )
        self.assertEqual(
            control_by_id(contract, "envelope")["domain"], list(ENVELOPES)
        )
        self.assertEqual(
            control_by_id(contract, "plate_profile")["domain"],
            list(PLATE_PROFILES),
        )

    def test_locks_narrow_domains_instead_of_only_labeling_them(self) -> None:
        session = _session(
            partition_locked=True,
            topology_locked=True,
            loading_required=True,
            loading="single",
            story_lock={"academic": 2, "public": 3},
        )
        contract = strategy_space_contract(session)
        self.assertTrue(control_by_id(contract, "program_organization")["locked"])
        self.assertEqual(control_by_id(contract, "topology")["domain"], ["independent_bars"])
        self.assertEqual(control_by_id(contract, "loading")["domain"], ["single"])
        stories = control_by_id(contract, "story_pattern")
        self.assertTrue(stories["locked"])
        self.assertEqual(stories["actions"], [])

    def test_conditional_topology_and_known_action_gap_are_honest(self) -> None:
        no_site = strategy_space_contract(_session())
        topology = control_by_id(no_site, "topology")
        self.assertEqual(topology["domain"], ["independent_bars"])
        self.assertFalse(topology["searchable"])

        with_site = strategy_space_contract(_session(max_total_length_ft=300.0))
        topology = control_by_id(with_site, "topology")
        self.assertEqual(topology["domain"], ["independent_bars", "paired_bars"])
        self.assertTrue(topology["searchable"])

        plate = control_by_id(with_site, "plate_profile")
        self.assertEqual(plate["actions"], [])
        self.assertIn("MCTS", plate["gap"])
        self.assertEqual(with_site["known_gaps"], [plate["gap"]])

    def test_planner_sees_the_same_contract(self) -> None:
        session = _session(max_total_length_ft=300.0)
        archive = {"attempts": 0, "cells": {}, "unsupported": [], "note": ""}
        context = plan_context(session, archive)
        self.assertEqual(
            context["strategy_contract"], strategy_space_contract(session)
        )
        self.assertIn("APPLY_PARTITION", context["allowed_ops"])
        self.assertIn("PAIR_MASSES", context["allowed_ops"])
        self.assertNotIn("COLOCATE", context["allowed_ops"])
        self.assertNotIn("SET_WIDTH", context["allowed_ops"])

    def test_locked_partition_actions_cannot_mutate_p(self) -> None:
        session = _session(partition_locked=True)
        before = [list(mass.departments) for mass in session.masses]
        for action in (
            {"op": "COLOCATE", "programs": ["CORE", "GYM"]},
            {"op": "KEEP_APART", "programs": ["CORE", "ADMIN"]},
        ):
            out = apply_action(session, action)
            self.assertFalse(out["ok"])
            self.assertIn("required", out["reason"])
        self.assertEqual(before, [list(mass.departments) for mass in session.masses])

    def test_ground_pin_cannot_overwrite_an_existing_pin(self) -> None:
        session = _session()
        session.floor_pins["CORE"] = -1
        out = apply_action(session, {"op": "PIN_GROUND", "programs": ["CORE"]})
        self.assertFalse(out["ok"])
        self.assertEqual(session.floor_pins["CORE"], -1)


if __name__ == "__main__":
    unittest.main()
