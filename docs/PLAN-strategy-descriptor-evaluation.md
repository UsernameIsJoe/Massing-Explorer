# Plan: strategy controls, descriptor model, and evaluation scorecard

Recorded 1 Oct 2026. This is the working migration guideline for bringing the
current repository toward the three-layer structure discussed after the
project-level review. It does **not** replace `BLUEPRINT-search.md` as project
law until it is explicitly accepted as a new milestone.

The project remains strategy-first. Form is the deterministic realization of
strategy, not the primary object being optimized.

## Current implementation status — 2 Oct 2026

The strategy → descriptor → evaluation flow is now active at the P-landscape
boundary. CSP builds a deterministic landscape of program organizations,
records cheap descriptor coordinates, and the initial-P selector admits a
portfolio. The selector protects mass-count strata and a small archetype floor,
then uses marginal descriptor/relationship coverage, partition difference,
capacity plausibility, and information value. Brief relevance is a light
tie-break because the brief already guides landscape attention. Each admitted P
records its selection rationale.

This implementation is committed in `604e711`. The focused landscape and
shortlist suite passes `33/33`, including the Underwood 3–4-mass legal-yield
regression. The downstream evaluation layer and full repository regression
suite remain separate follow-up work.

## Checkpoint: explicit representation boundaries

Accepted 1 Oct 2026 and tagged `checkpoint-three-layer-contracts-2026-10-01`.

This checkpoint establishes behavior-preserving interfaces for the three
roles that were previously mixed:

| Role | Canonical interface | Compatibility retained |
|---|---|---|
| Search projection | `encode_search_projection(strategy)` | `encode_strategy(...)` |
| Realized descriptors | `describe_result(result, context)` | Flat performance fields |
| Soft evaluation | `evaluate_descriptors(descriptors, context)` | `eval_composites(...)` |

The four evaluation formulas, legal gate, search budgets, and CSP ordering are
unchanged. Focus now moves to the strategy-space contract described below.

### Work after this checkpoint

The first strategy-contract implementation now lives in
`explore/strategy_contract.py`. It exposes the active domain, current value,
lock rule, generator, typed actions, pruning rules, and identity rule for each
search control. COVER and typed actions share its finite loading, envelope,
and plate-profile domains; planner context receives only actions currently
available under the contract.

The audit also recorded one remaining traversal gap: COVER samples plate
profiles, but MCTS has no typed plate-profile neighbor action. Exact widths
remain realization/repair variables rather than strategy controls.

---

## Goal

Give every candidate a clear causal path:

```text
PROJECT CONTEXT + HARD CONSTRAINTS
                 │
                 ▼
        1. STRATEGY CONTROLS
        what search can change
                 │
                 ▼
              REALIZE
       exact geometry and allocation
                 │
                 ▼
         2. DESCRIPTOR MODEL
       factual properties of the result
           │                 │
           │                 └── compact search projection
           │                         │
           ▼                         ▼
   3. EVALUATION SCORECARD      COVER / BO / landscape
   project-dependent judgment   similarity and uncertainty
                 │                         │
                 └──────────┬──────────────┘
                            ▼
                    SEARCH CONTROLLER
```

Plain-language rule:

| Layer | Question |
|---|---|
| Strategy controls | What can the search intentionally change? |
| Descriptor model | What objectively resulted? |
| Evaluation scorecard | How well does that result serve this brief? |

Hard constraints, preferences, site facts, GSF, and future market or carbon
assumptions are project context. They affect generation and judgment, but they
are not automatically axes.

---

## Why change the current structure

The repository already contains the three roles, but their boundaries are
mixed.

| Current condition | Target condition |
|---|---|
| `strategy.py` stores structured decisions | Keep one canonical strategy contract |
| `axes.py` calls a strategy encoding nine descriptor axes | Treat this as a search projection, not the full description |
| BO actually receives 66 partition bits plus eight scalars | Make the machine encoding explicit and separate from UI labels |
| `performance.py` calculates useful raw properties separately | Promote those properties into one full descriptor record |
| Four evaluation composites read those raw properties | Make every score traceable to named descriptors and brief criteria |
| Novelty is calculated differently in strategy and evaluation space | Name the two purposes and stop treating them as interchangeable |

This change is for clarity, validation, and future expansion. It is not a
reason to rewrite working search engines all at once.

---

## Layer 1 — strategy controls

### Contract

A strategy control is a decision the search can set before realization. It
must have:

1. an architecturally meaningful name;
2. a finite or explicitly bounded domain;
3. a canonical representation independent of enumeration order;
4. hard rules stating when it is locked or unsupported;
5. at least one typed action or generator capable of changing it.

### Current strategy grammar

```text
S = (P, T, V, G, D)
```

| Group | Current content | Direction |
|---|---|---|
| P — program organization | Mass count and department partition | Keep as the organizational backbone |
| T — topology | Independent and paired bars; partial L-leftover signal | Search only drawable topologies |
| V — vertical strategy | Floor pins, stacking, double height, locks | Separate locked requirements from open decisions |
| G — geometric strategy | Stories, loading, envelope, plate profile | Keep categorical strategy; exact feet stay outside |
| D — site disposition | Frontage and dimensional limits | Treat current values mainly as context/constraints |

