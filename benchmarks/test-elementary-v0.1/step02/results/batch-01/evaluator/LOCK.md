# Fable evaluator lock — Step-01 batch-01

Status: **LOCKED BEFORE UNMASKING**

Source evaluator artifacts:
- `Canonicalization Scoring.docx`
  - SHA-256: `6d56612840fffab2cc9a44371dd3062a4b80060d0a81d8900118c64d872ec6bf`
- `Behavior Scoring.docx`
  - SHA-256: `3f628dd40116a54b1f9a938e5e2a149c796337ea3fe2e7a768f3024c49c4fed3`

Audit result:
- R01–R12 are present in both evaluator outputs.
- Quality has four reviewer axes for every case; all detailed scores match its batch summary.
- Behavior has all eleven protocol axes for every case; all detailed scores match its batch summary.
- Representation status / representation expansion is `unknown` for all 12 because the Massing Explorer representation was intentionally not supplied to the evaluator. This is a deferred Layer-2 field, not missing evaluation work.
- No case-level model, condition, or run identity appears in the evaluator score outputs.
- No score edits were made during this audit.

Protocol annotations preserved without score changes:
1. Quality includes an L-arm applicability check; it is N/A/PASS across the batch and does not alter the locked results.
2. R05/R10 contain some dimension commitments that are asserted rather than independently test-fit. Quality preserves the evaluator's PASS judgments; behavior separately captures the weaker verification evidence.
3. The behavior evaluator reconstructed a 12-item hard-requirement checklist because the brief was not attached. Its observable-behavior scores are preserved exactly as returned.

Lock rule:
After the shuffle key is revealed, these score values must not be changed because of model/condition identity or downstream results. A change is permitted only for a documented extraction or factual-reading error, with the original value retained in the audit trail.

The two CSV files in this directory are exact transcriptions of the locked batch summary score tables and are the values used for downstream analysis.
