---
name: fix
description: Fix a bug in VWKanban (reproduce with a failing test → minimal fix → verify → PR) with minimal token use. Use when the user types /fix, reports a bug, an error, a failing test or CI run, or wrong behaviour in this repo. Argument - the symptom.
---

# /fix <symptom>

Goal: the smallest correct fix, proven by a test that failed before it.

## 1. Locate cheaply
1. Map the symptom to an area in `docs/map.md`, and read only that area's files (use
   `grep -n` plus offset/limit on large files). For a CI failure, read the failing job's
   log tail, not the whole log.
2. Check `docs/design.md` for the intended behaviour. If the code matches the design and
   the user wants something else, it's a feature: say so and use `/feature`.
3. Add the bug under Bugs in `docs/backlog.md` as `[~]`.

## 2. Reproduce first
- Create a branch: `git switch -c fix/<short-name>` from an up-to-date `main`.
- Write the smallest failing test at the lowest layer that shows the bug: backend unit
  or API (`tests/api`), WS multi-client (`tests/ws`) for sync bugs, vitest for
  store/keys, and e2e only for UI-only bugs. Run just that test and confirm it fails for
  the right reason.
- If you can't reproduce the bug, stop and ask the user for steps. Don't guess-fix.

## 3. Fix
- Make the minimal change at the root cause. Don't refactor nearby code. Keep the CLAUDE.md
  rules (apply_op only, field_meta, keymap only, never lose text).
- Flaky e2e: replace timing with `settled(page)` or an explicit `expect`, never a sleep.
  Prove it with `--repeat-each=20` on that spec.

## 4. Verify and finish
- Run the new test, then `scripts/check.sh`, then `scripts/e2e.sh <spec filter>` if the
  UI was involved.
- Update `docs/design.md` only if the intended behaviour was unclear there.
- Commit with the `commit` skill (`fix(scope): ...`), push the branch and open a PR (with
  `gh`, or give the compare URL). Move the bug to Done in `docs/backlog.md`.
- Report in ≤6 lines: the cause, the fix and the test.
