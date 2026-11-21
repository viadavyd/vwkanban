<script lang="ts">
  // Card tile per board.png / plan §4.4: title line, meta line `#12 · due 11-30 · ☐ 2/3`,
  // tag pills coloured by name, is_done checkbox on the right (done → dimmed title).
  import type { Card } from "../lib/api/boards";
  import { tagColor } from "../lib/colors";
  import type { ChildCount } from "../lib/sync/ops";

  let {
    card,
    selected,
    marked = false,
    pending = false,
    children,
    onselect,
    ontoggle,
  }: {
    card: Card;
    selected: boolean;
    marked?: boolean;
    pending?: boolean;
    children?: ChildCount;
    onselect: (id: string) => void;
    ontoggle: (id: string) => void;
  } = $props();

  const meta = $derived(
    [
      pending ? "#…" : `#${card.number}`,
      card.date ? `due ${card.date.slice(5)}` : "",
      children ? `☐ ${children.done}/${children.total}` : "",
    ]
      .filter(Boolean)
      .join(" · "),
  );
</script>

<!-- Mouse is optional (plan §4.4): click selects, the checkbox toggles. -->
<!-- svelte-ignore a11y_click_events_have_key_events (keys are handled by the dispatcher) -->
<div
  class="tile"
  class:selected
  class:done={card.is_done}
  class:pending
  class:marked
  role="option"
  aria-selected={selected}
  tabindex="-1"
  data-card={card.id}
  data-number={card.number}
  onclick={() => onselect(card.id)}
>
  <div class="body">
    <div class="title">{card.title}</div>
    <div class="meta" data-testid="card-meta">{meta}</div>
    {#if card.tags.length}
      <div class="tags">
        {#each card.tags as tag, i (i)}
          <span class="tag" style:background={tagColor(tag)}>{tag}</span>
        {/each}
      </div>
    {/if}
  </div>
  <!-- A span, not an <input>: focus must stay on the page so board keys keep working. -->
  <span
    class="check"
    role="checkbox"
    aria-checked={card.is_done}
    aria-label="done"
    tabindex="-1"
    onclick={(e) => {
      e.stopPropagation();
      onselect(card.id);
      ontoggle(card.id);
    }}
  >
    {card.is_done ? "✓" : ""}
  </span>
</div>

<style>
  .tile {
    display: flex;
    gap: 0.5rem;
    align-items: flex-start;
    background: #fff;
    border: 2px solid #222;
    padding: 0.45rem 0.55rem;
    cursor: default;
  }
  .tile.selected {
    outline: 3px solid #222;
    outline-offset: 2px;
  }
  .tile.marked {
    opacity: 0.45;
  }
  .tile.pending {
    border-style: dashed;
  }
  .body {
    flex: 1;
    min-width: 0;
  }
  .title {
    overflow-wrap: anywhere;
  }
  .done .title {
    color: #888;
    text-decoration: line-through;
  }
  .meta {
    color: #555;
    font-size: 0.85em;
    margin-top: 0.2rem;
  }
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    margin-top: 0.3rem;
  }
  .tag {
    color: #fff;
    border-radius: 999px;
    padding: 0 0.45rem;
    font-size: 0.8em;
  }
  .check {
    flex: none;
    width: 1.1rem;
    height: 1.1rem;
    border: 2px solid #222;
    display: grid;
    place-items: center;
    font-size: 0.85em;
    line-height: 1;
  }
</style>
