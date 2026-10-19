<script lang="ts">
  import { getContext, onMount, tick } from 'svelte';
  import { beforeNavigate, goto } from '$app/navigation';
  import { Api } from '#lib/api.ts';
  import SettingsWorkspace from '#lib/components/SettingsWorkspace.svelte';
  import { category, correction, labels, steps, type Setup, type Step } from '#lib/onboarding.ts';
  const api = getContext<Api>('api');
  let setup = $state<Setup>();
  let error = $state('');
  let errorNotice = $state<HTMLParagraphElement>();
  let busy = $state(false);
  let dirty = $state(false);
  let deferModels = $state(false);
  let email = $state<'skip'|'connect'>('skip');
  let sheets = $state<'skip'|'connect'>('skip');
  let workspace = $state<{save:()=>Promise<boolean>}>();
  let workspaceReady = $state(false);
  let workspaceVersion = $state(0);
  let stepHeading = $state<HTMLHeadingElement>();
  const profileStep = $derived(setup?.step==='profile'||setup?.step==='filters');
  const choiceDirty = $derived(!!setup && ((setup.step==='models' && deferModels!==setup.defer_models) || (setup.step==='integrations' && (email!==(setup.email??'skip') || sheets!==(setup.sheets??'skip')))));
  const anyDirty = $derived(dirty || choiceDirty);
  let changingStep = false;
  beforeNavigate(({cancel})=>{if(anyDirty&&!confirm('You have unsaved setup changes. Leave without saving?'))cancel();});
  function assign(value:Setup) {
    setup=value; deferModels=value.defer_models; email=value.email??'skip'; sheets=value.sheets??'skip';
  }
  async function load() {try {assign(await api.request<Setup>('/api/onboarding'));error='';}catch(e){error=(e as Error).message;}}
  async function action(path:string, body:unknown) {
    busy=true;error='';
    try {const value=await api.request<Setup>(`/api/onboarding/${path}`,body);if(value.step!==setup?.step)workspaceReady=false;assign(value);await tick();stepHeading?.focus();stepHeading?.scrollIntoView({block:'start'});return true;}
    catch(e) {error=(e as Error).message;await tick();errorNotice?.focus();errorNotice?.scrollIntoView({block:'center'});return false;}
    finally {busy=false;}
  }
  async function visit(step:Step) {if(busy||step===setup?.step)return;if (anyDirty && !confirm('You have unsaved changes. Leave this step without saving?')) return;changingStep=true;const moved=await action('visit',{step});if(moved)dirty=false;changingStep=false;}
  function discardForChoice() {
    if(dirty&&!confirm('Discard unsaved changes on this step and change this setup choice?'))return false;
    if(dirty){dirty=false;workspaceReady=false;workspaceVersion+=1;}
    return true;
  }
  function chooseIntegration(event:Event,kind:'email'|'sheets') {
    const select=event.currentTarget as HTMLSelectElement;
    if(!discardForChoice()){select.value=kind==='email'?email:sheets;return;}
    if(kind==='email')email=select.value as 'skip'|'connect';else sheets=select.value as 'skip'|'connect';
  }
  async function next() {
    if (!setup || busy || (profileStep ? !workspaceReady : dirty)) return;
    busy=true;
    try {
      if(profileStep && !await workspace?.save())return;
      await action('checkpoint',{step:setup.step,...(setup.step==='models'?{defer_models:deferModels}:{}),...(setup.step==='integrations'?{email,sheets}:{})});
    } finally {busy=false;}
  }
  async function finish() {if(await action('finish',{preview:setup?.preview_token}))await goto('/');}
  onMount(()=>{const warn=(event:BeforeUnloadEvent)=>{if(anyDirty)event.preventDefault();};window.addEventListener('beforeunload',warn);void load();return()=>{window.removeEventListener('beforeunload',warn);};});
