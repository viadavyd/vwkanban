# Backlog

One line per item: `- [ ] <title> — <one-line why or scope>`. When you take an item,
change its box to `[~]`. When the PR is merged, move it to Done with the PR number.
Bugs go under Bugs. `/feature` and `/fix` read and update this file.

## Bugs
(none known)

## Next (small, high value)
- [ ] Redo `Ctrl+r` — the counterpart of `u`; needs a redo stack in `BoardStore` cleared on new ops
- [ ] Paste above `P` — like `p` with `before_id`
- [ ] Vim counts and jumps on the board: `3j`, `gg`, `G`
- [ ] Search `/` and filters (tag, done) on the board
- [ ] Child reorder in card mode — a `card.move` with `parent_id` (keys to decide)
- [ ] Activity / history UI — the data is already in `board_events`

## Later (bigger or needs a design decision first)
- [ ] OAuth login — schema ready: nullable `password_hash`, `user_identities` table to add
- [ ] Viewer (read-only) role
- [ ] System-clipboard register `"+`
- [ ] 3-way text merge / CRDT for descriptions
- [ ] Multi-worker fan-out via `LISTEN/NOTIFY`
- [ ] Nesting deeper than 1
- [ ] Tag table with custom colours
- [ ] Shared cursors (who has which card selected)
- [ ] CSV replace mode
- [ ] Purge job for old soft-deleted cards
- [ ] Automatic TLS service in compose
- [ ] Bundle- and image-size CI gates; automated fresh-VPS CI job
- [ ] Persistent offline queue
- [ ] Mobile layout · i18n

## Done
- MVP M0–M7 (PRs #1–#11), 2026-11-22
