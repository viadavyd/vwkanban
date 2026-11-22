---
name: feature
description: Add a feature to VWKanban end to end (branch → plan → code → tests → docs → PR) with minimal token use. Use when the user types /feature, or asks to add, build or implement something in this repo. Argument - the feature, or a docs/backlog.md item.
---

# /feature <what>

Goal: a small, reviewed vertical slice. Spend tokens on the change, not on exploring.

## 1. Orient cheaply (no broad exploring)
1. Find the item in `docs/backlog.md` (or add it under Next). Mark it `[~]`.
2. Read the matching area(s) in `docs/map.md`. Read only the design sections it names in
   `docs/design.md`, plus the files it lists. Use `grep -n` to find a function, and read
   it with offset/limit instead of reading a whole large file (`sync/ops.py`,
   `routes/Board.svelte`, `components/CardView.svelte`, `lib/sync/store.ts` are all
   600+ lines).
3. Don't spawn subagents for exploring unless the user asks.

## 2. Plan briefly, and ask only real questions
- State in ≤10 lines: the behaviour, the keys (check `keymap.ts` for clashes and
  `Esc` one-level), the op kinds or routes, the files to touch and the tests to add.
- If the feature needs a product decision (key choice, a new dependency, a schema
  change, or a design §0 trade-off), ask with AskUserQuestion, then continue.
- Create a branch: `git switch -c feat/<short-name>` from an up-to-date `main`.

## 3. Build
- Follow the CLAUDE.md rules. New op kind = schema + apply branch + `inverseOf` +
  multi-client test. New key = `keymap.ts` entry with help, plus `HELP_SECTIONS` if it's
  a new mode. New route = `require_member` + `BOARD_ROUTES`. Schema change = a new
  additive migration.
- Test first where it's cheap (backend rules, store logic). Add one e2e spec only when
  the feature is keyboard- or UI-visible.

## 4. Verify (quiet output only)
- While you iterate: `scripts/check.sh backend -k <area>` or `scripts/check.sh frontend`.
- Once at the end: `scripts/check.sh`, then `scripts/e2e.sh <spec filter>` for touched
  specs, then the whole `scripts/e2e.sh` if keys, sync or card mode changed.
- Don't paste full logs into the conversation. The scripts already print only failures.

## 5. Docs and finish
- Behaviour changed → edit the section in `docs/design.md`, and add a line under §11 if
  it was a decision. Files moved or areas added → `docs/map.md`. Commands changed →
  `CLAUDE.md` / `docs/dev.md`.
- `docs/backlog.md`: move the item to Done (with the PR number once known).
- Commit slice by slice with the `commit` skill. Push the branch, then open a PR with
  `gh pr create` if `gh` is installed; otherwise give the user the compare URL.
- Report in ≤8 lines: what changed, the tests, and anything the user must decide or check.
