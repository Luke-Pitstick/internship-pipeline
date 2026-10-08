<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import { Api, ApiError } from '#lib/api.ts';
  import type { Snapshot } from '#lib/settings.ts';
  import { review, type ImportDraft, type ImportPreview } from '#lib/resume-import.ts';
  let { profileRevision, dirty, onsaved, onpending, onreload } = $props<{
    profileRevision: number; dirty: boolean; onsaved: (value: Snapshot) => void;
    onpending: (value: boolean) => void; onreload: () => void;
  }>();
  const api = getContext<Api>('api');
  let draft = $state<ImportDraft>();
  let preview = $state<ImportPreview>();
  let file = $state<File>();
  let fileInput = $state<HTMLInputElement>();
  let removeIds = $state<string[]>([]);
  let confirmed = $state(false);
  let busy = $state(false);
  let feedback = $state('');
  let failure = $state(false);
  let conflict = $state(false);
  let current = $state<{format: string; approved_revision: number; lines: ImportDraft['lines']} | null>(null);
  const blocked = $derived(dirty || busy || conflict);
  const selectedCount = $derived(draft?.suggestions.filter(item => item.selected).length ?? 0);
  function changed() { preview = undefined; confirmed = false; }
  function cancel() { if(fileInput)fileInput.value='';file=undefined;draft = undefined; preview = undefined; removeIds = []; confirmed = false; conflict = false; feedback = ''; failure = false; onpending(false); }
  function report(reason: unknown) { failure = true; feedback = (reason as Error).message; conflict = reason instanceof ApiError && reason.status === 409; }
  async function history() {
    try { current = (await api.request<{import: typeof current}>('/api/resume-imports/current')).import; } catch { /* Main settings load reports authentication failures. */ }
  }
  async function upload() {
    if (!file || blocked) return;
    const extension = file.name.split('.').pop()?.toLowerCase();
    if (!['pdf', 'docx'].includes(extension ?? '') || !file.size || file.size > 5 * 1024 * 1024) {
      failure = true; feedback = 'Choose a nonempty PDF or DOCX of at most 5 MiB.'; return;
    }
    busy = true; failure = false; feedback = 'Extracting readable text…';
    try {
      draft = await api.upload<ImportDraft>(`/api/resume-imports/upload?format=${extension}&expected_revision=${profileRevision}`, file);
      preview = undefined; removeIds = []; confirmed = false; onpending(true);
      feedback = 'Review the preselected source facts. Unrecognized text stays unselected; eligibility stays unchanged.';
    } catch (reason) { report(reason); } finally { busy = false; }
  }
  async function showPreview() {
    if (!draft || blocked) return;
    busy = true; failure = false;
    try { preview = await api.request<ImportPreview>(`/api/resume-imports/${draft.id}/preview`, review(draft, removeIds, false)); feedback = 'Check the resulting changes, then confirm to save a profile revision.'; }
    catch (reason) { report(reason); } finally { busy = false; }
  }
  async function save() {
    if (!draft || !preview || !confirmed || blocked) return;
    busy = true; failure = false;
    try {
      const saved = await api.request<Snapshot>(`/api/resume-imports/${draft.id}/confirm`, review(draft, removeIds, true));
      onsaved(saved); cancel(); feedback = `Resume reviewed and saved · revision ${saved.revision}.`; await history();
    } catch (reason) { report(reason); } finally { busy = false; }
  }
  onMount(() => { void history(); });
</script>

