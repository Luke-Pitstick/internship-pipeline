<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import { Api } from '#lib/api.ts';
  let { ondirty = () => {} } = $props<{ondirty?: (value: boolean) => void}>();
  interface Limits { hourly_calls: number; daily_calls: number; daily_tokens: number }
  interface State { revision: number; limits: Limits; usage: Limits; paused_jobs: number; resumes_at: number | null }
  const api = getContext<Api>('api');
  let saved = $state<State | null>(null);
  let draft = $state<Limits | null>(null);
  let busy = $state(false);
  let error = $state('');
  let message = $state('');
  const dirty = $derived(!!saved && !!draft && JSON.stringify(saved.limits) !== JSON.stringify(draft));
  $effect(() => { ondirty(dirty); });
  async function load() {
    busy = true; error = ''; message = '';
    try {
      saved = await api.request<State>('/api/scoring-limits');
      draft = {...saved.limits};
    } catch (reason) { error = (reason as Error).message; }
    finally { busy = false; }
  }
  async function save(event: SubmitEvent) {
    event.preventDefault();
    if (!saved || !draft) return;
    busy = true; error = ''; message = '';
    try {
      saved = await api.request<State>('/api/scoring-limits', {...draft, expected_revision: saved.revision});
      draft = {...saved.limits};
      message = 'Scoring limits saved. Paused jobs will resume when the new limits allow.';
    } catch (reason) { error = (reason as Error).message; }
    finally { busy = false; }
  }
  async function scoreUnscored() {
    busy = true; error = ''; message = '';
    try {
      const result = await api.request<{queued: number; already_queued: number; skipped: number}>('/api/scoring-limits/score-unscored', {});
      message = `${result.queued.toLocaleString()} jobs queued for Jev scoring. ${result.already_queued.toLocaleString()} already queued or scoring. ${result.skipped.toLocaleString()} skipped (not actionable, missing a description, or retry limit reached). Scoring runs in the background within your saved limits.`;
    } catch (reason) { error = (reason as Error).message; }
    finally { busy = false; }
  }
  onMount(load);
</script>

<section class="scoring-limits" aria-labelledby="scoring-limits-title">
  <h3 id="scoring-limits-title">Scoring limits</h3>
  <p>Control Jev scoring for new and already collected jobs. Limits use rolling one-hour and 24-hour windows across all jobs.</p>
  <p>Score previously collected, unscored internships using your saved profile and tested Jev connection. Closed jobs, applied jobs, and jobs without descriptions are skipped. This uses your Jev API allowance and may incur provider charges.</p>
  <button class="secondary" type="button" disabled={busy} onclick={scoreUnscored}>Score all unscored jobs with Jev</button>
  <p class="field-help">Tokens include input and output. Calls with unknown usage keep a conservative token reservation. These limits control usage, not a dollar spending cap.</p>
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if message}<p role="status">{message}</p>{/if}
  {#if saved && draft}
    <p class="field-help">Used in the last hour: {saved.usage.hourly_calls.toLocaleString()} calls. Last 24 hours: {saved.usage.daily_calls.toLocaleString()} calls and {saved.usage.daily_tokens.toLocaleString()} used or reserved tokens.</p>
    {#if saved.paused_jobs}
      <p role="status">{saved.paused_jobs.toLocaleString()} jobs are waiting for the scoring budget.{#if saved.resumes_at} Next retry: {new Date(saved.resumes_at * 1000).toLocaleString()}.{/if} Raise the limits to let queued work resume sooner.</p>
    {/if}
    <form onsubmit={save}>
      <fieldset disabled={busy}>
        <div class="limit-fields">
          <label>Scoring calls per hour<input type="number" required min="1" max="1000000" step="1" bind:value={draft.hourly_calls} /></label>
          <label>Scoring calls per day<input type="number" required min="1" max="1000000" step="1" bind:value={draft.daily_calls} /></label>
          <label>Scoring tokens per day<input type="number" required min="1" max="1000000000000" step="1" bind:value={draft.daily_tokens} /></label>
        </div>
        <div class="limit-actions">
          <button class="primary" type="submit" disabled={!dirty}>{busy ? 'Saving…' : 'Save scoring limits'}</button>
          <button class="secondary" type="button" disabled={!dirty} onclick={() => {if (saved) draft = {...saved.limits};}}>Discard scoring changes</button>
        </div>
      </fieldset>
    </form>
  {:else if !error}<p role="status">Loading scoring limits…</p>{/if}
  <button class="subtle reload" type="button" disabled={busy} onclick={() => {if (!dirty || confirm('Discard unsaved scoring limits and reload?')) void load();}}>Reload scoring limits</button>
</section>

<style>
  .scoring-limits {border-top:1px solid var(--border); margin-top:1.5rem; padding-top:1.5rem;}
  h3 {font-size:1.15rem; margin:0;}
  p {line-height:1.6;}
  fieldset {border:0; padding:0; margin:0; min-width:0;}
  .limit-fields {display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr)); gap:1rem;}
  label {display:grid; gap:.5rem; font-size:.85rem; font-weight:600;}
  input {width:100%; min-width:0; box-sizing:border-box;}
  .limit-actions {display:flex; flex-wrap:wrap; gap:.6rem; margin-top:1rem;}
  .reload {margin-top:1rem;}
</style>