The initial searchable strategy product is:

```text
P × story pattern × topology × loading × envelope × plate profile
```

Exact widths and lengths are not strategy coordinates. `realize(s)` chooses
them under the brief and solver constraints.

### Initial population rule

P remains the first organizational factor, but P alone is not enough to admit
or reject an initial search region. Each admitted P should eventually carry a
cheap capacity/story envelope derived from:

- assigned GSF per mass;
- ground-floor-required GSF;
- double-height demand;
- required widths;
- lower-bound story demand;
- site and length capacity;
- large-volume concentration.

Use those facts to order and allocate probes. The current CSP landscape keeps a
coverage floor across allowed mass-count strata, then spends remaining sample
capacity using brief relevance, bounded capacity plausibility, uncertainty,
rarity, and diminishing returns. Remove a branch only when it is provably
impossible. A weak prior is a reason for fewer probes, not zero coverage.

The initial-P shortlist applies a separate portfolio policy. It does not simply
repeat the landscape score: it protects mass-count coverage, preserves a
limited archetype floor when seats permit, and fills remaining seats by
marginal information and organizational difference.

### First work item

Create a strategy-space contract listing, for every control:

| Required field | Purpose |
|---|---|
| Name and meaning | Architectural interpretation |
| Domain | What values can exist |
| Source | Brief, CSP, engine, or derived library |
| Lock rule | When search cannot change it |
| Canonical ID | Stable identity independent of enumeration |
| Generator/action | How candidates are created |
| Hard pruning | What proves impossibility |
| Neighbor operation | How MCTS or REFINE changes it |

Do this before redesigning BO or the descriptor encoding.

---

## Layer 2 — descriptor model

### Contract

A descriptor is a factual property measured from a strategy or its realized
scheme. It should not say whether the property is good or bad.

Examples:

| Descriptor | Not a descriptor |
|---|---|
| Circulation ratio = 0.18 | Circulation quality = good |
| Program concentration = 0.72 | Program coherence = 0.84 |
| Mean height = 2.3 stories | Height alignment = 0.90 |
| Leftover usable area = 0.08 | Efficiency = 0.86 |

### Two representations inside one descriptor layer

Do not force all information into one nine-number vector.

| Representation | Job |
|---|---|
| Full descriptor record | Preserve enough facts for exact scoring and explanation |
| Compact search projection | Support distance, coverage, novelty, BO, and uncertainty |

The compact projection is derived from the full record. It is not the source
of truth.

### Current material to retain

The current repository already measures useful full-descriptor candidates:

- spread;
- height variance;
- footprint likeness;
- realized lengths;
- preference distance;
- leftover area;
- fragmentation;
- awkward program splits;
- anchor fit;
- public programs on grade;
- street-edge usage as a diagnostic.

The current nine named probe axes should initially remain as a compatibility
projection, but each must be audited:

| Current axis | Required audit |
|---|---|
| Program organization | Keep label-invariant pairwise relationships; document the 66-value machine block |
| Mass count | Confirm normalization does not distort relevant ranges |
| Distribution balance | Replace department counts with GSF-aware measures where appropriate |
| Topology | Do not encode unsupported topology as if it were searchable |
| Loading | Keep if it predicts meaningful differences |
| Mean height | Replace ownership-weighted naming with an interpretable measure or rename it |
| Height articulation | Validate against recognizable stacking differences |
| Vertical organization | Replace hashed department-name encoding with explicit relational facts |
| Geometric character | Separate envelope character from plate stepping if both matter |

### Validation rule

A compact descriptor earns its place only if it improves at least one of:

- recognition of strategically similar schemes;
- legal-status prediction;
- evaluation prediction;
- coverage measurement;
- duplicate detection;
- an explanation an architect can understand.

If it serves none of these, keep it as metadata or remove it from the search
projection.

---

## Layer 3 — evaluation scorecard

### Contract

Evaluation attaches project-dependent judgment to the descriptor record:

```text
scores = evaluate(full_descriptors, brief, preferences, assumptions)
```

It is a scorecard, not another required search landscape.

Keep the current four soft scores initially:

| Score | Current purpose |
|---|---|
| Program coherence | Program continuity and public-on-grade behavior |
| Preference alignment | Fit to stated soft preferences |
| Performance efficiency | Area use and footprint consistency |
| Robustness | Performance under perturbation or a clearly labeled proxy |

### Rules

1. Keep hard legality separate from soft quality.
2. Every score must list the descriptors and brief rules that produced it.
3. Do not hide trade-offs inside one score before presenting the scorecard.
4. A combined reward may guide search, but it is not the underlying evidence.
5. Label proxies honestly. Untested robustness is not proven robustness.
6. New domains add their own score families; they do not get forced into the
   existing four architectural scores.

Example future extension:

