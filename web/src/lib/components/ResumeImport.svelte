<script lang="ts">
  import { getContext, onDestroy, onMount } from 'svelte';
  import { Api, ApiError } from '#lib/api.ts';
  import type { Profile } from '#lib/settings.ts';
  import { review, type ImportDraft, type ImportPreview, type PendingImport } from '#lib/resume-import.ts';
  let { profileRevision, dirty, disabled, onfill, onpending, onreload, saveLabel = 'Save changes' } = $props<{
    profileRevision: number; dirty: boolean; disabled: boolean;
    onfill: (value: PendingImport, profile: Profile) => boolean;
    onpending: (value: boolean) => void; onreload: () => void;
    saveLabel?: string;
  }>();
  const api = getContext<Api>('api');
  let file = $state<File>();
  let fileInput = $state<HTMLInputElement>();
  let busy = $state(false);
  let useModel = $state(false);
  let feedback = $state('');
  let failure = $state(false);
  let conflict = $state(false);
  let current = $state<{format: string; approved_revision: number; lines: ImportDraft['lines']} | null>(null);
  let source = $state<ImportDraft['lines']>([]);
  let disposed = false;
  const blocked = $derived(dirty || disabled || busy || conflict);
  function chooseFile(selected?: File) {
    file = selected; failure = false; feedback = '';
    if (file && (!/\.(pdf|docx|tex)$/i.test(file.name) || !file.size || file.size > 5 * 1024 * 1024)) {
      failure = true; feedback = 'Choose a nonempty PDF, DOCX or TEX of at most 5 MiB.';
      file = undefined;
      if (fileInput) fileInput.value = '';
    }
    onpending(!!file);
  }
  function cancel() {
    if (fileInput) fileInput.value = '';
    file = undefined; feedback = ''; failure = false; onpending(false);
  }
  async function upload() {
    if (!file || blocked) return;
    const extension = file.name.split('.').pop()?.toLowerCase();
    if (!['pdf', 'docx', 'tex'].includes(extension ?? '') || !file.size || file.size > 5 * 1024 * 1024) {
      failure = true; feedback = 'Choose a nonempty PDF, DOCX or TEX of at most 5 MiB.'; return;
    }
    busy = true; failure = false; feedback = 'Uploading and reading your résumé…';
    try {
      const draft = await api.upload<ImportDraft>(`/api/resume-imports/upload?format=${extension}&expected_revision=${profileRevision}&use_model=${useModel}`, file);
      feedback = 'Filling your profile with the extracted details…';
      const selection = review(draft, [], false);
      const preview = await api.request<ImportPreview>(`/api/resume-imports/${draft.id}/preview`, selection);
      if (disposed) return;
      if (!onfill({id: draft.id, review: selection}, preview.after.profile)) {
        failure = true; feedback = 'Your profile changed during extraction. Save or discard those edits, then import again.';
        return;
      }
      source = draft.lines;
      if (fileInput) fileInput.value = '';
      file = undefined; onpending(false);
      const method = draft.method === 'native_pdf' ? 'Your PDF model read the résumé.' : draft.method === 'ai_text' ? 'Your model organized the locally extracted résumé text.' : 'Your résumé was parsed locally.';
      const counts = (['experience', 'project', 'education'] as const).map(kind => {
        const count = draft.suggestions.filter(item => item.selected && item.kind === kind).length;
        return kind === 'project' ? `${count} project${count === 1 ? '' : 's'}` : `${count} ${kind} ${count === 1 ? 'entry' : 'entries'}`;
      }).join(', ');
      feedback = `${method} Profile fields filled. Found ${counts}. Review and edit the fields below, then choose ${saveLabel}. Missing details stay blank. ${draft.warnings.join(' ')}`;
    } catch (reason) {
      failure = true; feedback = (reason as Error).message;
      conflict = reason instanceof ApiError && reason.status === 409;
    } finally { busy = false; }
  }
  onMount(() => {
    void api.request<{import: typeof current}>('/api/resume-imports/current').then(value => { current = value.import; }).catch(() => {});
  });
  onDestroy(() => { disposed = true; });