<section class="resume-import" aria-labelledby="resume-import-title">
  <h3 id="resume-import-title">Import your resume</h3>
  <p class="field-help">Upload or replace a PDF or DOCX, review its source facts, and explicitly save. Extraction happens on this instance, without a model call. The uploaded binary is discarded.</p>
  {#if !draft}
    <label class="form-group">Resume document<input aria-label="Resume document" bind:this={fileInput} type="file" accept=".pdf,.docx" disabled={blocked} onchange={event => { file = event.currentTarget.files?.[0];onpending(!!file); failure = false; feedback = ''; }} /></label>
    {#if file}<button type="button" class="subtle" onclick={cancel}>Discard selected résumé file</button>{/if}
    <button type="button" class="secondary" disabled={!file || blocked} onclick={upload}>{busy ? 'Extracting…' : current ? 'Upload replacement' : 'Upload and review'}</button>
    {#if dirty}<p class="field-help">Save or discard your profile and filter changes before importing.</p>{/if}
    {#if current}<details><summary>Last reviewed {current.format.toUpperCase()} · profile revision {current.approved_revision}</summary><div class="source-text">{#each current.lines as line}<p><small>{line.location}</small><br />{line.text}</p>{/each}</div></details>{/if}
  {:else}
    <p class="field-help">{selectedCount} source fields selected. Preselected fields are a draft, limited to available profile space. Names and delimited skills are literal excerpts; education is proposed only when a school and degree can be read together. Clear any incorrect selection. Dates, sponsorship and authorization require your manual confirmation in the profile editor.</p>
    <fieldset disabled={busy || conflict} class="import-review"><legend>Review extracted facts</legend>
      {#each draft.suggestions as selection, index}
        {@const line = draft.lines.find(value => value.id === selection.line_id)!}
        <div class="source-entry">
          <label class="select-source"><input type="checkbox" bind:checked={selection.selected} onchange={changed} aria-label={`Include source ${index + 1}`} /><span>{line.text}</span></label>
          {#each selection.source_line_ids as sourceId}<p class="extra-source">{draft.lines.find(value => value.id === sourceId)?.text}</p>{/each}
          <small>{line.location}{selection.selected ? ' · Included in draft' : ' · Needs review / excluded'}</small>
          <label class="form-group">Profile field<select aria-label={`Profile field ${index + 1}`} bind:value={selection.kind} onchange={changed}><option value="name">Name</option><option value="email">Email</option><option value="experience">Experience</option><option value="project">Project</option><option value="skill">Skill</option><option value="education">Education</option></select></label>
          {#if selection.kind === 'name' || selection.kind === 'email'}<label class="form-group">Exact source excerpt<input aria-label={`Source excerpt ${index + 1}`} bind:value={selection.value} placeholder={line.text} oninput={changed} /></label>{/if}
          {#if selection.kind === 'education'}
            <label class="form-group">Institution excerpt<input aria-label={`Institution excerpt ${index + 1}`} bind:value={selection.institution} oninput={changed} /></label>
            <label class="form-group">Degree excerpt<input aria-label={`Degree excerpt ${index + 1}`} bind:value={selection.degree} oninput={changed} /></label>
          {:else if selection.kind === 'skill'}
            <label class="form-group">Acquired skills from this line<input aria-label={`Imported skills ${index + 1}`} value={selection.skills.join(', ')} oninput={event => { selection.skills = event.currentTarget.value.split(',').map(value => value.trim()).filter(Boolean); changed(); }} /></label>
          {/if}
        </div>
      {/each}
      {#if draft.removable.length}<h4>Previously imported facts</h4><p class="field-help">Keep existing facts unless you select their removal. Manually added and edited facts are protected.</p>{#each draft.removable as item}<label class="select-source"><input type="checkbox" checked={removeIds.includes(item.id)} onchange={event => { removeIds = event.currentTarget.checked ? [...removeIds, item.id] : removeIds.filter(value => value !== item.id); changed(); }} /><span>Remove: {item.text}</span></label>{/each}{/if}
    </fieldset>
    <details><summary>Complete extracted source text</summary><div class="source-text">{#each draft.lines as line}<p><small>{line.location}</small><br />{line.text}</p>{/each}</div></details>
    <div class="import-actions"><button type="button" class="subtle" disabled={busy} onclick={cancel}>Cancel import</button><button type="button" class="secondary" disabled={blocked} onclick={showPreview}>Preview profile changes</button></div>
    {#if preview}
      <section class="import-preview" aria-labelledby="import-preview-title"><h4 id="import-preview-title">Profile change preview</h4>
        {#if preview.before.profile.name !== preview.after.profile.name}<p>Name: {preview.before.profile.name || 'Unknown'} → {preview.after.profile.name}</p>{/if}
        {#if preview.before.profile.email !== preview.after.profile.email}<p>Email: {preview.before.profile.email || 'Unknown'} → {preview.after.profile.email}</p>{/if}
        {#each preview.after.profile.facts.filter(item => !preview!.before.profile.facts.some(old => old.id === item.id)) as fact}<p>Added {fact.kind}: {fact.text}{fact.skills.length ? ` · Skills: ${fact.skills.join(', ')}` : ''}</p>{/each}
        {#each preview.after.profile.education.filter(item => !preview!.before.profile.education.some(old => old.id === item.id)) as education}<p>Added education: {education.institution} · {education.degree}</p>{/each}
        {#each [...preview.before.profile.facts, ...preview.before.profile.education].filter(item => removeIds.includes(item.id)) as removed}<p>Removed: {'text' in removed ? removed.text : `${removed.institution} · ${removed.degree}`}</p>{/each}
        <p class="field-help">{preview.after.profile.facts.length} facts and {preview.after.profile.education.length} education entries will be saved. Existing preferences and eligibility are preserved.</p>
        <label class="select-source"><input type="checkbox" bind:checked={confirmed} disabled={blocked} />I reviewed the selected claims against the source and confirm the profile changes.</label>
        <button type="button" class="primary" disabled={!confirmed || blocked} onclick={save}>{busy ? 'Saving…' : 'Confirm and save imported profile'}</button>
      </section>
    {/if}
  {/if}
  {#if feedback}<p role={failure ? 'alert' : 'status'} class:error={failure}>{feedback}</p>{/if}
  {#if conflict}<button type="button" class="secondary" onclick={() => { cancel(); onreload(); }}>Reload saved profile to import again</button>{/if}
</section>
<style>
  .resume-import { border-bottom: 1px solid var(--border); padding-bottom: 24px; margin-bottom: 24px; min-width: 0; }
  h3 { margin-top: 0; }
  input[type=file] { width: 100%; max-width: 100%; box-sizing: border-box; }
  .import-review { border: 0; padding: 0; min-width: 0; margin-top: 20px; }
  .import-review legend { font-weight: 600; }
  .source-entry, .import-preview { padding: 20px 0; border-top: 1px solid var(--border); margin: 12px 0; overflow-wrap: anywhere; }
  .select-source { display: flex; align-items: flex-start; gap: 10px; padding: 8px 0; overflow-wrap: anywhere; }
  .select-source input { flex-shrink: 0; margin-top: 3px; }
  .source-entry select, .source-entry input:not([type=checkbox]) { width: 100%; box-sizing: border-box; }
  .extra-source { margin: 0 0 8px 24px; }
  .source-text { max-height: 320px; overflow-y: auto; overflow-wrap: anywhere; padding: 8px; }
  .import-actions { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; }
  details { margin-top: 16px; } summary { cursor: pointer; }
  .error { color: #a83424; }
</style>
