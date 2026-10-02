# Work status — 2026-10-02

## Initial-P shortlist

The current uncommitted implementation builds a marginal-value portfolio from
the deterministic CSP landscape. It protects mass-count strata, then selects
organizations that add descriptor coordinates, relationship evidence,
partition difference, capacity plausibility, and information value. Brief
relevance is only a light tie-break because it already guides landscape
sampling. Each selected organization records a selection explanation.

## Reconnect checkpoint

- Base commit: `82cbe45` (`Build deterministic CSP landscape sampler`)
- Current implementation committed as `604e711` (`Implement deterministic CSP
  landscape and P portfolio shortlist`).
- Focused CSP landscape tests previously reported: `12/12` sampling and `9/9`
  integration checks.
- On resume, one regression was reproduced and fixed: when normalized
  `p_constraints` existed, `required_together()` also merged a raw briefing
  `same_mass` clause, which could collapse all departments into one group.
- The shortlist now uses a hybrid portfolio selector: marginal feature value
  remains the main policy, while a small archetype floor is protected when a
  mass-count stratum has enough seats. The archetype floor is ordered
  deterministically and does not hard-code department names.
- Focused shortlist/landscape suite after the hybrid change: `33/33` passed,
  including the Underwood 3–4-mass legal-yield regression.
- Full-suite result: 477 tests ran, with 21 failures, 10 errors, and 3
  skipped. Those failures span broader legacy/integration areas; the focused
  P-landscape/shortlist suite remains 33/33.

Keep this checkpoint updated before long test runs or further edits.