</script>
<svelte:head><title>Guided setup · Internship Pipeline</title></svelte:head>
<section class="settings-heading"><h1>Set up your workspace</h1><p class="intro">Tell us what you're looking for, then find your first internships. You can change these settings later.</p></section>
{#if error}<p class="error" role="alert" tabindex="-1" bind:this={errorNotice}>{error}</p>{/if}
{#if setup}
  <nav class="setup-steps" aria-label="Setup steps">
    {#each steps as step, index}<button class:chosen={setup.step===step} aria-current={setup.step===step?'step':undefined} onclick={()=>visit(step)} disabled={busy}>{index+1}. {labels[step]}{setup.reviewed.includes(step)?' ✓':''}</button>{/each}
  </nav>
  <section class="setup-context"><p class="step-count">Step {steps.indexOf(setup.step)+1} of {steps.length}</p><h2 bind:this={stepHeading} tabindex="-1">{labels[setup.step]}</h2>
    {#if setup.step==='models'}<p>Connect models to assess job fit and draft tailored résumés, or start with job discovery and add them later.</p><label class="choice"><input type="checkbox" disabled={busy} checked={deferModels} onchange={event=>{if(discardForChoice())deferModels=event.currentTarget.checked;else event.currentTarget.checked=deferModels;}}/> Defer model work and collect jobs first</label>{#if deferModels}<p class="field-help">You can import your résumé and find jobs now. Fit scores and tailored drafts will wait until you connect models in Settings.</p>{/if}
    {:else if setup.step==='profile'}<p>Import your résumé to fill in the form, or enter your details below. Review the information and select Save and continue. You can leave unknown fields empty.</p>
    {:else if setup.step==='filters'}<p>Choose the roles and places you're interested in. Required preferences filter your results; preferred options help rank job fit.</p>
    {:else if setup.step==='integrations'}<p>Get job alerts by email or track opportunities in Google Sheets. Both are optional, and you can connect them later in Settings.</p><div class="choices"><label class="form-field">Email during setup<select disabled={busy} value={email} onchange={event=>chooseIntegration(event,'email')}><option value="skip">Skip email</option><option value="connect">Connect and test email</option></select></label><label class="form-field">Sheets during setup<select disabled={busy} value={sheets} onchange={event=>chooseIntegration(event,'sheets')}><option value="skip">Skip Sheets</option><option value="connect">Connect and test Sheets</option></select></label></div>{#if email==='skip'&&sheets==='skip'}<p class="field-help">You’ll find and track your jobs in the app. No email or Google account is needed.</p>{/if}
    {/if}
  </section>
  {#if category[setup.step]}
    <div inert={busy&&!profileStep}>{#key `${setup.step}:${workspaceVersion}`}<SettingsWorkspace bind:this={workspace} initialCategory={category[setup.step]} guided showModels={!deferModels} showEmail={email==='connect'} showSheets={sheets==='connect'} onready={value=>{workspaceReady=value;}} oncontinue={()=>void next()} ondirty={value=>{if(!changingStep)dirty=value;}}/>{/key}</div>
    <div class="setup-actions"><p role="status">{dirty&&!profileStep?'Save or discard your connection changes before continuing.':'Your progress is saved when you continue.'}</p><div class="action-buttons">{#if steps.indexOf(setup.step)>0}<button class="secondary" disabled={busy} onclick={()=>visit(steps[steps.indexOf(setup!.step)-1])}>Back</button>{/if}<button class="primary" type={profileStep?'submit':'button'} form={profileStep?'setup-settings-form':undefined} disabled={busy||(profileStep?!workspaceReady:dirty)} onclick={()=>{if(!profileStep)void next();}}>{busy?'Saving…':profileStep?'Save and continue':'Continue'}</button></div></div>
  {:else if setup.step==='review'}
    <section class="settings-panel preview" aria-label="Final configuration preview">
      <p>Check your saved details and the searches we'll run. Collection starts when you finish, and your Jobs page opens right away.</p>
      <h3>Your profile <button class="text-button" onclick={()=>visit('profile')}>Edit profile</button></h3>
      <p>{setup.preview.profile.name||'Name not provided'} · {setup.preview.profile.email||'Email not provided'} · {setup.preview.confirmed_facts} confirmed supporting facts.</p>
      <p>Availability: {setup.preview.profile.available_from||'unknown'} through {setup.preview.profile.available_until||'unknown'}. Sponsorship: {setup.preview.profile.requires_sponsorship===null?'unknown':setup.preview.profile.requires_sponsorship?'required':'not required'}. Authorization: {setup.preview.profile.work_authorization.join(', ')||'unknown'}.</p>
      <h3>Job preferences <button class="text-button" onclick={()=>visit('filters')}>Edit job filters</button></h3>
      <p>Required countries: {setup.preview.preferences.hard.countries.join(', ')||'Any'}; locations: {setup.preview.preferences.hard.locations.join(', ')||'Any'}; terms: {setup.preview.preferences.hard.term_keywords.join(', ')||'Any'}.</p>
      <p>Preferred roles: {setup.preview.preferences.soft.roles.join(', ')||'Any internship'}; locations: {setup.preview.preferences.soft.locations.join(', ')||'Any'}; skills: {setup.preview.preferences.soft.skills.join(', ')||'None selected'}.</p>
      <h3>AI models <button class="text-button" onclick={()=>visit('models')}>Edit model connections</button></h3>
      {#each Object.entries(setup.preview.models) as [kind, model]}<p>{kind==='jev'?'Jev':'General LLM'}: {model.model||'not configured'} · {model.status} · revision {model.revision}.</p>{/each}
      <p>{setup.preview.defer_models?'Model setup is deferred. You can find jobs now and connect models later for fit scores and tailored drafts.':'Job fit assessments and résumé drafts use your tested connections.'}</p>
      <h3>Optional integrations <button class="text-button" onclick={()=>visit('integrations')}>Edit integrations</button></h3>
      <p>Email: {setup.preview.email.choice==='skip'?'Skipped':setup.preview.email.status} · alerts {setup.preview.email.enabled?'enabled':'off'}. Sheets: {setup.preview.sheets.choice==='skip'?'Skipped':setup.preview.sheets.status} · automatic sync {setup.preview.sheets.enabled?'enabled':'off'}.</p>
      {#if (setup.preview.email.choice==='skip'&&setup.preview.email.enabled)||(setup.preview.sheets.choice==='skip'&&setup.preview.sheets.enabled)}<p class="field-help">Skipping setup doesn't disable a previously enabled integration. <a href={correction('integrations')}>Manage enabled integrations</a></p>{/if}
      <details><summary>Résumé generation settings</summary><p>Automatic résumé generation is {setup.preview.generation.enabled?'enabled':'off'}. Minimum fit {setup.preview.generation.minimum_fit}; recommendation {setup.preview.generation.recommendation}; eligibility {setup.preview.generation.eligibility}. Only confirmed facts support drafts, and every generated document needs review. <a href="/settings/?setup=1#Resume%20Generation">Edit generation policy</a></p></details>
      <h3>Your automatic searches</h3>
      <p>These searches use your saved roles and locations. Terms, skills, availability and eligibility preferences guide matching after collection. You can adjust searches later in Settings.</p>
      {#each setup.preview.searches as search}<p>{search.search_term} · {search.location || 'All locations'} · {search.country} · {search.sites.join(', ')}.</p>{/each}
      {#if setup.blockers.length}<div class="setup-blockers" role="status"><h3>A few things need your attention</h3><ul>{#each setup.blockers as blocker}<li>{blocker.message} <button class="text-button" onclick={()=>visit(blocker.step)}>Review {labels[blocker.step]}</button></li>{/each}</ul></div>{/if}
      <p class="field-help">You review résumé drafts and submit applications yourself. Finding a job or downloading a résumé never marks it as Applied.</p>
      <div class="setup-actions"><button class="secondary" disabled={busy} onclick={()=>visit('integrations')}>Back</button><button class="primary" disabled={busy||!!setup.blockers.length} onclick={finish}>{busy?'Starting your workspace…':'Finish setup and find jobs'}</button></div>
      <button class="text-button" disabled={busy} onclick={()=>action('visit',{step:'review'})}>Refresh configuration preview</button>
    </section>
  {/if}
{:else}<p role="status">Loading saved setup…</p>{#if error}<button class="secondary" onclick={load}>Retry setup</button>{/if}{/if}
<style>
  .setup-steps,.setup-actions,.choices,.action-buttons {display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:24px 0}
  .setup-steps button {min-height:44px;padding:10px;border:1px solid var(--border);border-radius:var(--radius);background:var(--surface);font:inherit;cursor:pointer}
  .setup-steps .chosen {border-color:var(--accent);color:var(--accent)}
  .setup-context {max-width:80ch;margin-bottom:24px}.choice {display:flex;gap:10px;align-items:center;min-height:44px;cursor:pointer}.choice input{width:20px;height:20px;flex-shrink:0}
  .choices>*{flex:1;min-width:200px}.setup-actions{justify-content:space-between}.preview p{overflow-wrap:anywhere}
  .step-count{color:var(--muted);font-size:14px;margin-bottom:8px}.setup-context h2{scroll-margin-top:24px}
  .setup-actions p,.action-buttons{margin:0}.setup-actions button,.text-button{min-height:44px}
  .preview{max-width:80ch;border:0;padding:0}.preview h3{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-top:28px}.preview details{margin:20px 0}.preview summary{cursor:pointer;padding:12px 0}
  .text-button{background:transparent;border:0;color:var(--accent);font:inherit;font-size:14px;text-align:left;padding:8px 0;cursor:pointer}
  .setup-blockers{border-left:3px solid var(--accent);padding-left:20px}.setup-blockers li{margin:12px 0}
  @media(max-width:600px){.setup-actions{align-items:stretch;flex-direction:column}.action-buttons{justify-content:space-between}.action-buttons button{flex:1}.setup-steps{gap:8px}.setup-steps button{text-align:left;font-size:14px}.choices>*{min-width:0;flex-basis:100%}}
</style>
