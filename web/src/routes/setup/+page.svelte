<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import { beforeNavigate, goto } from '$app/navigation';
  import { Api } from '#lib/api.ts';
  import SettingsWorkspace from '#lib/components/SettingsWorkspace.svelte';
  import { category, correction, labels, steps, type Setup, type Step } from '#lib/onboarding.ts';
  const api = getContext<Api>('api');
  let setup = $state<Setup>();
  let error = $state('');
  let busy = $state(false);
  let dirty = $state(false);
  let deferModels = $state(false);
  let email = $state<'skip'|'connect'>('skip');
  let sheets = $state<'skip'|'connect'>('skip');
  let chosenSearch = $state('');
  const choiceDirty = $derived(!!setup && ((setup.step==='models' && deferModels!==setup.defer_models) || (setup.step==='integrations' && (email!==(setup.email??'skip') || sheets!==(setup.sheets??'skip')))));
  const anyDirty = $derived(dirty || choiceDirty);
  let changingStep = false;
  beforeNavigate(({cancel})=>{if(anyDirty&&!confirm('You have unsaved setup changes. Leave without saving?'))cancel();});
  function assign(value:Setup) {
    setup=value; deferModels=value.defer_models; email=value.email??'skip'; sheets=value.sheets??'skip';
    if (!value.preview.searches.some(s=>s.id===chosenSearch&&!s.paused)) chosenSearch=value.preview.searches.find(s=>!s.paused)?.id??'';
  }
  async function load() {try {assign(await api.request<Setup>('/api/onboarding'));error='';}catch(e){error=(e as Error).message;}}
  async function action(path:string, body:unknown) {
    busy=true;error='';
    try {assign(await api.request<Setup>(`/api/onboarding/${path}`,body));return true;}
    catch(e) {error=(e as Error).message;return false;}
    finally {busy=false;}
  }
  async function visit(step:Step) {if(step===setup?.step)return;if (anyDirty && !confirm('You have unsaved changes. Leave this step without saving?')) return;changingStep=true;const moved=await action('visit',{step});if(moved)dirty=false;changingStep=false;}
  async function next() {
    if (!setup || dirty) return;
    await action('checkpoint',{step:setup.step,...(setup.step==='models'?{defer_models:deferModels}:{}),...(setup.step==='integrations'?{email,sheets}:{})});
  }
  async function finish() {await action('finish',{});if(setup?.complete)await goto('/');}
  onMount(()=>{const warn=(event:BeforeUnloadEvent)=>{if(anyDirty)event.preventDefault();};window.addEventListener('beforeunload',warn);void load();const timer=setInterval(()=>{if(setup?.step==='results')void load();},2000);return()=>{clearInterval(timer);window.removeEventListener('beforeunload',warn);};});
