<script lang="ts">
  // Tiny history router: /login, / (dashboard) and /b/:id (board; a stub until M3a).
  import { getAuthConfig, me, type User } from "./lib/api/auth";
  import { installKeys } from "./lib/keys/dispatch";
  import BoardStub from "./routes/BoardStub.svelte";
  import Dashboard from "./routes/Dashboard.svelte";
  import Login from "./routes/Login.svelte";

  const BOARD_PATH = /^\/b\/([0-9a-f-]{36})$/i;

  let path = $state(location.pathname);
  let user = $state<User | null>(null);
  let signupEnabled = $state(false);
  let ready = $state(false);
  let bootError = $state("");
  // The board we came back from, so the dashboard keeps it selected.
  let lastBoardId = $state<string | undefined>();

  const boardId = $derived(BOARD_PATH.exec(path)?.[1]);

  function navigate(to: string, replace = false) {
    if (location.pathname !== to) history[replace ? "replaceState" : "pushState"](null, "", to);
    path = to;
  }

  function route() {
    if (!user) navigate("/login", true);
    else if (path !== "/" && !BOARD_PATH.test(path)) navigate("/", true);
  }

  async function boot() {
    try {
      const [current, config] = await Promise.all([me(), getAuthConfig()]);
      user = current;
      signupEnabled = config.signup_enabled;
      route();
    } catch {
      bootError = "Cannot reach the server.";
    }
    ready = true;
  }

  function onLoggedIn(u: User) {
    user = u;
    navigate("/");
  }

  function onLoggedOut() {
    user = null;
    lastBoardId = undefined;
    navigate("/login");
  }

  function openBoard(id: string) {
    lastBoardId = id;
    navigate(`/b/${id}`);
  }

  function backToDashboard() {
    lastBoardId = boardId ?? lastBoardId;
    navigate("/");
  }

  $effect(() => installKeys());

  $effect(() => {
    const onPop = () => {
      path = location.pathname;
      route();
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  });

  boot();
</script>

{#if !ready}
  <!-- booting -->
{:else if bootError}
  <p class="boot-error" role="alert">{bootError}</p>
{:else if !user || path === "/login"}
  <Login {signupEnabled} {onLoggedIn} />
{:else if boardId}
  {#key boardId}
    <BoardStub id={boardId} {user} onback={backToDashboard} onloggedout={onLoggedOut} />
  {/key}
{:else}
  <Dashboard {user} initialSelected={lastBoardId} onopen={openBoard} onloggedout={onLoggedOut} />
{/if}

<style>
  :global(body) {
    margin: 0;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    background: #fafafa;
    color: #222;
  }
  .boot-error {
    padding: 1rem;
    color: #b00020;
  }
</style>
