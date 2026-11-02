# question-content.v1

P2-001; requirements QBK-01, QBK-02, PUB-01, SEC-01. Implementation: backend/app/question_bank/contracts.py. Seven synthetic valid examples are in QUESTION_CONTENT_EXAMPLES.json; generated JSON Schema is QUESTION_CONTENT_SCHEMA.json.

Call `validate_content(payload)` at an authorized authoring boundary. The tagged `kind` selects a single explicit content model. Extra fields are forbidden recursively. Lists become immutable tuples; nested models reject ordinary field assignments. This is application-level immutability, not protection from trusted Python code using bypass methods or from database owners. Persisted version protections follow in P2-002.

All types contain item_id, plain-text prompt and positive points. Option/criterion/item identifiers are lowercase bounded tokens; option IDs and labels are unique. Points are exact decimal strings/integers, up to 10000, two decimal places. Numeric expected/tolerance values use at most 18 total digits and six decimal places. Float/boolean decimal inputs, nonfinite values, control characters and blank content are rejected. Main text is capped at 16000 characters, labels at 1000; these are provisional engineering bounds. Incomplete editor forms will remain frontend-local until a valid saved draft can be produced; save-time contracts do not accept malformed half-authored items.

| kind | Authoring fields / rules |
| --- | --- |
| single_choice | 2–20 options; exactly one correct_option_id pointing to an option |
| multiple_select | 2–20 options; nonempty unique correct_option_ids; all_or_nothing policy |
| numeric | Exact expected value, nonnegative absolute_tolerance; optional public unit_label |
| short_answer | 1–50 accepted_answers; explicit NFKC/case/whitespace normalization; response length bound |
| essay | Manual rubric with unique criteria and total equal to points; private marker_guidance; response length bound |
| file_upload | Same manual rubric; allowed_extensions limited to pdf/txt/png/jpg/jpeg, at most five files, at most 20 MiB each; no upload service yet |
| passage_group | Plain passage plus 1–20 non-nested leaf children; unique child/group IDs; parent points equal child sum |

Use `candidate_view(item)` for candidate-rendering previews. It explicitly includes public type/id/prompt/points, visible option labels/IDs, units, response/file limits and recursively projected passage children. It excludes correct answers, tolerance, normalization, private rubrics and marker guidance. Do not return `model_dump()` or a content fingerprint to candidates. The projection does not grant access; later endpoints must authorize it. Staff may intentionally write answer material into a public prompt; human review still controls content quality.

`content_hash(item)` computes SHA-256 over an envelope containing schema_version and the complete authoring snapshot. Object keys are sorted; array order is significant; finite Decimals use canonical fixed-point strings without redundant trailing zeros (negative zero becomes zero); UTF-8 encoding of ASCII-escaped compact JSON is used. Equal decimal spelling and input-field-order variations do not change the fingerprint; scoring-key edits do. Defaults are materialized by validation before hashing. No signature, external canonical-JSON standard compliance or tamper-proof database claim is made.

The schema export documents authoring input; semantic validators add rules that JSON Schema alone cannot express. Validation errors can contain input values when inspected programmatically; do not log raw exceptions/errors or authoring payloads. Existing safe HTTP problem conversion must be used when routes are added. Pydantic sources consulted: https://docs.pydantic.dev/latest/concepts/unions/ and https://docs.pydantic.dev/latest/concepts/models/ . The implementation and tests use the existing pinned dependency version, not an upgrade to the latest documentation version.

No grading occurs here. Numeric inclusive tolerance, multi-select matching and manual rubric score decisions are later P5 acceptance cases. No media authorization, review approval, persistent version or API behavior is implied by content unit tests.
