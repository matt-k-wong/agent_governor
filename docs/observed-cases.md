# Observed interventions and corrections

These cases were checked against the local Agent Governor ledger from September 2026. The ledger records proposed actions and verdicts. It does not prove that a blocked action was attempted, obeyed, or fixed. We include a correction only where a follow-up action or current code supports it.

## A false collision in Agent Governor was fixed

In an evaluation of a card-game test fixture, the governor returned `BLOCK_COLLISION` when an agent proposed writing a corrected function back to an **existing ordinary test file**. That was a false positive: collision protection was intended for new numbered plans, specs, and migrations. The ledger shows the block recurring, followed by an `ALLOW` when the action was phrased as editing the same file (September 17, `BLOCK_COLLISION` and subsequent `ALLOW` entries).

The current `check_unprobed_state` limits that collision rule to numbered artifacts. `test_writing_existing_ordinary_file_allows` and `test_creating_existing_numbered_plan_blocks` guard both sides of the distinction. This is a verified correction in Agent Governor itself, and a reminder that its verdicts need regression tests.

## Test weakening was rejected in a focused evaluation

For a card-game project, the ledger shows `BLOCK_REPO_INVARIANT_VIOLATION` when proposed actions would delete a failing test, skip related tests, or replace an exact category-count assertion with the much weaker `counts[name] >= 0`. The same evaluation allowed the focused fixture correction: remove the dealt hand from the remaining deck. The local project working tree subsequently contained that correction and retained its exact count assertion.

This is evidence of the governor distinguishing a legitimate repair from test weakening in that evaluation. The ledger does not prove that it caused the file change or that the change was committed. We therefore describe it as an evaluated intervention, not a production incident prevented.

## What the ledger cannot establish

Several `audit-diff` entries blocked broad diffs during concurrent or read-only work. Later `ALLOW` entries sometimes used a broader goal or reported a clean tree. Those pairs do not establish that unrelated edits were removed. We do not present them as fixed scope creep.

To make future case studies auditable, record the repository, diff or commit identifier, and a follow-up outcome alongside each intervention. Until then, pair ledger entries with independent code and test evidence before claiming a fix.
