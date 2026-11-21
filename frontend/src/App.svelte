<script lang="ts">
  // Tiny history router: /login and / (boards and /b/:id arrive in M2/M3).
  import { getAuthConfig, me, type User } from "./lib/api/auth";
  import Login from "./routes/Login.svelte";

  let path = $state(location.pathname);
  let user = $state<User | null>(null);
  let signupEnabled = $state(false);
  let ready = $state(false);
  let bootError = $state("");

  function navigate(to: string, replace = false) {
    if (location.pathname !== to) history[replace ? "replaceState" : "pushState"](null, "", to);
    path = to;
  }

  function route() {
    if (!user) navigate("/login", true);
    else if (path !== "/") navigate("/", true);
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
{:else}
  <header>
    <strong>VWKanban</strong>
    <span class="mode">-- DASHBOARD --</span>
    <span data-testid="username">{user.username}</span>
  </header>
  <main>
    <p>Logged in. Boards arrive in M2.</p>
  </main>
{/if}

<style>
  :global(body) {
    margin: 0;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    background: #fafafa;
    color: #222;
  }
  header {
    display: flex;
    gap: 2rem;
    align-items: center;
    padding: 0.75rem 1rem;
    border-bottom: 2px solid #222;
  }
  .mode {
    flex: 1;
    text-align: center;
  }
  main {
    padding: 1rem;
  }
  .boot-error {
    padding: 1rem;
    color: #b00020;
  }
</style>
