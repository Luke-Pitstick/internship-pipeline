<script lang="ts">
  import { getContext } from "svelte";
  import { Api } from "#lib/api.ts";
  let { jobId }: { jobId: string } = $props();
  type Draft = {key?: string; state: string; profile_revision: number; model_revision: number;
    stage?: string; error?: string; warnings?: string[]; changes?: {selected_fact_ids: string[]; omitted_fact_ids: string[]; wording: string; selected: {id: string; text: string}[]; omitted: {id: string; text: string; status: string}[]};
    preview_url?: string; download_url?: string; pages?: number};
  const api = getContext<Api>("api");
  let draft = $state<Draft>();
  let error = $state("");
  let busy = $state(false);
  let preview = $state(false);
  const working = $derived(busy || ["pending", "running"].includes(draft?.state ?? ""));
  $effect(() => {
    const id = jobId;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    draft = undefined; error = ""; preview = false;
    async function refresh() {
      try {
        const value = await api.request<Draft>(`/api/jobs/${encodeURIComponent(id)}/resume`);
        if (stopped) return;
        draft = value;
      } catch (reason) { if (!stopped) error = (reason as Error).message; }
      if (!stopped) timer = setTimeout(refresh, 1500);
    }
    void refresh();
    return () => { stopped = true; clearTimeout(timer); };
  });
  async function generate() {
    if (!draft) return;
    const id = jobId;
    busy = true; error = ""; preview = false;
    try {
      const value = await api.request<Draft>(`/api/jobs/${encodeURIComponent(id)}/resume`, {
        expected_profile_revision: draft.profile_revision, expected_model_revision: draft.model_revision});
      if (jobId === id) draft = value;
    } catch (reason) { if (jobId === id) error = (reason as Error).message; }
    finally { busy = false; }
  }
  async function review() {
    const key = draft?.key; const id = jobId;
    if (!key) return;
    busy = true;
    try {
      const value = await api.request<Draft>(`/api/tailored-resume/${key}/review`, {});
      if (jobId === id) draft = value;
    } catch (reason) { if (jobId === id) error = (reason as Error).message; }
    finally { busy = false; }
  }
</script>
<section aria-label="Job-specific résumé" class="tailored-resume">
  <h3>Job-specific résumé</h3>
  <p>The configured general LLM selects and orders confirmed facts for this job. Saved wording, education and contact details are preserved. Review the draft before applying.</p>
  <button onclick={generate} disabled={!draft || working}>{working ? "Generating résumé…" : draft?.state === "failed" ? "Retry generation" : "Generate job-specific résumé"}</button>
  <div aria-live="polite">
    {#if error}<p role="alert">{error}</p>{/if}
    {#if draft?.error}<p role="alert">{draft.error}</p>{/if}
    {#if working}<p>{draft?.stage ?? "Queued"} — you can keep using the app.</p>{/if}
    {#if draft?.state === "draft" || draft?.state === "reviewed"}
      <p>{draft.state === "reviewed" ? "Review recorded" : "Draft awaiting your review"} · {draft.pages} pages</p>
      {#if draft.changes}
        <p>{draft.changes.wording}</p>
        <details><summary>Inspect selected and omitted facts</summary>
          <h4>Selected confirmed facts</h4><ul>{#each draft.changes.selected as fact}<li>{fact.text} <small>({fact.id})</small></li>{/each}</ul>
          <h4>Omitted facts</h4><ul>{#each draft.changes.omitted as fact}<li>{fact.text} <small>({fact.status})</small></li>{/each}</ul>
        </details>
      {/if}
      <ul>{#each draft.warnings ?? [] as warning}<li>{warning}</li>{/each}</ul>
      <div class="actions">
        <button onclick={() => preview = !preview} aria-expanded={preview}>Preview PDF</button>
        <a href={draft.download_url} download="tailored-resume.pdf">Download draft PDF</a>
        {#if draft.state === "draft"}<button onclick={review} disabled={busy}>I reviewed this draft and its omissions</button>{/if}
      </div>
      <p>Review and download do not submit an application or change its status.</p>
      {#if preview}<iframe title="Job-specific résumé PDF preview" src={draft.preview_url}></iframe>{/if}
    {/if}
  </div>
</section>
<style>
  .tailored-resume { border-top: 1px solid var(--border); margin-top: 1.5rem; padding-top: 1rem; min-width: 0; }
  p, li { line-height: 1.5; overflow-wrap: anywhere; }
  .actions { display: flex; flex-wrap: wrap; gap: .75rem; margin-top: 1rem; }
  button, a { padding: .6rem .8rem; border: 1px solid var(--border); border-radius: var(--radius); font: inherit; }
  iframe { width: 100%; height: 35rem; border: 1px solid var(--border); }
</style>