</script>
<svelte:head><title>Guided setup · Internship Pipeline</title></svelte:head>
<section class="settings-heading"><p class="eyebrow">GET STARTED · ACCOUNT CLAIMED</p><h1>Guided setup</h1><p class="intro">Save your settings once, review the configuration, then discover your first jobs. Your progress survives closing this page.</p></section>
{#if error}<p class="error" role="alert">{error}</p>{/if}
{#if setup}
  <nav class="setup-steps" aria-label="Setup steps">
    {#each steps as step, index}<button class:chosen={setup.step===step} aria-current={setup.step===step?'step':undefined} onclick={()=>visit(step)} disabled={busy}>{index+1}. {labels[step]}{setup.reviewed.includes(step)?' ✓':''}</button>{/each}
  </nav>
  <section class="setup-context"><h2>{labels[setup.step]}</h2>
    {#if setup.step==='models'}<p>Jev evaluates rubric fit and eligibility evidence. The general model creates tailored résumé drafts. Saving a connection does not call a provider; its test uses synthetic facts and may incur a provider charge.</p><label class="choice"><input type="checkbox" disabled={busy} bind:checked={deferModels}/> Defer model work and collect jobs first</label><p class="field-help">You can continue with unknown fit. Résumé import extracts text locally; tailored generation needs a tested general model, and evaluation needs a tested Jev connection. A failed test remains visible even when you choose to defer.</p>
    {:else if setup.step==='profile'}<p>Import a résumé and review the proposed facts, or enter facts manually below. Only confirmed supporting facts enter matching and generation. Unknown fields stay unknown, and job descriptions cannot add candidate claims.</p>
    {:else if setup.step==='filters'}<p>Hard country, location and term constraints affect eligibility filtering. Work authorization, availability and confirmed education also affect eligibility. Soft roles, locations and skills affect rubric fit, which measures alignment rather than interview probability. Unknown eligibility needs review.</p>
    {:else if setup.step==='search'}<p>Save an active source to collect its full inventory independently of models and delivery. Model jobs, calls and token limits cap review work; they do not limit stored collection. Initial backlog evaluation requires your explicit review after collection.</p>
    {:else if setup.step==='integrations'}<p>Both integrations are optional. Skipping them permits search and leaves application status under your control. Email tests send a synthetic message; Sheets tests inspect access, and synchronization requires a separate preview.</p><div class="choices"><label class="form-group">Email during setup<select disabled={busy} bind:value={email}><option value="skip">Skip email</option><option value="connect">Connect and test email</option></select></label><label class="form-group">Sheets during setup<select disabled={busy} bind:value={sheets}><option value="skip">Skip Sheets</option><option value="connect">Connect and test Sheets</option></select></label></div><p>Saved service status: email {setup.preview.email.status}; Sheets {setup.preview.sheets.status}. Incomplete means not configured or not verified; failed means a recorded test or service operation needs attention.</p>
    {/if}
  </section>
  {#if category[setup.step]}
    <div inert={busy}>{#key setup.step}<SettingsWorkspace initialCategory={category[setup.step]} guided ondirty={value=>{if(!changingStep)dirty=value;}}/>{/key}</div>
    <div class="setup-actions"><p role="status">{dirty?'Save or discard your changes before continuing.':'Continue uses the saved workspace settings.'}</p><button class="primary" disabled={busy||dirty} onclick={next}>{busy?'Saving progress…':'Save progress and continue'}</button></div>
  {:else if setup.step==='review'}
    <section class="settings-panel preview" aria-label="Final configuration preview">
      <h3>Review before your first run</h3>
      <p>Profile revision {setup.preview.profile_revision} · {setup.preview.confirmed_facts} confirmed supporting facts · {setup.preview.profile.name||'Name unknown'} · {setup.preview.profile.email||'Contact unknown'}.</p>
      <p>Availability: {setup.preview.profile.available_from||'unknown'} through {setup.preview.profile.available_until||'unknown'}. Sponsorship: {setup.preview.profile.requires_sponsorship===null?'unknown':setup.preview.profile.requires_sponsorship?'required':'not required'}. Authorization: {setup.preview.profile.work_authorization.join(', ')||'unknown'}.</p>
      <p>Hard countries: {setup.preview.preferences.hard.countries.join(', ')||'unrestricted'}; locations: {setup.preview.preferences.hard.locations.join(', ')||'unrestricted'}; terms: {setup.preview.preferences.hard.term_keywords.join(', ')||'unrestricted'}.</p>
      <p>Soft roles: {setup.preview.preferences.soft.roles.join(', ')||'none'}; locations: {setup.preview.preferences.soft.locations.join(', ')||'none'}; skills: {setup.preview.preferences.soft.skills.join(', ')||'none'}.</p>
      <p><a href={correction('profile')}>Correct profile</a> · <a href={correction('filters')}>Correct job filters</a></p>
      {#each Object.entries(setup.preview.models) as [kind, model]}<p>{kind==='jev'?'Jev':'General LLM'}: {model.model||'not configured'} · {model.status} · revision {model.revision}.</p>{/each}
      <p>Model work {setup.preview.defer_models?'may remain pending while models are deferred':'uses tested connections'}. <a href={correction('models')}>Correct model connections</a></p>
      <p>Automatic résumé generation is {setup.preview.generation.enabled?'enabled':'off'}. Minimum fit {setup.preview.generation.minimum_fit}; recommendation {setup.preview.generation.recommendation}; eligibility {setup.preview.generation.eligibility}. Only confirmed facts support drafts, and every generated document needs review. <a href="/settings/?setup=1#Resume%20Generation">Correct generation policy</a></p>
      <p>Email: {setup.preview.email.choice||'not reviewed'} · {setup.preview.email.status} · alerts {setup.preview.email.enabled?'enabled':'off'}. Sheets: {setup.preview.sheets.choice||'not reviewed'} · {setup.preview.sheets.status} · automatic sync {setup.preview.sheets.enabled?'enabled':'off'}. <a href={correction('integrations')}>Correct integrations</a></p>
      <p>Skip removes an integration prerequisite from setup; an already enabled saved integration remains enabled. Inspect the statuses above before running.</p>
      <label class="form-group">First search<select disabled={busy} bind:value={chosenSearch}><option value="">Choose an active search</option>{#each setup.preview.searches.filter(s=>!s.paused) as search}<option value={search.id}>{search.name}</option>{/each}</select></label>
      {#each setup.preview.searches as search}<p>{search.name}: {search.source} · {search.board||search.search_term} · {search.paused?'paused':'active'} · {search.daily_at?`daily ${search.daily_at} ${search.timezone}`:'manual only'} · review limits {search.max_jobs} jobs, {search.max_calls} calls, {search.max_tokens} reserved tokens.</p>{/each}
      <p><a href={correction('search')}>Correct sources and run limits</a></p>
      {#if setup.blockers.length}<ul>{#each setup.blockers as blocker}<li>{blocker.message} <button class="subtle" onclick={()=>visit(blocker.step)}>Review {labels[blocker.step]}</button></li>{/each}</ul>{/if}
      <p>Discovery, fit assessments, résumé drafts, delivered alerts and Applied are separate states. You mark Applied only after submitting an application yourself.</p>
      <button class="primary" disabled={busy||!!setup.blockers.length||!chosenSearch} onclick={()=>action('start',{preview:setup?.preview_token,search_id:chosenSearch})}>Confirm configuration and run first search</button>
      <button class="secondary" disabled={busy} onclick={()=>visit('review')}>Refresh configuration preview</button>
    </section>
  {:else if setup.step==='results'}
    <section class="settings-panel" aria-label="First search results">
      {#if setup.run}<h3>{setup.run.name}</h3><p role="status">Search status: {setup.run.stage.replaceAll('_',' ')}. {setup.run.collected} jobs collected · {setup.run.evaluated} evaluated · {setup.run.pending} pending · {setup.run.recommended} recommended.</p>
        {#if setup.run.source_error}<p role="alert">The source failed: {setup.run.source_error}. Your saved setup remains available.</p><a href={correction('search')}>Correct source connection</a>{/if}
        {#if setup.run.evaluation_error_codes.length}<p role="alert">Model service needs attention: {setup.run.evaluation_error_codes.join(', ')}.</p><a href={correction('models')}>Correct model connections</a>{/if}
        {#if setup.run.stage==='awaiting_model_configuration'}<p>Collection worked. Evaluation is incomplete because a profile or tested model is still needed.</p><a href={correction('models')}>Configure models</a>{/if}
        {#if setup.run.collected}<p>Your first jobs are ready to inspect. Initial inventory may be backlog, so approve review from Jobs when you want to use model capacity.</p><button class="primary" disabled={busy} onclick={finish}>Finish setup and view jobs</button>
        {:else if !['queued','collecting','fetched'].includes(setup.run.stage)}<p>No jobs were observed. Check the source and search terms, then review and run again.</p><a href={correction('search')}>Correct search settings</a>{/if}
      {:else}<p>Review the saved configuration before starting your first search.</p>{/if}
      <p>Work continues when you close the browser. <button class="secondary" disabled={busy} onclick={()=>visit('review')}>Return to configuration preview</button></p>
    </section>
  {/if}
{:else}<p role="status">Loading saved setup…</p>{#if error}<button class="secondary" onclick={load}>Retry setup</button>{/if}{/if}
<style>
  .setup-steps,.setup-actions,.choices {display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:24px 0}
  .setup-steps button {padding:10px;border:1px solid var(--border);border-radius:var(--radius);background:var(--surface);font:inherit;cursor:pointer}
  .setup-steps .chosen {border-color:var(--accent);color:var(--accent)}
  .setup-context {max-width:80ch;margin-bottom:24px}.choice {display:flex;gap:10px;align-items:center}.choice input{width:auto}
  .choices>*{flex:1;min-width:200px}.setup-actions{justify-content:space-between}.preview p{overflow-wrap:anywhere}
  @media(max-width:600px){.setup-actions{align-items:stretch;flex-direction:column}}
</style>
