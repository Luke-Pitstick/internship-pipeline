<script lang="ts">
  import { getContext, onMount, tick } from 'svelte';
  import { afterNavigate, beforeNavigate, goto } from '$app/navigation';
  import { page } from '$app/state';
  import { Api, ApiError } from '#lib/api.ts';
  import { categories, validateSettings, type Category, type Snapshot, type FieldErrors } from '#lib/settings.ts';
  import ProfileSettings from '#lib/components/ProfileSettings.svelte';
  import JobFilterSettings from '#lib/components/JobFilterSettings.svelte';
  import AiModelSettings from '#lib/components/AiModelSettings.svelte';
  import ResumeImport from '#lib/components/ResumeImport.svelte';
  import type { PendingImport } from '#lib/resume-import.ts';
  import Diagnostics from '#lib/components/Diagnostics.svelte';
  import SheetsSettings from '#lib/components/SheetsSettings.svelte';
  import EmailSettings from '#lib/components/EmailSettings.svelte';
  import SourceSettings from '#lib/components/SourceSettings.svelte';
  import GenerationPolicySettings from '#lib/components/GenerationPolicySettings.svelte';
  import MasterResume from '#lib/components/MasterResume.svelte';
  const api = getContext<Api>('api');
  let { initialCategory = 'Profile', guided = false, showModels = true, showEmail = true, showSheets = true, ondirty = () => {}, onready = () => {}, oncontinue = () => {} } = $props<{initialCategory?: Category; guided?: boolean; showModels?: boolean; showEmail?: boolean; showSheets?: boolean; ondirty?: (value: boolean) => void; onready?: (value: boolean) => void; oncontinue?: () => void}>();
  let category = $state<Category>('Profile');
  let heading = $state<HTMLHeadingElement>();
  let saved = $state<Snapshot>();
  let draft = $state<Snapshot>();
  let errors = $state<FieldErrors>({});
  let saving = $state(false);
  let feedback = $state('Loading saved settings…');
  let failure = $state(false);
  let conflict = $state(false);
  let feedbackCategory = $state<Category>('Profile');
  let integration = $state<'email' | 'sheets'>('email');
  const groups: {label: string; items: Category[]}[] = [
    {label: 'Your search', items: ['Profile', 'Job Filters', 'Sources']},
    {label: 'Workspace', items: ['Resume Generation', 'AI Models', 'Notifications & Integrations']},
    {label: 'System', items: ['Diagnostics']}
  ];
  const descriptions: Record<Category, string> = {
    'Profile': 'Manage the personal details and experience used to match jobs and write your résumé.',
    'Job Filters': 'Choose what you’re looking for and which requirements matter most.',
    'Sources': 'Manage where jobs come from, search schedules and usage limits.',
    'Resume Generation': 'Create your master résumé and choose when job-specific drafts are generated.',
    'AI Models': 'Connect the models used for job matching and résumé writing.',
    'Notifications & Integrations': 'Manage email delivery and connect your spreadsheet.',
    'Diagnostics': 'Check worker health, recent activity and tasks that need attention.'
  };
  let importPending = $state(false);
  let importOpen = $state(false);
  let pendingImport = $state<PendingImport>();
  let importVersion = $state(0);
  let mounted = $state<Category[]>(['Profile']);
  let childDirty = $state({models:false,sources:false,generation:false,email:false,sheets:false});
  $effect(() => { if(!showModels)childDirty.models=false; if(!showEmail)childDirty.email=false; if(!showSheets)childDirty.sheets=false; });
  $effect(() => { if (!mounted.includes(category)) mounted = [...mounted, category]; });
  const dirty = $derived(!!draft && !!saved && JSON.stringify(draft) !== JSON.stringify(saved));
  const profileDirty = $derived(!!draft && !!saved && JSON.stringify(draft.profile) !== JSON.stringify(saved.profile));
  const filtersDirty = $derived(!!draft && !!saved && JSON.stringify(draft.preferences) !== JSON.stringify(saved.preferences));
  const sectionDirty = $derived(guided ? dirty || !!pendingImport || importPending : category === 'Profile' ? profileDirty || !!pendingImport || importPending : filtersDirty);
  const visibleErrors = $derived(Object.entries(errors).filter(([path]) => guided || path.startsWith(category === 'Job Filters' ? 'preferences' : 'profile')));
  function isDirty(value: Category) {
    switch (value) {
      case 'Profile': return profileDirty || !!pendingImport || importPending;
      case 'Job Filters': return filtersDirty;
      case 'Sources': return childDirty.sources;
      case 'AI Models': return childDirty.models;
      case 'Resume Generation': return childDirty.generation;
      case 'Notifications & Integrations': return childDirty.email || childDirty.sheets;
      default: return false;
    }
  }
  const anyDirty = $derived(dirty || importPending || !!pendingImport || Object.values(childDirty).some(Boolean));
  $effect(() => { ondirty(anyDirty); });
  $effect(() => { onready(!!saved && !saving && !importPending); });
  function selectHash(hash: string) {
    let chosen = '';
    try { chosen = decodeURIComponent(hash.slice(1)); } catch { /* Malformed bookmarks use Profile. */ }
    const [section, connection] = chosen.split('/');
    const target = categories.includes(section as Category) ? section as Category : 'Profile';
    if (target === 'Notifications & Integrations') integration = connection === 'Google Sheets' ? 'sheets' : 'email';
    if (target !== category) void selectCategory(target);
  }
  afterNavigate(() => {
    // Router state can lag native fragment changes; use the current address bar.
    if (!guided) selectHash(location.hash);
  });
  async function selectCategory(value: Category) {
    category = value;
    await tick();
    heading?.focus({preventScroll: true});
    window.scrollTo({top: 0, behavior: 'instant'});
  }
  async function navigate(value: Category) {
    if (value === category) return;
    if (guided) await selectCategory(value);
    else {
      const url = new URL(page.url.href); url.hash = value === 'Notifications & Integrations' && integration === 'sheets' ? `${value}/Google Sheets` : value;
      await goto(url, {state: page.state, reset: false});
      await selectCategory(value);
    }
  }
  async function navigateIntegration(value: 'email' | 'sheets') {
    if (value === integration) return;
    const url = new URL(page.url.href);
    url.hash = `Notifications & Integrations/${value === 'sheets' ? 'Google Sheets' : 'Email alerts'}`;
    await goto(url, {state: page.state, reset: false});
    integration = value;
  }
  async function load() {
    try {
      const data = await api.request<Snapshot>('/api/profile-settings');
      saved = data; draft = structuredClone(data); errors = {}; failure = false; conflict = false;
      pendingImport = undefined; importPending = false; importVersion += 1;
      feedback = data.revision ? 'Your saved settings are up to date.' : 'Add the details you know. You can leave the rest blank.';
      feedbackCategory = category;
    } catch (reason) { feedback = (reason as Error).message; failure = true; }
  }
  function discard() {
    if (!saved || !draft) return;
    if (guided) draft = structuredClone($state.snapshot(saved));
    else if (category === 'Profile') draft.profile = structuredClone($state.snapshot(saved.profile));
    else draft.preferences = structuredClone($state.snapshot(saved.preferences));
    errors = {}; failure = false;
    if (guided || category === 'Profile') {
      pendingImport = undefined; importPending = false; importVersion += 1;
    }
    feedback = 'Changes discarded.'; feedbackCategory = category;
  }
  async function focusError() {
    const path = Object.keys(errors)[0];
    category = path?.startsWith('preferences') ? 'Job Filters' : 'Profile';
    await tick();
    const field = path ? document.getElementById(path) : null;
    (field ?? heading)?.focus();
    field?.scrollIntoView({block: 'center'});
  }
  export async function save(): Promise<boolean> {
    if (!draft || !saved || saving || conflict || ((guided || category === 'Profile') && importPending)) return false;
    if (!guided && category === 'Job Filters' && pendingImport) return false;
    if (saved.revision && !sectionDirty) return true;
    const savingCategory = category;
    const saveProfile = guided || category === 'Profile';
    const saveFilters = guided || category === 'Job Filters';
    const snapshot = structuredClone($state.snapshot(draft));
    if (!saveProfile) snapshot.profile = structuredClone($state.snapshot(saved.profile));
    if (!saveFilters) snapshot.preferences = structuredClone($state.snapshot(saved.preferences));
    errors = validateSettings(snapshot); failure = false; feedbackCategory = category;
    if (Object.keys(errors).length) { feedback = 'Check the highlighted fields before saving.'; failure = true; await focusError(); return false; }
    saving = true;
    try {
      const settings = {expected_revision: saved.revision, profile: snapshot.profile, preferences: snapshot.preferences};
      const data = pendingImport && saveProfile
        ? await api.request<Snapshot>(`/api/resume-imports/${pendingImport.id}/confirm`, {...pendingImport.review, confirmed: true, settings})
        : await api.request<Snapshot>('/api/profile-settings', settings);
      const profile = draft.profile; const preferences = draft.preferences;
      saved = data; draft = structuredClone(data);
      if (!saveProfile) draft.profile = profile;
      if (!saveFilters) draft.preferences = preferences;
      feedbackCategory = savingCategory;
      feedback = guided ? 'Settings saved.' : `${savingCategory === 'Profile' ? 'Profile' : 'Job filters'} saved.`;
      if (saveProfile) { pendingImport = undefined; importPending = false; importVersion += 1; }
      return true;
    } catch (reason) {
      feedback = (reason as Error).message; failure = true;
      if (reason instanceof ApiError) {
        conflict = reason.status === 409;
        errors = Object.fromEntries(reason.fields.map(error => [error.field, error.message]));
        if (Object.keys(errors).length) await focusError();
      }
      return false;
    } finally { saving = false; }
  }
  beforeNavigate(({cancel, to}) => {
    if (to?.url.pathname === page.url.pathname && to.url.search === page.url.search) return;
    if (!guided && anyDirty && !confirm('You have unsaved settings. Leave without saving?')) cancel();
  });
  onMount(() => {
    if (guided) { category = initialCategory; importOpen = true; }
    else selectHash(location.hash);
    void load();
    const warn = (event: BeforeUnloadEvent) => { if (!guided && anyDirty) event.preventDefault(); };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  });
