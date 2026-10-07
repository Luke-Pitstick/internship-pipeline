<script lang="ts">
  import { getContext, onMount, tick } from 'svelte';
  import { beforeNavigate } from '$app/navigation';
  import { page } from '$app/state';
  import { Api, ApiError } from '#lib/api.ts';
  import { categories, validateSettings, type Category, type Snapshot, type FieldErrors } from '#lib/settings.ts';
  import ProfileSettings from '#lib/components/ProfileSettings.svelte';
  import JobFilterSettings from '#lib/components/JobFilterSettings.svelte';
  import AiModelSettings from '#lib/components/AiModelSettings.svelte';
  import ResumeImport from '#lib/components/ResumeImport.svelte';
  import Diagnostics from '#lib/components/Diagnostics.svelte';
  import SheetsSettings from '#lib/components/SheetsSettings.svelte';
  import EmailSettings from '#lib/components/EmailSettings.svelte';
  import SourceSettings from '#lib/components/SourceSettings.svelte';
  import GenerationPolicySettings from '#lib/components/GenerationPolicySettings.svelte';
  import MasterResume from '#lib/components/MasterResume.svelte';
  const api = getContext<Api>('api');
  let { initialCategory = 'Profile', guided = false, ondirty = () => {} } = $props<{initialCategory?: Category; guided?: boolean; ondirty?: (value: boolean) => void}>();
  let category = $state<Category>('Profile');
  let heading = $state<HTMLHeadingElement>();
  let saved = $state<Snapshot>();
  let draft = $state<Snapshot>();
  let errors = $state<FieldErrors>({});
  let saving = $state(false);
  let feedback = $state('Loading saved settings…');
  let failure = $state(false);
  let conflict = $state(false);
  let workerMessage = $state('');
  let importPending = $state(false);
  const dirty = $derived(!!draft && !!saved && JSON.stringify(draft) !== JSON.stringify(saved));
  $effect(() => { ondirty(dirty || importPending); });
  $effect(() => {
    if (!guided) {
      const chosen = decodeURIComponent(page.url.hash.slice(1));
      if (categories.includes(chosen as Category)) category = chosen as Category;
    }
  });
  async function navigate(value: Category) {
    if (importPending && !confirm('Discard the unconfirmed résumé import and change category?')) return;
    importPending = false; category = value; await tick(); heading?.focus();
  }
  async function load() {
    try {
      const data = await api.request<Snapshot>('/api/profile-settings');
      saved = data; draft = structuredClone(data); errors = {}; failure = false; conflict = false;
      feedback = data.revision ? `Saved · revision ${data.revision}` : 'No profile or filters saved yet. Unknown fields are welcome.';
    } catch (reason) { feedback = (reason as Error).message; failure = true; }
  }
  async function focusError() {
    const path = Object.keys(errors)[0];
    category = path?.startsWith('preferences') ? 'Job Filters' : 'Profile';
    await tick();
    const field = path ? document.getElementById(path) : null;
    (field ?? heading)?.focus();
  }
  async function save() {
    if (!draft || saving || conflict) return;
    errors = validateSettings(draft); failure = false;
    if (Object.keys(errors).length) { feedback = 'Check the highlighted fields before saving.'; failure = true; await focusError(); return; }
    saving = true;
    try {
      const data = await api.request<Snapshot>('/api/profile-settings', {expected_revision: saved?.revision ?? 0, profile: draft.profile, preferences: draft.preferences});
      saved = data; draft = structuredClone(data); feedback = `Saved · revision ${data.revision}. Workers use this revision at their next task boundary.`;
    } catch (reason) {
      feedback = (reason as Error).message; failure = true;
      if (reason instanceof ApiError) {
        conflict = reason.status === 409;
        errors = Object.fromEntries(reason.fields.map(error => [error.field, error.message]));
        if (Object.keys(errors).length) await focusError();
      }
    } finally { saving = false; }
  }
  beforeNavigate(({cancel}) => { if ((dirty || importPending) && !confirm('You have unsaved profile, filter or import changes. Leave without saving?')) cancel(); });
  onMount(() => {
    if (guided) category = initialCategory;
    void load();
    void api.request<{worker_roles: string[]}>('/api/status').then(status => {
      workerMessage = status.worker_roles.length ? `Active worker roles: ${status.worker_roles.join(', ')}.` : 'Setup mode is healthy. Collection starts when a source is configured; evaluation and generation are not active yet.';
    }).catch(() => {});
    const warn = (event: BeforeUnloadEvent) => { if (dirty || importPending) event.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  });
</script>
{#if !guided}<section class="settings-heading"><p class="eyebrow">YOUR WORKSPACE</p><h1>Settings</h1><p class="intro">Your facts, preferences and connections, in one place.</p></section>{/if}
<div class="settings-layout">
  {#if !guided}<nav class="settings-nav" aria-label="Settings categories">{#each categories as value}<button class:chosen={category === value} aria-current={category === value ? 'true' : undefined} onclick={() => navigate(value)}>{value}</button>{/each}</nav>{/if}
  <section class="settings-panel">
    <div class="settings-panel-header"><h2 bind:this={heading} tabindex="-1">{category}</h2>{#if category === 'Profile' || category === 'Job Filters'}<span class="saved-label">{dirty ? 'Unsaved profile / filters' : saved?.revision ? `Active revision ${saved.revision}` : 'Not saved yet'}</span>{/if}</div>
    {#if draft}
      {#if category === 'Profile'}<ResumeImport profileRevision={saved?.revision ?? 0} {dirty} onpending={value => { importPending = value; }} onreload={() => { void load(); }} onsaved={data => { saved = data; draft = structuredClone(data); errors = {}; failure = false; conflict = false; feedback = `Saved · revision ${data.revision}`; }} />{/if}
      <form onsubmit={event => {event.preventDefault(); void save();}} novalidate>
        <fieldset class="settings-fields" disabled={saving || importPending}>
          {#if category === 'Profile'}<ProfileSettings bind:profile={draft.profile} {errors} />
          {:else if category === 'Job Filters'}<JobFilterSettings bind:preferences={draft.preferences} {errors} />{/if}
        </fieldset>
        {#if category === 'Profile' || category === 'Job Filters'}
          {#if Object.keys(errors).length}<div class="validation-summary" role="alert"><p>Please check these fields:</p><ul>{#each Object.entries(errors) as [field, message]}<li>{field}: {message}</li>{/each}</ul></div>{/if}
          <div class="settings-save"><p class:error={failure} role={failure ? 'alert' : 'status'}>{dirty && !failure && !saving ? 'Unsaved changes. Save applies your profile and filters together.' : feedback}</p><div>
            <button type="button" class="subtle" disabled={saving || !dirty} onclick={() => {if (saved) {draft = structuredClone($state.snapshot(saved)); errors = {}; failure = false; feedback = `Saved · revision ${saved.revision}`;}}}>Discard changes</button>
            <button class="primary" type="submit" disabled={saving || (!dirty && !!saved?.revision) || conflict || importPending}>{saving ? 'Saving…' : 'Save changes'}</button>
          </div></div>
          {#if conflict}<button type="button" class="secondary" onclick={() => {if (confirm('Reload saved settings and discard your unsaved draft?')) void load();}}>Reload saved settings</button>{/if}
          <p class="field-help">{saved?.saved_at ? `Last saved ${new Date(saved.saved_at).toLocaleString()}. ` : ''}{workerMessage}</p>
        {/if}
      </form>
      {#if category === 'Diagnostics'}<Diagnostics />{/if}
      {#if category === 'Sources'}<SourceSettings allowRun={!guided} />{/if}
      {#if category === 'AI Models'}<AiModelSettings />{/if}
      {#if category === 'Resume Generation'}<MasterResume profileRevision={saved?.revision ?? 0} dirty={dirty || importPending} /><GenerationPolicySettings />{/if}
      {#if category === 'Notifications & Integrations'}<EmailSettings /><SheetsSettings />{/if}
    {:else}<p role={failure ? 'alert' : 'status'}>{feedback}</p>{#if failure}<button class="secondary" onclick={load}>Retry loading settings</button>{/if}{/if}
  </section>
</div>
<style>
  .settings-layout:has(> .settings-panel:only-child) { grid-template-columns: minmax(0, 1fr); }
  .settings-fields { border: 0; padding: 0; margin: 0; min-width: 0; }
  .validation-summary { color: #a83424; overflow-wrap: anywhere; }
  :global(.fact-entry) { border: 0; border-top: 1px solid var(--border); padding: 20px 0; margin: 24px 0; min-width: 0; }
  :global(.fact-entry legend) { font-weight: 600; padding: 0 12px 0 0; }
  :global(.fact-id) { overflow-wrap: anywhere; font-size: 11px; }
  :global(.field-error) { color: #a83424; font-size: 13px; margin: 6px 0; }
  :global([aria-invalid=true]) { border-color: #a83424; }
  :global(.role-options) { border: 0; margin: 16px 0; padding: 0; }
  :global(.role-options .toggle-label) { display: flex; gap: 10px; padding: 8px 0; }
  :global(.form-group select) { max-width: 100%; width: 100%; margin-top: 7px; }
</style>
