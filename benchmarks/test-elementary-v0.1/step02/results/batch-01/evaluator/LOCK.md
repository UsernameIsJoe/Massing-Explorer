# Fable evaluator record — Step-01 batch-01

Source evaluator artifacts:
- `Canonicalization Scoring.docx`
  - SHA-256: `6d56612840fffab2cc9a44371dd3062a4b80060d0a81d8900118c64d872ec6bf`
- `Behavior Scoring.docx`
  - SHA-256: `3f628dd40116a54b1f9a938e5e2a149c796337ea3fe2e7a768f3024c49c4fed3`

Audit result:
- R01–R12 are present in both evaluator outputs.
- Quality has four reviewer axes for every case; all detailed scores match its batch summary.
- Behavior has all eleven protocol axes for every case; all detailed scores match its batch summary.
- Representation status / representation expansion is `unknown` for all 12 because the Massing Explorer representation was not supplied to the evaluator.
- No score edits were made during this audit.
- The score outputs state that model/condition were masked and not inferred, but the actual shuffled input file contradicts that methodological claim because identity metadata remained visible.

Use restriction:
- These scores may be retained as an identity-exposed evaluator pass.
- They must **not** be described or cited as a blinded evaluator result.
- They must **not** serve as the primary blinded comparison for ChatGPT vs Opus or A0 vs A1.
- Any future valid blinded pass must use a sanitized input with all identity-bearing metadata removed and a fresh shuffle key.

Protocol annotations preserved without score changes:
1. Quality includes an L-arm applicability check; it is N/A/PASS across the batch and does not alter the evaluator scores.
2. R05/R10 contain some dimension commitments that are asserted rather than independently test-fit. Quality preserves the evaluator's PASS judgments; behavior separately captures the weaker verification evidence.
3. The behavior evaluator reconstructed a 12-item hard-requirement checklist because the brief was not attached. Its observable-behavior scores are preserved exactly as returned.

The two CSV files in this directory are exact transcriptions of this identity-exposed evaluator pass and are retained for auditability only.
