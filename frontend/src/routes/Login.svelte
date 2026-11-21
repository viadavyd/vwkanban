<script lang="ts">
  // Login panel per .local/drawing/login.png. Keyboard: the username field is focused,
  // Tab moves between fields, Enter submits. Signup is shown only when the server allows it.
  import { login, signup, type User } from "../lib/api/auth";
  import { ApiError } from "../lib/api/client";

  let { signupEnabled, onLoggedIn }: { signupEnabled: boolean; onLoggedIn: (u: User) => void } =
    $props();

  let mode = $state<"login" | "signup">("login");
  let username = $state("");
  let password = $state("");
  let error = $state("");
  let busy = $state(false);
  let usernameInput: HTMLInputElement | undefined = $state();

  $effect(() => {
    void mode; // refocus when switching between login and signup
    usernameInput?.focus();
  });

  async function submit(e: SubmitEvent) {
    e.preventDefault();
    if (busy) return;
    busy = true;
    error = "";
    try {
      const user =
        mode === "login" ? await login(username, password) : await signup(username, password);
      onLoggedIn(user);
    } catch (err) {
      error = err instanceof ApiError ? capitalize(err.message) : "Something went wrong";
      password = "";
    } finally {
      busy = false;
    }
  }

  function toggleMode() {
    mode = mode === "login" ? "signup" : "login";
    error = "";
  }

  const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
</script>

<main>
  <form class="panel" onsubmit={submit} novalidate>
    <p class="brand">VWKanban</p>
    <h1>{mode === "login" ? "Log in" : "Sign up"}</h1>
    <label>
      <span>Username</span>
      <input
        bind:this={usernameInput}
        bind:value={username}
        name="username"
        autocomplete="username"
        autocapitalize="none"
        spellcheck="false"
        required
      />
    </label>
    <label>
      <span>Password</span>
      <input
        bind:value={password}
        name="password"
        type="password"
        autocomplete={mode === "login" ? "current-password" : "new-password"}
        required
      />
    </label>
    <p class="error" role="alert" aria-live="assertive">{error}</p>
    <div class="actions">
      <button type="submit" disabled={busy}>{mode === "login" ? "Log in" : "Sign up"}</button>
    </div>
    {#if signupEnabled}
      <button type="button" class="link" onclick={toggleMode}>
        {mode === "login" ? "Sign up" : "Back to log in"}
      </button>
    {/if}
  </form>
</main>

<style>
  main {
    min-height: 100vh;
    display: grid;
    place-items: center;
    padding: 1rem;
    box-sizing: border-box;
  }
  .panel {
    width: min(26rem, 100%);
    border: 2px solid #222;
    padding: 2rem 2.5rem 2.5rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
    background: #fff;
  }
  .brand {
    margin: 0;
    text-align: center;
    font-size: 1.5rem;
    font-weight: bold;
  }
  h1 {
    margin: 1rem 0 0.5rem;
    font-size: 1.25rem;
  }
  label {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  label span {
    font-size: 0.8rem;
    color: #555;
  }
  input {
    font: inherit;
    padding: 0.6rem 0.7rem;
    border: 2px solid #222;
    background: #fff;
  }
  input:focus,
  button:focus-visible {
    outline: 3px solid #4a7dff;
    outline-offset: 1px;
  }
  .error {
    min-height: 1.2em;
    margin: 0;
    color: #b00020;
    font-size: 0.9rem;
  }
  .actions {
    display: flex;
    justify-content: flex-end;
  }
  button[type="submit"] {
    font: inherit;
    padding: 0.4rem 1.6rem;
    background: #222;
    color: #fff;
    border: 2px solid #222;
    cursor: pointer;
  }
  button[disabled] {
    opacity: 0.6;
  }
  .link {
    align-self: flex-end;
    font: inherit;
    font-size: 0.9rem;
    background: none;
    border: none;
    padding: 0;
    color: #224;
    text-decoration: underline;
    cursor: pointer;
  }
</style>
