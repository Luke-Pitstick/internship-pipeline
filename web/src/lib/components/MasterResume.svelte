<script lang="ts">
  import { getContext, onDestroy } from 'svelte';
  import { Api } from '#lib/api.ts';
  import type { MasterResumeResult } from '#lib/master-resume.ts';
  let { profileRevision, dirty }: { profileRevision: number; dirty: boolean } = $props();
  const api = getContext<Api>('api');
  let result = $state<MasterResumeResult>();
  let error = $state('');
  let submitting = $state(false);
  let preview = $state(false);
  let alive = true;
  onDestroy(() => { alive = false; });
  const working = $derived(submitting || result?.state === 'pending' || result?.state === 'running');
  const current = $derived(result?.profile_revision === profileRevision && result?.state === 'ready');
  $effect(() => {
    const revision = profileRevision;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    result = undefined; error = ''; preview = false;
    async function refresh() {
      try {
        const data = await api.request<MasterResumeResult>('/api/master-resume');
        if (stopped) return;
        if (data.profile_revision !== revision) {
          result = undefined;
          error = 'The saved profile changed in another tab. Reload Settings before generating.';
          return;
        }
        result = data;
        if (data.state === 'pending' || data.state === 'running') timer = setTimeout(refresh, 1500);
      } catch (reason) { if (!stopped) error = (reason as Error).message; }
    }
    if (revision) void refresh();
    return () => { stopped = true; clearTimeout(timer); };
  });
  async function generate() {
    submitting = true; error = ''; preview = false;
    const revision = profileRevision;
    try {
      const data = await api.request<MasterResumeResult>('/api/master-resume', {expected_revision: revision});
      if (!alive || revision !== profileRevision) return;
      result = data;
      while (data.state !== 'ready' && result && ['pending', 'running'].includes(result.state)) {
        await new Promise(resolve => setTimeout(resolve, 1500));
        if (!alive || revision !== profileRevision) return;
        const update = await api.request<MasterResumeResult>('/api/master-resume');
        if (!alive || revision !== profileRevision) return;
        if (update.profile_revision !== revision) {
          result = undefined; error = 'The saved profile changed. Reload Settings and generate again.'; return;
        }
        result = update;
      }
    } catch (reason) { if (revision === profileRevision) error = (reason as Error).message; }
    finally { submitting = false; }
  }
</script>

<section class="master-resume" aria-labelledby="master-resume-title">
  <h3 id="master-resume-title">Master résumé</h3>
  <p>Generate a PDF from your confirmed saved facts and education using the supported two-page template. No AI connection is needed.</p>
  {#if !profileRevision}<p>Save your profile with a name and at least one confirmed fact or education entry first.</p>{/if}
  {#if dirty}<p class="notice">You have unsaved changes. Save or discard them before generating.</p>{/if}
  <button class="primary" onclick={generate} disabled={!profileRevision || dirty || working}>
    {working ? 'Generating master résumé…' : current ? 'Reuse saved master PDF' : 'Generate master résumé'}
  </button>
  <div aria-live="polite" aria-atomic="true">
    {#if error}<p class="failure" role="alert">{error}</p>
    {:else if result?.state === 'failed'}<p class="failure" role="alert">{result.error}</p>
    {:else if working}<p>Queued for the PDF worker. You can keep using the app while it compiles.</p>
    {:else if current}<p>Ready · saved profile revision {result?.profile_revision} · {result?.pages} {result?.pages === 1 ? 'page' : 'pages'}. Unknown entries were excluded ({result?.omitted_unknown ?? 0}).</p>
    {:else if result?.state === 'stale'}<p>The saved profile changed. Generate a new master résumé.</p>{/if}
  </div>
  {#if current && result?.download_url}
    <div class="actions">
      <button onclick={() => preview = !preview} aria-expanded={preview}>{preview ? 'Hide PDF preview' : 'Preview master PDF'}</button>
      <a class="download" href={result.download_url} download="master-resume.pdf">Download master PDF</a>
    </div>
    {#if preview && result.preview_url}<iframe title="Master résumé PDF preview" src={result.preview_url}></iframe>{/if}
  {/if}
</section>

<style>
  .master-resume { max-width: 52rem; }
  h3 { margin: 0 0 .75rem; }
  p { line-height: 1.6; }
  button, .download { border: 1px solid var(--border, #d8dce3); border-radius: var(--radius); padding: .7rem 1rem; font: inherit; color: inherit; background: white; cursor: pointer; }
  .primary { background: var(--accent); color: white; }
  button:disabled { opacity: .5; cursor: default; }
  .actions { display: flex; flex-wrap: wrap; gap: .75rem; margin-top: 1rem; }
  .download { text-decoration: none; }
  .failure { color: #9d2525; }
  .notice { color: #795210; }
  iframe { display: block; width: 100%; height: 40rem; border: 1px solid #d8dce3; margin-top: 1rem; border-radius: var(--radius); }
  @media (max-width: 600px) { iframe { height: 30rem; } }
</style>