| Domain | Descriptors | Evaluations |
|---|---|---|
| Carbon | Material quantities, envelope area | Embodied and operational carbon |
| Schedule | Phase count, dependency structure | Duration and disruption |
| Finance | Cost timing, rentable area | Cost, return, and risk |

These are examples of scalability, not current implementation targets.

---

## How search uses the layers

| Engine | Strategy controls | Descriptors | Evaluations |
|---|---|---|---|
| CSP | Enumerate and constrain P | Cheap capacity/relationship facts | No final quality judgment |
| COVER | Select broad strategy combinations | Measure coverage and underexplored regions | Observe legal yield and early quality |
| REALIZE | Freeze strategy | Produce physical quantities and full descriptors | Supply exact evidence |
| REPAIR | Change permitted controls near a failed case | Read violation and headroom facts | Minimize feasibility distance first |
| MCTS | Traverse typed strategy actions | Recognize related states | Backpropagate feasibility and quality |
| BO | Propose unevaluated strategies | Model outcomes over validated coordinates | Predict score and uncertainty |
| REFINE | Make local permitted changes | Detect saturation and nearby gaps | Improve selected trade-offs |
| Landscape ledger | Identify regions | Store coverage, uncertainty, failure profile | Store potential and observed trade-offs |

Evaluation can guide the next sample without becoming a strategy control. BO
and the controller read evaluated outcomes, predict them in descriptor space,
then select a new strategy to realize.

---

## Migration sequence

Do not perform a big-bang rewrite.

| Phase | Change | Required gate |
|---:|---|---|
| 0 | Freeze current benchmark outputs and budgets | Reproducible baseline |
| 1 | Define the strategy-space contract | Every open control has a domain, lock, ID, and action |
| 2 | Fix known CSP/P-pool correctness problems | Feasibility tie-break works; admitted P receives fair probes |
| 3 | Introduce a full descriptor record without changing scores | Existing legal status and four scores remain equal within tolerance |
| 4 | Make evaluation formulas read only the descriptor contract plus context | Traceable score provenance |
| 5 | Separate machine search projection from UI descriptor labels | No hidden 9-versus-74 ambiguity |
| 6 | Validate each search descriptor | Neighborhood and prediction tests beat simple baselines |
| 7 | Switch COVER novelty and BO distance one component at a time | Same-budget ablation shows benefit |
| 8 | Add the landscape ledger | Every region has status, evidence, effort, and reopen condition |
| 9 | Add the unified controller | Allocation beats the fixed pipeline under the same budget |

Do not start phases 8–9 until the earlier representations are trustworthy.

---

## Validation plan

### Representation tests

| Test | Question |
|---|---|
| Canonical identity | Do relabeled equivalent strategies encode identically? |
| Neighborhood consistency | Do nearby descriptors correspond to recognizable similarity? |
| Legal correlation | Are nearby points more likely to share legal status than random pairs? |
| Evaluation correlation | Are nearby points more similar in score than random pairs? |
| Missing-factor audit | Which large outcome differences are unexplained by current descriptors? |

### Search tests

Compare every new policy under the same evaluation budget against:

- current deterministic pipeline;
- fair stratified sampling;
- simple random sampling where useful;
- saved 53c and current benchmark cases;
- small cases that can be exhaustively enumerated.

Report:

- number of legal organizations;
- legal yield;
- best and top-k quality;
- Pareto diversity;
- organization and descriptor coverage;
- duplicate rate;
- cost in evaluations;
- stability as additional budget is added;
- calibration of predicted legality and quality.

One benchmark prompt is not evidence of generality. Add briefs that change
program type, mass-count range, site pressure, height, and relationship rules.

---

## What to avoid

| Avoid | Reason |
|---|---|
| Treating the nine UI axes as a complete description | BO currently uses 74 values and evaluation reads other properties |
| Letting enumeration order define architectural similarity | Recursive order is an implementation detail |
| Pruning a branch because a prior dislikes it | Creates self-confirming search bias |
| Adding every measurable value as an axis | High dimensions weaken limited-data models and explanation |
| Using one combined reward as the evidence record | Hides trade-offs and prevents reweighting |
| Mixing hard legality into soft preference scores | A strong preference must never unlock a failed requirement |
| Calling a proxy a measured result | Produces false confidence, especially for robustness |
| Hard-coding current school motifs into general architecture | Risks benchmark overfitting |
| Changing generator, descriptors, scoring, and budgets together | Makes regressions impossible to diagnose |
| Claiming the global optimum without exhaustive proof or bounds | The correct product is best-supported strategies plus uncertainty |

---

## Direction to hold

The target is not a larger generator. It is a self-aware strategic search
system that can state:

- what decisions define the available space;
- what regions it has and has not examined;
- what it currently predicts about unseen regions;
- why it focused or stepped back;
- what trade-offs the finalists represent;
- what uncertainty remains and what would trigger reopening a region.

The immediate priority is the strategy-space contract. Descriptor refactoring
comes after the finite grammar is explicit. The evaluation scorecard remains
stable during that work so the repository keeps a trustworthy baseline.
