<script lang="ts">
  // Members overlay (plan §4.3 `M`): who the board is shared with. Everyone sees the list;
  // the owner adds a user by name (`a`, a plain prompt) and removes one (`d`, confirmed).
  // Keys come from the "members" mode in keymap.ts; the prompt and confirm stack on top.
  import Confirm from "./Confirm.svelte";
  import Prompt from "./Prompt.svelte";
  import type { User } from "../lib/api/auth";
  import { addMember, listMembers, removeMember, type Member } from "../lib/api/boards";
  import { ApiError } from "../lib/api/client";
  import { pushMode } from "../lib/keys/dispatch";
  import type { Action } from "../lib/keys/keymap";

  let {
    boardId,
    user,
    onclose,
    onloggedout,
  }: { boardId: string; user: User; onclose: () => void; onloggedout: () => void } = $props();

  let members = $state<Member[]>([]);
  let loaded = $state(false);
  let sel = $state(0);
  let message = $state("");
  let sub = $state<{ kind: "add" } | { kind: "remove"; member: Member } | null>(null);

  const isOwner = $derived(members.some((m) => m.user_id === user.id && m.role === "owner"));
  const selected = $derived<Member | undefined>(members[sel]);

  function failure(e: unknown): string {
    if (e instanceof ApiError && e.status === 401) {
      onloggedout();
      return "";
    }
    return e instanceof ApiError ? e.message : "Something went wrong";
  }

  async function load() {
    try {
      members = await listMembers(boardId);
      sel = Math.min(sel, Math.max(members.length - 1, 0));
    } catch (e) {
      message = failure(e);
    }
    loaded = true;
  }

  async function add(name: string): Promise<string | void> {
    if (!name.trim()) return "enter a username";
    try {
      const m = await addMember(boardId, name.trim());
      sub = null;
      await load();
      sel = Math.max(
        members.findIndex((x) => x.user_id === m.user_id),
        0,
      );
      message = `${m.username} can now edit this board`;
    } catch (e) {
      return failure(e);
    }
  }

  async function remove(m: Member) {
    sub = null;
    try {
      await removeMember(boardId, m.user_id);
      message = `${m.username} was removed`;
    } catch (e) {
      message = failure(e);
    }
    await load();
  }

  function onkey(action: Action) {
    message = "";
    switch (action) {
      case "down":
        sel = Math.min(sel + 1, members.length - 1);
        return;
      case "up":
        sel = Math.max(sel - 1, 0);
        return;
      case "create":
        if (!isOwner) message = "only the board owner can add members";
        else sub = { kind: "add" };
        return;
      case "delete":
        if (!isOwner) message = "only the board owner can remove members";
        else if (!selected) return;
        else if (selected.role === "owner") message = "the board owner can't be removed";
        else sub = { kind: "remove", member: selected };
        return;
      case "back":
        return onclose();
    }
  }

  $effect(() => pushMode("members", (a) => onkey(a)));

  load();
</script>

<div class="backdrop">
  <div class="dialog" role="dialog" aria-modal="true" aria-label="Members">
    <h2>Members</h2>
    {#if loaded}
      <ul role="listbox" aria-label="Members">
        {#each members as m, i (m.user_id)}
          <li role="option" aria-selected={i === sel} data-member={m.username}>
            <span class="name">{m.username}</span>
            <span class="role">{m.role}{m.user_id === user.id ? " · you" : ""}</span>
          </li>
        {/each}
      </ul>
    {/if}
    <p class="message" role="status">{message}</p>
    <p class="hint">
      j/k select{#if isOwner}
        · a add · d remove{/if} · Esc close
    </p>
  </div>
</div>

{#if sub?.kind === "add"}
  <Prompt
    label="Add member (username)"
    maxlength={64}
    onsubmit={add}
    oncancel={() => (sub = null)}
  />
{:else if sub?.kind === "remove"}
  {@const m = sub.member}
  <Confirm
    message={`Remove ${m.username} from this board?`}
    onyes={() => remove(m)}
    onno={() => (sub = null)}
  />
{/if}

<style>
  .backdrop {
    position: fixed;
    inset: 0;
    background: rgb(0 0 0 / 0.25);
    display: grid;
    place-items: start center;
    padding-top: 15vh;
  }
  .dialog {
    width: min(28rem, calc(100vw - 2rem));
    background: #fff;
    border: 2px solid #222;
    padding: 1rem 1.5rem 1.25rem;
  }
  h2 {
    margin: 0 0 0.75rem;
    font-size: 1.1rem;
  }
  ul {
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    display: flex;
    justify-content: space-between;
    padding: 0.35rem 0.5rem;
    border: 2px solid transparent;
  }
  li[aria-selected="true"] {
    border-color: #222;
  }
  .role {
    color: #555;
  }
  .message {
    min-height: 1.2em;
    margin: 0.75rem 0 0;
  }
  .hint {
    margin: 0.25rem 0 0;
    color: #666;
    font-size: 0.85rem;
  }
</style>
