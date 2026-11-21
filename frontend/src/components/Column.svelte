<script lang="ts">
  // A board column per board.png: header boxed in the status colour (name + count), then
  // the cards. `draftAt` is where the new-card placeholder (`newCard`) sits (a/A), if any.
  import type { Snippet } from "svelte";
  import type { Card, Status } from "../lib/api/boards";
  import { colorOf } from "../lib/colors";
  import type { ChildCount } from "../lib/sync/ops";
  import CardTile from "./CardTile.svelte";

  let {
    status,
    cards,
    current,
    selectedId,
    markedId = null,
    children,
    pending,
    draftAt = null,
    newCard,
    onselect,
    ontoggle,
  }: {
    status: Status;
    cards: Card[];
    /** this column holds the selection */
    current: boolean;
    selectedId: string | null;
    /** the card marked with x (dimmed until it is moved) */
    markedId?: string | null;
    children: Map<string, ChildCount>;
    pending: Set<string>;
    draftAt?: number | null;
    newCard?: Snippet;
    onselect: (id: string) => void;
    ontoggle: (id: string) => void;
  } = $props();
</script>

<section
  class="column"
  class:current
  aria-label={status.name}
  data-column={status.id}
  data-testid="column"
>
  <header style:border-color={colorOf(status.color)}>
    <span class="name">{status.name}</span>
    <span class="count" data-testid="column-count">{cards.length}</span>
  </header>
  <div class="cards" role="listbox" aria-label={`${status.name} cards`}>
    {#each cards as card, i (card.id)}
      {#if draftAt === i}{@render newCard?.()}{/if}
      <CardTile
        {card}
        selected={card.id === selectedId}
        marked={card.id === markedId}
        pending={pending.has(card.id)}
        children={children.get(card.id)}
        {onselect}
        {ontoggle}
      />
    {/each}
    {#if draftAt !== null && draftAt >= cards.length}{@render newCard?.()}{/if}
  </div>
</section>

<style>
  .column {
    flex: none;
    width: 17rem;
    display: flex;
    flex-direction: column;
    border: 3px solid #222;
    background: #fff;
    max-height: 100%;
    min-height: 0;
  }
  .column.current {
    box-shadow: 0 0 0 3px #222;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.5rem;
    margin: 0.3rem;
    padding: 0.35rem 0.5rem;
    border: 4px solid;
    font-weight: bold;
    font-size: 1.1em;
  }
  .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .count {
    font-weight: normal;
    color: #555;
  }
  .cards {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 0.4rem 0.55rem 0.8rem;
    overflow-y: auto;
    min-height: 3rem;
  }
</style>
