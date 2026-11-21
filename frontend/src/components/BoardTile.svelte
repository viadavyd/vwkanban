<script lang="ts">
  import type { BoardItem } from "../lib/api/boards";
  import { timeAgo } from "../lib/time";

  let {
    board,
    selected,
    now,
    onselect,
    onopen,
  }: {
    board: BoardItem;
    selected: boolean;
    now: number;
    onselect: () => void;
    onopen: () => void;
  } = $props();

  const s = $derived(board.summary);
  const columns = $derived(s.by_status.map((c) => `${c.name} ${c.count}`).join(" · "));
</script>

<!-- Mouse is optional (plan §4.4): click selects, double-click opens. -->
<!-- svelte-ignore a11y_click_events_have_key_events (keys are handled by the dispatcher) -->
<div
  class="tile"
  class:selected
  role="option"
  aria-selected={selected}
  tabindex="-1"
  data-tile={board.id}
  onclick={onselect}
  ondblclick={onopen}
>
  <h2>{board.title}</h2>
  <p>{s.total} {s.total === 1 ? "card" : "cards"} · {s.done} done</p>
  <p class="columns" title={columns}>{columns || "no columns"}</p>
  <p class="muted">updated {timeAgo(board.updated_at, now)}</p>
</div>

<style>
  .tile {
    border: 2px solid #222;
    padding: 1rem 1.25rem 1.25rem;
    background: #fff;
    min-width: 0;
    cursor: default;
    outline: none;
  }
  .tile.selected {
    border-width: 4px;
    padding: calc(1rem - 2px) calc(1.25rem - 2px) calc(1.25rem - 2px);
  }
  h2 {
    margin: 0 0 1rem;
    font-size: 1.3rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  p {
    margin: 0.3rem 0 0;
  }
  .columns {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .muted {
    color: #666;
  }
</style>