</script>

<section class="resume-import" aria-labelledby="resume-import-title" aria-busy={busy}>
  <h3 id="resume-import-title">Import your resume</h3>
  <p class="field-help">Upload a PDF, DOCX or LaTeX (.tex) file to fill your profile fields. Review and correct them before saving. A saved .tex import also becomes your template for AI tailoring.</p>
  <label class="upload-label" for="resume-document">Resume document</label>
  <input id="resume-document" aria-describedby="resume-file-help" bind:this={fileInput} type="file" accept=".tex,.pdf,.docx,application/x-tex,text/x-tex,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" disabled={blocked} onchange={event => chooseFile(event.currentTarget.files?.[0])} />
  <p class="field-help" id="resume-file-help">PDF or Word (.docx), up to 5 MiB; UTF-8 LaTeX (.tex), up to 100,000 characters. Local PDF parsing needs selectable text; a supported PDF model can also read scans.</p>
  {#if file}
    <label><input type="checkbox" bind:checked={useModel} disabled={busy} /> Use AI to organize résumé fields</label>
    <p class="field-help">Optional. Sends the PDF to your saved, tested API model when it supports native PDFs; otherwise sends the locally extracted text, including contact details and links. AI imports allow up to 8,192 output tokens, independently of résumé-generation settings, and provider charges apply. ChatGPT account connections use local parsing. Leave unchecked to keep this import entirely local.</p>
  {/if}
  {#if file}<p class="selected-file">{file.name} <span>· {Math.max(1, Math.round(file.size / 1024))} KB</span></p>{/if}
  {#if file}<button type="button" class="subtle" disabled={busy || disabled} onclick={cancel}>Discard selected résumé file</button>{/if}
  <button type="button" class="secondary" disabled={!file || blocked} onclick={upload}>{busy ? 'Filling profile…' : 'Fill profile from resume'}</button>
  {#if dirty}<p class="field-help">Save or discard your profile and filter changes before importing another resume.</p>{/if}
  {#if source.length}<details><summary>Extracted resume text</summary><div class="source-text">{#each source as line}<p><small>{line.location}</small><br />{line.text}</p>{/each}</div></details>{/if}
  {#if current}<details><summary>Last reviewed {current.format.toUpperCase()} · profile revision {current.approved_revision}</summary><div class="source-text">{#each current.lines as line}<p><small>{line.location}</small><br />{line.text}</p>{/each}</div></details>{/if}
  {#if feedback}<p role={failure ? 'alert' : 'status'} class:error={failure}>{feedback}</p>{/if}
  {#if conflict}<button type="button" class="secondary" onclick={onreload}>Reload saved profile to import again</button>{/if}
</section>
<style>
  .resume-import { border-bottom: 1px solid var(--border); padding-bottom: 24px; margin-bottom: 24px; min-width: 0; }
  h3 { margin-top: 0; }
  input[type=file] { width: 100%; max-width: 100%; box-sizing: border-box; padding: 12px; border-style: dashed; }
  input[type=file]::file-selector-button { font: inherit; font-weight: 600; color: var(--accent); background: var(--selected); border: 0; border-radius: var(--radius); padding: 10px 14px; margin-right: 12px; cursor: pointer; }
  .upload-label { display: block; font-size: 14px; font-weight: 600; margin: 16px 0 8px; }
  .selected-file { margin: 12px 0; font-size: 14px; overflow-wrap: anywhere; }
  .selected-file span { color: var(--muted); }
  .secondary { margin-top: 16px; }
  .source-text { max-height: 320px; overflow-y: auto; overflow-wrap: anywhere; padding: 8px; white-space: pre-line; }
  details { margin-top: 16px; } summary { cursor: pointer; }
  .error { color: #a83424; }
</style>
