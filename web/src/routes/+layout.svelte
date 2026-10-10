<script lang="ts">
  import { onMount, setContext } from 'svelte';
  import { page } from '$app/state';
  import { afterNavigate, goto } from '$app/navigation';
  import { Api, type Session } from '#lib/api.ts';
  import '../app.css';
  let { children } = $props();
  let session = $state<Session | null>(null);
  let error = $state('');
  let busy = $state(false);
  let username = $state('');
  let password = $state('');
  let setupToken = $state('');
  const api = new Api(() => { session = null; refresh(); });
  let setupPending = $state(false);
  setContext('api', api);
  function captureSetupLink() {
    const fragment = new URLSearchParams(location.hash.slice(1));
    const token = fragment.get('setup');
    if (token !== null) {
      history.replaceState(history.state, '', location.pathname + location.search);
      if (/^[A-Za-z0-9_-]{43}$/.test(token)) sessionStorage.setItem('pipeline-setup', token);
      else sessionStorage.removeItem('pipeline-setup');
    }
    if (session?.claimed) clearSetupLink();
    else setupToken = sessionStorage.getItem('pipeline-setup') ?? '';
  }
  function clearSetupLink() {
    setupToken = '';
    sessionStorage.removeItem('pipeline-setup');
  }
  async function refresh() {
    try {
      session = await api.session(); error = '';
      if (session.claimed) clearSetupLink();
      if(session.authenticated) await checkSetup();
    }
    catch { error = 'The application could not be reached. Retry when it is available.'; }
  }
  async function checkSetup() {
    try {
      const setup = await api.request<{complete:boolean;has_jobs:boolean}>('/api/onboarding');
      setupPending = !setup.complete;
      if (setupPending && !setup.has_jobs && page.url.pathname === '/') await goto('/setup/');
    } catch { /* The setup screen exposes its own retry if unavailable. */ }
  }
  onMount(() => {
    captureSetupLink(); void refresh();
    window.addEventListener('hashchange', captureSetupLink);
    return () => window.removeEventListener('hashchange', captureSetupLink);
  });
  afterNavigate(() => { captureSetupLink(); if (session?.authenticated) void checkSetup(); });
  async function submit(event: SubmitEvent) {
    event.preventDefault(); busy = true; error = '';
    try {
      session = await api.request<Session>(session?.claimed ? '/api/login' : '/api/claim', {
        username, password, ...(!session?.claimed ? { setup_token: setupToken } : {})
      });
      api.csrf = session.csrf; password = ''; clearSetupLink();
      await checkSetup();
    } catch (reason) { error = (reason as Error).message; }
    finally { busy = false; }
  }
  async function logout() {
    try { await api.request('/api/logout', {}); session = null; await refresh(); }
    catch (reason) { error = (reason as Error).message; }
  }
</script>
<svelte:head><title>Internship Pipeline</title></svelte:head>
<a class="skip-link" href="#main">Skip to content</a>
<header class="app-header">
  <a class="brand" href="/" aria-label="Internship Pipeline jobs"><span class="monogram">IP</span><span>Internship<span class="brand-second">Pipeline</span></span></a>
  {#if session?.authenticated}<nav aria-label="Main navigation">
    <a href="/" class:active={page.url.pathname === '/'} aria-current={page.url.pathname === '/' ? 'page' : undefined}>Jobs</a>
    <a href="/settings/" class:active={page.url.pathname.startsWith('/settings')} aria-current={page.url.pathname.startsWith('/settings') ? 'page' : undefined}>Settings</a>
    {#if setupPending}<a href="/setup/" class:active={page.url.pathname.startsWith('/setup')}>Continue setup</a>{/if}
    <button class="small-button" onclick={logout}>Log out</button>
  </nav>{/if}
</header>
<main id="main" tabindex="-1">
  {#if session?.authenticated}
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    {@render children()}
  {:else if session}
    <section class="auth-panel settings-panel">
      <h1>{session.claimed ? 'Welcome back.' : 'Make it yours.'}</h1>
      <p class="intro">{session.claimed ? 'Sign in to your internship workspace.' : 'Create the owner account to claim this instance. No model credentials or profile are needed yet.'}</p>
      <form onsubmit={submit}>
        <label for="username">Username</label><input id="username" bind:value={username} required maxlength="80" autocomplete="username" />
        <label for="password">Password</label><input id="password" type="password" bind:value={password} minlength={session.claimed ? 1 : 12} maxlength="256" required autocomplete={session.claimed ? 'current-password' : 'new-password'} />
        {#if !session.claimed}<p class="field-help">Use at least 12 characters. Store this password in your password manager.</p>{/if}
        {#if !session.claimed && !setupToken}<p class="field-help" role="status">Open the private setup link printed by the installer, or run <code>internship-pipeline open</code> on the host to open it automatically.</p>{/if}
        {#if error}<p class="error" role="alert">{error}</p>{/if}
        <button class="primary" type="submit" disabled={busy || (!session.claimed && !setupToken)}>{busy ? 'Please wait…' : session.claimed ? 'Sign in' : 'Create owner account'}</button>
      </form>
      {#if session.claimed}<p class="field-help">Forgot your password? The instance operator can recover the account from the local command line.</p>{/if}
    </section>
  {:else}<section class="empty-state"><h1>Opening your workspace…</h1>{#if error}<p role="alert">{error}</p><button class="primary" onclick={refresh}>Retry</button>{/if}</section>{/if}
</main>
<footer class="app-footer">Your applications stay separate from discovery, résumé downloads, and alerts.</footer>
<style>
  @media(max-width:760px) {
    .app-header {flex-wrap:wrap;gap:16px}
    .app-header nav {flex-wrap:wrap;max-width:100%}
  }
</style>