</script>
<svelte:window onhashchange={() => {if (!guided) selectHash(location.hash);}} />
{#if !guided}<section class="settings-heading"><h1>Settings</h1><p class="intro">Your facts, preferences and connections, in one place.</p></section>{/if}
<div class="settings-layout" class:guided class:settings-workspace={!guided}>
  {#if !guided}
    <nav class="settings-nav" aria-label="Settings categories">
      {#each groups as group}
        <div class="nav-group"><p class="nav-group-label">{group.label}</p>
          {#each group.items as value}<button class:chosen={category === value} aria-label={value} aria-current={category === value ? 'page' : undefined} onclick={() => navigate(value)}><span>{value}</span>{#if isDirty(value)}<span class="dirty-dot" aria-label="Unsaved changes"></span>{/if}</button>{/each}
        </div>
      {/each}
      <p class="nav-help">Changes stay in their section until you save or discard them.</p>
    </nav>
    <label class="mobile-section-picker">Settings section
      <select value={category} onchange={event => navigate(event.currentTarget.value as Category)}>
        {#each groups as group}<optgroup label={group.label}>{#each group.items as value}<option value={value}>{value}{isDirty(value) ? ' · Unsaved' : ''}</option>{/each}</optgroup>{/each}
      </select>
    </label>
  {/if}
  <section class="settings-panel" aria-labelledby={guided ? undefined : 'settings-section-title'}>
    {#if !guided}<div class="settings-panel-header"><div><h2 id="settings-section-title" bind:this={heading} tabindex="-1">{category}</h2><p class="section-description">{descriptions[category]}</p></div>{#if category === 'Profile' || category === 'Job Filters'}<span class="saved-label" class:unsaved={sectionDirty}>{sectionDirty ? 'Unsaved changes' : saved?.revision ? 'Saved' : 'Not saved yet'}</span>{/if}</div>{/if}
    {#if draft}
      {#if !guided || category === 'Profile'}<div hidden={category !== 'Profile'}><details class="settings-import" bind:open={importOpen}><summary>Import from a résumé<span>Fill your profile from a PDF, Word or LaTeX file.</span></summary>{#key importVersion}<ResumeImport saveLabel={guided?'Save and continue':'Save changes'} profileRevision={saved?.revision ?? 0} dirty={profileDirty || !!pendingImport} disabled={saving || conflict} onpending={value => { importPending = value; }} onreload={() => { void load(); }} onfill={(value, profile) => {
        if (!draft || profileDirty || saving || value.review.expected_revision !== saved?.revision) return false;
        draft.profile = structuredClone(profile); pendingImport = value;
        errors = {}; failure = false; feedbackCategory = 'Profile'; feedback = 'Review the filled profile fields, then save your changes.';
        return true;
      }} />{/key}</details></div>{/if}
      <form id={guided?'setup-settings-form':undefined} onsubmit={event => {event.preventDefault(); if(guided)oncontinue();else void save();}} novalidate>
        <fieldset class="settings-fields" class:profile-fields={category === 'Profile'} disabled={saving}>
          {#if category === 'Profile'}<ProfileSettings disabled={saving} bind:profile={draft.profile} {errors} />
          {:else if category === 'Job Filters'}<JobFilterSettings disabled={saving} bind:preferences={draft.preferences} {errors} />{/if}
        </fieldset>
        {#if category === 'Profile' || category === 'Job Filters'}
          {#if !guided && category === 'Job Filters' && pendingImport}<p class="import-notice">Save or discard your imported profile before saving filters. <button type="button" class="subtle" onclick={() => navigate('Profile')}>Review imported profile</button></p>{/if}
          {#if visibleErrors.length}<div class="validation-summary" role="alert"><p>Please check the highlighted fields:</p><ul>{#each visibleErrors as [field]}<li><a href={`#${field}`} onclick={event => { event.preventDefault(); document.getElementById(field)?.focus(); }}>{field === 'profile.email' ? 'Email' : field === 'profile.available_until' ? 'Available until' : field.includes('.facts.') ? 'Supporting fact' : field.includes('.education.') ? 'Education details' : 'Review field'}</a></li>{/each}</ul></div>{/if}
          <div class="settings-save"><p class:error={failure && feedbackCategory === category} role={failure && feedbackCategory === category ? 'alert' : 'status'}>{saving ? 'Saving your changes…' : failure && feedbackCategory === category ? feedback : sectionDirty ? guided ? 'Your changes will be saved when you continue.' : `You have unsaved ${category === 'Profile' ? 'profile' : 'filter'} changes.` : feedbackCategory === category ? feedback : 'Your saved settings are up to date.'}</p><div>
            <button type="button" class="subtle" disabled={saving || !sectionDirty} onclick={discard}>Discard changes</button>
            {#if !guided}<button class="primary" type="submit" disabled={saving || (!sectionDirty && !!saved?.revision) || conflict || importPending || (category === 'Job Filters' && !!pendingImport)}>{saving ? 'Saving…' : 'Save changes'}</button>{/if}
          </div></div>
          {#if conflict}<button type="button" class="secondary" onclick={() => {if (confirm('Reload saved settings and discard your unsaved draft?')) void load();}}>Reload saved settings</button>{/if}

        {/if}
      </form>
      {#if category === 'Diagnostics'}<Diagnostics />{/if}
      {#if mounted.includes('Sources')}<div hidden={category !== 'Sources'}><SourceSettings allowRun={!guided} ondirty={value=>{childDirty.sources=value;}} /></div>{/if}
      {#if showModels && mounted.includes('AI Models')}<div hidden={category !== 'AI Models'}><AiModelSettings ondirty={value=>{childDirty.models=value;}} /></div>{/if}
      {#if mounted.includes('Resume Generation')}<div hidden={category !== 'Resume Generation'}><MasterResume profileRevision={saved?.revision ?? 0} dirty={profileDirty || importPending || !!pendingImport} /><GenerationPolicySettings ondirty={value=>{childDirty.generation=value;}} /></div>{/if}
      {#if mounted.includes('Notifications & Integrations')}
        <div hidden={category !== 'Notifications & Integrations'}>
          {#if !guided}<nav class="integration-nav" aria-label="Integrations"><button aria-label="Email alerts" class:chosen={integration === 'email'} aria-current={integration === 'email' ? 'page' : undefined} onclick={() => navigateIntegration('email')}>Email alerts{#if childDirty.email}<span class="dirty-dot" aria-label="Unsaved email changes"></span>{/if}</button><button aria-label="Google Sheets" class:chosen={integration === 'sheets'} aria-current={integration === 'sheets' ? 'page' : undefined} onclick={() => navigateIntegration('sheets')}>Google Sheets{#if childDirty.sheets}<span class="dirty-dot" aria-label="Unsaved Sheets changes"></span>{/if}</button></nav>{/if}
          {#if showEmail}<div hidden={!guided && integration !== 'email'}><EmailSettings {guided} ondirty={value=>{childDirty.email=value;}} /></div>{/if}
          {#if showSheets}<div hidden={!guided && integration !== 'sheets'}><SheetsSettings {guided} ondirty={value=>{childDirty.sheets=value;}} /></div>{/if}
        </div>
      {/if}
    {:else}<p role={failure ? 'alert' : 'status'}>{feedback}</p>{#if failure}<button class="secondary" onclick={load}>Retry loading settings</button>{/if}{/if}
  </section>
</div>
<style>
  .settings-layout:has(> .settings-panel:only-child) { grid-template-columns: minmax(0, 1fr); }
  .guided .settings-panel { border:0; padding:0; }
  .guided .settings-save { position:static; flex-wrap:wrap; }
  .guided .settings-import > summary { display: none; }
  .settings-import { margin: 0 0 24px; border: 1px solid var(--border); border-radius: var(--radius); padding: 0 16px; }
  .guided .settings-import { border: 0; padding: 0; }
  .settings-import summary { cursor: pointer; padding: 14px 0; font-weight: 600; }
  .settings-import summary span { display: block; margin-top: 4px; color: var(--muted); font-size: 13px; font-weight: 400; }
  .settings-import :global(.resume-import) { border: 0; margin: 0; padding-bottom: 16px; }
  .settings-fields { border: 0; padding: 0; margin: 0; min-width: 0; }
  .validation-summary { color: #a83424; overflow-wrap: anywhere; }
  :global(.fact-entry) { border: 0; border-top: 1px solid var(--border); padding: 20px 0; margin: 24px 0; min-width: 0; }
  :global(.fact-entry legend) { font-weight: 600; padding: 0 12px 0 0; }
  :global(.field-error) { color: #a83424; font-size: 13px; margin: 6px 0; }
  :global([aria-invalid=true]) { border-color: #a83424; }
  :global(.form-group select) { max-width: 100%; width: 100%; margin-top: 7px; }

  .settings-workspace { grid-template-columns: 224px minmax(0, 1fr); gap: 40px; max-width: 1120px; align-items: start; }
  .settings-workspace .settings-nav { gap: 24px; top: 28px; }
  .nav-group { display: grid; gap: 4px; }
  .settings-nav .nav-group-label { margin: 0 12px 8px; color: var(--muted); font-size: 11px; font-weight: 650; letter-spacing: .08em; text-transform: uppercase; }
  .settings-workspace .settings-nav button { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; min-height: 44px; padding: 11px 12px; border: 0; border-radius: var(--radius); line-height: 1.45; color: var(--muted); }
  .settings-workspace .settings-nav button.chosen { background: var(--selected); color: var(--accent); box-shadow: inset 3px 0 var(--accent); }
  .settings-nav .nav-help { margin: 0 12px; font-size: 12px; line-height: 1.6; }
  .dirty-dot { display: inline-block; width: 7px; height: 7px; flex-shrink: 0; border-radius: 50%; background: var(--accent); }
  .mobile-section-picker { display: none; }
  .settings-workspace .settings-panel { padding: 0 0 0 36px; }
  .settings-workspace .settings-panel-header > div { flex: 1; min-width: 0; }
  .settings-workspace .settings-panel-header { align-items: flex-start; margin-bottom: 28px; padding-bottom: 24px; border-bottom: 1px solid var(--border); }
  .settings-panel-header h2 { scroll-margin-top: 24px; }
  .section-description { margin: 0; color: var(--muted); max-width: 55ch; font-size: 14px; }
  .saved-label { flex-shrink: 0; padding: 5px 9px; background: var(--surface-subtle); border: 1px solid var(--border); border-radius: var(--radius); white-space: nowrap; }
  .saved-label.unsaved { color: var(--accent); background: var(--selected); }
  .settings-workspace :global(.form-intro) { margin: 0 0 24px; }
  .settings-workspace :global(.form-group) { padding: 28px 0; }
  .settings-workspace .profile-fields :global(.form-intro) { display: none; }
  .settings-workspace .profile-fields :global(.form-group:first-of-type) { border-top: 0; padding-top: 0; }
  .settings-workspace :global(.source-settings .form-group) { padding: 12px 0; border: 0; }
  .settings-workspace :global(.form-group h3) { margin-bottom: 14px; }
  .settings-workspace :global(.field-help) { font-size: 13px; line-height: 1.6; }
  .settings-workspace :global(.choice-field button) { min-width: 44px; min-height: 44px; }
  .settings-workspace :global(button), .settings-workspace :global(summary) { min-height: 44px; }
  .settings-workspace :global(input:not([type=checkbox])), .settings-workspace :global(select), .settings-workspace :global(textarea) { min-height: 44px; }
  .settings-workspace :global(.settings-save) { padding: 16px 0 max(16px, env(safe-area-inset-bottom)); gap: 16px; box-shadow: 0 -8px 16px rgb(23 33 59 / 3%); }
  .settings-workspace :global(.settings-save p) { font-size: 13px; }
  .settings-workspace :global(.settings-save button) { white-space: nowrap; }
  .settings-workspace :global(.fact-entry) { padding: 20px; background: var(--surface-subtle); border: 1px solid var(--border); border-radius: var(--radius); margin: 20px 0; }
  .settings-workspace :global(.fact-entry legend) { padding: 0 8px; }
  .settings-workspace :global(.fact-entry input), .settings-workspace :global(.fact-entry textarea), .settings-workspace :global(.fact-entry select) { background: var(--surface); }
  .settings-workspace :global(.form-group input), .settings-workspace :global(.form-group select), .settings-workspace :global(.form-group textarea) { scroll-margin: 24px 0 120px; }
  .integration-nav { display: flex; gap: 8px; margin: 0 0 28px; padding-bottom: 12px; border-bottom: 1px solid var(--border); }
  .integration-nav button { display: flex; align-items: center; gap: 10px; padding: 10px 16px; border-radius: var(--radius); color: var(--muted); }
  .integration-nav button.chosen { background: var(--selected); color: var(--accent); font-weight: 600; }
  .settings-workspace :global(.mapping) { gap: 12px 20px; }
  .settings-workspace :global(.form-grid) { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
  .settings-workspace :global(section:has(> h3)) { margin-top: 0; border-top: 0; padding-top: 0; }
  .import-notice { padding: 12px 16px; background: var(--selected); border-radius: var(--radius); }
  .import-notice button { color: var(--accent); text-decoration: underline; }
  .validation-summary { padding: 16px 20px; border: 1px solid currentColor; border-radius: var(--radius); margin: 16px 0; }
  .validation-summary p { margin: 0 0 8px; }
  .validation-summary ul { margin: 0; padding-left: 20px; }
  .validation-summary a { color: inherit; text-decoration: underline; }
  @media (max-width: 1000px) and (min-width: 761px) {
    .settings-workspace { grid-template-columns: 190px minmax(0, 1fr); gap: 24px; }
    .settings-workspace .settings-panel { padding-left: 24px; }
  }
  @media (max-width: 760px) {
    .settings-workspace { grid-template-columns: minmax(0, 1fr); gap: 24px; }
    .settings-workspace .settings-nav { display: none; }
    .mobile-section-picker { display: grid; gap: 8px; font-size: 13px; font-weight: 600; }
    .mobile-section-picker select { width: 100%; font-size: 16px; background: var(--surface-subtle); }
    .settings-workspace .settings-panel { border: 0; padding: 0; }
    .settings-workspace .settings-panel-header { flex-wrap: wrap; gap: 12px; margin-bottom: 24px; padding-bottom: 20px; }
    .settings-workspace .settings-panel-header h2 { font-size: 24px; }
    .settings-workspace :global(.form-grid) { grid-template-columns: minmax(0, 1fr); }
    .settings-workspace :global(input:not([type=checkbox])), .settings-workspace :global(select), .settings-workspace :global(textarea) { font-size: 16px; }
    .settings-workspace :global(.settings-save) { flex-direction: column; align-items: stretch; gap: 12px; }
    .settings-workspace :global(.settings-save > div) { margin: 0; display: flex; }
    .settings-workspace :global(.settings-save > div > button) { flex: 1; }
    .settings-workspace :global(.fact-entry) { padding: 16px; }
  }
</style>
