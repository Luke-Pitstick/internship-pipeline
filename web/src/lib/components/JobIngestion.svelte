<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import { Api } from '#lib/api.ts';

  type Status = { stopped: boolean; sources: number; enabled_sources: number; active_runs: number; next_run: number | null };
  const api = getContext<Api>('api');
  let status = $state<Status>();
  let busy = $state<'start' | 'stop' | null>(null);
  let error = $state('');
  let connectionError = $state('');
  let message = $state('');
  let connected = $state(false);
  let request = 0;

  async function load() {
    const current = ++request;
    try {
      const result = await api.request<Status>('/api/job-ingestion');
      if (current !== request) return;
      status = result;
      connected = true;
      connectionError = '';
    } catch (e) {
      if (current !== request) return;
      connected = false;
      connectionError = `Couldn’t refresh ingestion status. ${(e as Error).message}`;
    }
  }

  async function control(action: 'start' | 'stop') {
    busy = action;
    ++request;
    error = '';
    message = '';
    try {
      status = await api.request<Status>(`/api/job-ingestion/${action}`, {});
      connected = true;
      connectionError = '';
      message = action === 'start'
        ? 'Ingestion started. Enabled sources are queued and schedules are active.'
        : 'Ingestion stopped. Active collection is cancelled and schedules are paused.';
    } catch (e) {
      connected = false;
      error = (e as Error).message;
    } finally {
      busy = null;
    }
  }

  onMount(() => {
    void load();
    const refresh = () => { if (!document.hidden && !busy) void load(); };
    const timer = setInterval(refresh, 3000);
    window.addEventListener('online', refresh);
    document.addEventListener('visibilitychange', refresh);
    return () => {
      ++request;
      clearInterval(timer);
      window.removeEventListener('online', refresh);
      document.removeEventListener('visibilitychange', refresh);
    };
  });
</script>

<section class="ingestion" aria-labelledby="ingestion-heading" aria-busy={busy !== null}>
  <h3 id="ingestion-heading">Job ingestion</h3>
  <p role="status">
    {#if !status}Loading ingestion status…
    {:else if !connected}Ingestion status unavailable
    {:else if status.stopped}Stopped — automatic searches are paused
    {:else if status.active_runs}Collecting jobs — {status.active_runs} active {status.active_runs === 1 ? 'run' : 'runs'}
    {:else if !status.sources}Add a source below to start collecting jobs
    {:else if !status.enabled_sources}All sources are individually paused — resume a source below
    {:else}Ready — {status.enabled_sources} enabled {status.enabled_sources === 1 ? 'source' : 'sources'}{/if}
  </p>
  {#if status?.next_run && connected}
    <p class="field-help">Next scheduled search: {new Date(status.next_run * 1000).toLocaleString()}</p>
  {/if}
  <div class="actions">
    <button type="button" class="primary" disabled={!!busy || !connected || !status?.enabled_sources || !!status?.active_runs} onclick={() => control('start')}>
      {busy === 'start' ? 'Starting…' : 'Start ingestion'}
    </button>
    <button type="button" class="secondary" disabled={!!busy || !status || !!status.stopped} onclick={() => control('stop')}>
      {busy === 'stop' ? 'Stopping…' : 'Stop ingestion'}
    </button>
  </div>
  <p class="field-help">Start runs every enabled source now and resumes its schedule. Stop cancels queued and active collection and keeps ingestion stopped across restarts. Individually paused sources stay paused.</p>
  <p class="field-help">Saved jobs stay available, and scoring and résumé work for saved jobs continue. A source request already in progress may finish, but its results won’t be saved after Stop.</p>
  {#if message}<p role="status">{message}</p>{/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if connectionError}<p class="error" role="alert">{connectionError}</p>{/if}
  {#if error || connectionError}<button type="button" class="secondary" disabled={!!busy} onclick={load}>Refresh ingestion status</button>{/if}
</section>

<style>
  .ingestion { padding-bottom: 24px; margin-bottom: 24px; border-bottom: 1px solid var(--border); }
  h3 { margin: 0 0 8px; }
  p { margin: 8px 0; overflow-wrap: anywhere; }
  .actions { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }
  .actions button { min-height: 44px; }
  @media (max-width: 600px) { .actions button { flex: 1; } }
</style>
