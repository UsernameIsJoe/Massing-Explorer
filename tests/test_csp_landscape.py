from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from massing_explorer.explore import csp
from massing_explorer.explore.csp_landscape import (
    _restricted_growth_fixed,
    build_partition_landscape,
    describe_partition,
    stirling_second,
)
from massing_explorer.models import Department, ProgramStudy


def _atoms(n: int) -> list[dict]:
    return [
        {
            "id": f"d{i}",
            "name": f"D{i}",
            "departments": [f"D{i}"],
            "story_count": 2,
        }
        for i in range(n)
    ]


def _session(*, preferences: list[dict] | None = None) -> SimpleNamespace:
    program = ProgramStudy()
    program.departments = [
        Department(name=f"D{i}", nfa_sf=900 + i * 100, target_gsf=1000 + i * 100)
        for i in range(9)
    ]
    return SimpleNamespace(
        program=program,
        floor_pins={"D0": 0, "D1": 0},
        double_height_rooms=[],
        constraints={
            "briefing": {
                "requirements": [],
                "limitations": [],
                "preferences": preferences or [],
            },
            "max_building_length_ft": 100,
            "max_building_width_ft": 80,
            "max_stories": 3,
        },
    )


class TestCspLandscape(unittest.TestCase):
    def test_stirling_counts_partition_strata(self) -> None:
        self.assertEqual(stirling_second(5, 1), 1)
        self.assertEqual(stirling_second(5, 2), 15)
        self.assertEqual(stirling_second(5, 3), 25)
        self.assertEqual(sum(stirling_second(5, k) for k in range(1, 6)), 52)

    def test_large_space_sampling_is_reproducible_and_not_a_dfs_prefix(self) -> None:
        atoms = _atoms(8)
        first, _, report_a = build_partition_landscape(
            atoms,
            k_min=4,
            k_max=4,
            apart_pairs=[],
            budget=40,
        )
        second, _, report_b = build_partition_landscape(
            atoms,
            k_min=4,
            k_max=4,
            apart_pairs=[],
            budget=40,
        )
        prefix = {
            tuple(assign)
            for _, assign in zip(range(40), _restricted_growth_fixed(8, 4))
        }
        self.assertEqual(first, second)
        self.assertEqual(report_a, report_b)
        self.assertTrue(any(tuple(assign) not in prefix for assign in first))
        self.assertEqual(report_a["method"], "deterministic_stratified_landscape")

    def test_sampling_keeps_every_mass_count_stratum_visible(self) -> None:
        _, _, report = build_partition_landscape(
            _atoms(9),
            k_min=2,
            k_max=7,
            apart_pairs=[],
            budget=120,
            preferred_mass_count=3,
        )
        self.assertTrue(all(row["retained"] > 0 for row in report["strata"].values()))
        self.assertGreater(report["strata"][3]["retained"], report["strata"][7]["retained"])
        self.assertAlmostEqual(report["coverage_floor_share"], 0.25)

    def test_descriptor_is_invariant_to_mass_labels(self) -> None:
        atoms = _atoms(4)
        session = _session()
        left = describe_partition(atoms, [0, 0, 1, 2], session=session)
        right = describe_partition(atoms, [2, 2, 0, 1], session=session)
        self.assertEqual(left, right)
        self.assertEqual(left["structure"]["mass_count"], 3)
        self.assertIn("area_distribution", left)
        self.assertIn("constraint_pressure", left)
        self.assertIn("relationships", left)
        self.assertIn("confidence", left)

    def test_brief_preference_changes_attention_without_erasing_coverage(self) -> None:
        atoms = _atoms(9)
        neutral, _, neutral_report = build_partition_landscape(
            atoms,
            k_min=3,
            k_max=5,
            apart_pairs=[],
            budget=80,
            session=_session(),
        )
        focused, _, focused_report = build_partition_landscape(
            atoms,
            k_min=3,
            k_max=5,
            apart_pairs=[],
            budget=80,
            session=_session(
                preferences=[
                    {"lever": "same_mass", "departments": ["D0", "D1"]}
                ]
            ),
        )
        neutral_colocated = sum(assign[0] == assign[1] for assign in neutral)
        focused_colocated = sum(assign[0] == assign[1] for assign in focused)
        self.assertGreater(focused_colocated, neutral_colocated)
        self.assertTrue(
            all(row["retained"] > 0 for row in focused_report["strata"].values())
        )
        self.assertEqual(
            set(neutral_report["strata"]),
            set(focused_report["strata"]),
        )

    def test_keep_apart_filters_before_landscape_allocation(self) -> None:
        selected, rejected, report = build_partition_landscape(
            _atoms(8),
            k_min=3,
            k_max=5,
            apart_pairs=[(0, 1)],
            budget=60,
        )
        self.assertTrue(selected)
        self.assertTrue(rejected)
        self.assertTrue(all(assign[0] != assign[1] for assign in selected))
        self.assertFalse(report["feasible_count_exact"])

    def test_solve_partitions_passes_landscape_to_unchanged_shortlist(self) -> None:
        atoms = _atoms(8)
        with patch.object(csp, "MAX_ENUM", 40):
            first = csp.solve_partitions(atoms, cap=8, preferred_mass_count=4)
            second = csp.solve_partitions(atoms, cap=8, preferred_mass_count=4)
        self.assertEqual(first["chosen"], second["chosen"])
        self.assertEqual(first["feasible_count"], 40)
        self.assertFalse(first["feasible_count_exact"])
        self.assertEqual(
            first["landscape"]["method"],
            "deterministic_stratified_landscape",
        )
        self.assertEqual(len(first["chosen"]), 8)


if __name__ == "__main__":
    unittest.main()
