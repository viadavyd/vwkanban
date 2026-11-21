<script lang="ts">
  // Top bar (plan §4.4). On a board it also shows who else is on it (initials) and the
  // connection dot: ● live / ◌ reconnecting / ○ offline. `data-state` and `data-pending`
  // (unanswered ops) let tests wait for the board to settle.
  import type { PresenceUser, SyncStatus } from "../lib/sync/socket";

  let {
    title,
    mode,
    pending = "",
    username,
    others,
    sync,
  }: {
    title?: string;
    mode: string;
    pending?: string;
    username: string;
    /** Other users with the board open (a board only). */
    others?: PresenceUser[];
    /** Connection status and unanswered op count (a board only). */
    sync?: { status: SyncStatus; pending: number };
  } = $props();

  const DOT: Record<SyncStatus, [string, string]> = {
    live: ["●", "live"],
    connecting: ["◌", "connecting"],
    reconnecting: ["◌", "reconnecting"],
    offline: ["○", "offline"],
  };
</script>

<header>
  <span class="brand">
    <strong>VWKanban</strong>{#if title}<span class="title" data-testid="board-title">
        / {title}
      </span>{/if}
  </span>
  <span class="mode">
    <span data-testid="mode">-- {mode.toUpperCase()} --</span>{#if pending}<span
        class="pending"
        data-testid="pending"
      >
        {pending}
      </span>{/if}
  </span>
  {#if others}
    <ul class="presence" data-testid="presence" aria-label="Also on this board">
      {#each others as u (u.user_id)}
        <li title={u.username} aria-label={u.username}>{u.username[0].toUpperCase()}</li>
      {/each}
    </ul>
  {/if}
  {#if sync}
    <span
      class="sync {sync.status}"
      data-testid="sync"
      data-state={sync.status}
      data-pending={sync.pending}
      title={sync.pending ? `${sync.pending} change(s) not saved yet` : ""}
    >
      {DOT[sync.status][0]}
      {DOT[sync.status][1]}
    </span>
  {/if}
  <span class="hint"><kbd>?</kbd> help</span>
  <span data-testid="username">{username}</span>
</header>

<style>
  header {
    display: flex;
    gap: 2rem;
    align-items: center;
    padding: 0.75rem 1rem;
    border-bottom: 2px solid #222;
    background: #fff;
  }
  .brand {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .mode {
    flex: 1;
    text-align: center;
    white-space: nowrap;
  }
  .pending {
    margin-left: 1rem;
    font-weight: bold;
  }
  .presence {
    display: flex;
    gap: 0.3rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .presence li {
    width: 1.6rem;
    height: 1.6rem;
    line-height: 1.6rem;
    text-align: center;
    border: 2px solid #222;
    border-radius: 50%;
    font-weight: bold;
  }
  .sync {
    white-space: nowrap;
  }
  .sync.live {
    color: #1b7a2e;
  }
  .sync.reconnecting,
  .sync.connecting {
    color: #a66400;
  }
  .sync.offline {
    color: #b00020;
  }
  .hint {
    color: #555;
    white-space: nowrap;
  }
  kbd {
    font: inherit;
    border: 1px solid #888;
    padding: 0 0.3rem;
  }
</style>
