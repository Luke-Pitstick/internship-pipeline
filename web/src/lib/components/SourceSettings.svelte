<script lang="ts">
  import {getContext,onMount,tick} from 'svelte';
  import {Api} from '#lib/api.ts';
  import SourceLibrary from './SourceLibrary.svelte';
  import type { SavedSource as Search } from '#lib/source-settings.ts';
  import JobIngestion from '#lib/components/JobIngestion.svelte';
  import ChoiceField from './ChoiceField.svelte';
  import { countryOptions, timezoneOptions, type Choice } from '#lib/input-options.ts';
  const api=getContext<Api>('api');
  let {allowRun=true,ondirty=()=>{}}=$props<{allowRun?:boolean;ondirty?:(value:boolean)=>void}>();
  const blank=()=>({id:'',revision:0,name:'',source:'greenhouse',board:'',search_term:'',location:'',country:'USA',sites:['indeed'],hours_old:72,results_wanted:100,daily_at:'09:00' as string|null,timezone:'UTC',max_jobs:20,max_calls:30,max_tokens:5000000,paused:false,next_run:null,last_success:null});
  let searches=$state<Search[]>([]); let draft=$state<Search>(blank());
  let ready=$state(false);let busy=$state(false);let error=$state(false);let message=$state('Loading searches…');
  let schedule=$state('09:00');
  let countries=$state<Choice[]>([]); let sites=$state<Choice[]>([]);
  let form: HTMLFormElement;
  let editorOpen=$state(false);
  const siteLabels: Record<string,string> = {indeed:'Indeed',linkedin:'LinkedIn',zip_recruiter:'ZipRecruiter',glassdoor:'Glassdoor',google:'Google',bayt:'Bayt',naukri:'Naukri',bdjobs:'BDJobs'};
  const boards = [
    {value:'greenhouse',label:'Greenhouse',example:'https://boards.greenhouse.io/example'},
    {value:'lever',label:'Lever',example:'https://jobs.lever.co/example'},
    {value:'ashby',label:'Ashby',example:'https://jobs.ashbyhq.com/example'},
  ];
  let savedDraft=$state(JSON.stringify({draft:blank(),schedule:'09:00'}));
  const dirty=$derived(JSON.stringify({draft,schedule})!==savedDraft);
  $effect(()=>{ondirty(dirty);});
  function edit(s?:Search){draft=s?structuredClone($state.snapshot(s)):blank();schedule=draft.daily_at??'';savedDraft=JSON.stringify({draft,schedule});}
  async function showEditor(s?:Search) {
    if (dirty && !confirm('Discard the unsaved search draft and edit another search?')) return;
    edit(s);
    editorOpen=true;
    await tick();
    form.scrollIntoView({block:'start'});
    form.querySelector<HTMLInputElement>('#source-name')?.focus({preventScroll:true});
  }
  async function addSource(source: string, site?: string) {
    if (dirty && !confirm('Discard the unsaved search draft and configure another source?')) return;
    edit();
    editorOpen=true;
    draft.source = source;
    if (site) draft.sites = [site];
    await tick();
    form.scrollIntoView({block:'start'});
    form.querySelector<HTMLInputElement>('#source-name')?.focus({preventScroll:true});
  }
  async function load() {
    try {
      const data = await api.request<{searches:Search[]; sites:string[]; countries:{value:string;code:string}[]}>('/api/search-settings');
      searches = data.searches;
      sites = data.sites.map(value => ({value, label:siteLabels[value] ?? value}));
      countries = data.countries.map(country => {
        const option = countryOptions.find(option => option.code === country.code);
        return {...option, label:option?.label ?? country.value, value:country.value};
      });
      ready=true; error=false; message='Saved searches are ready.';
    } catch (e) { error=true; message=(e as Error).message; }
  }
  async function save(){busy=true;try{const {id,revision,paused,next_run,last_success,...config}=draft;const body={...config,id:id||null,expected_revision:revision,daily_at:schedule||null};if(body.source==='jobspy')body.board='';else body.search_term='';searches=(await api.request<{searches:Search[]}>('/api/search-settings',body)).searches;edit();error=false;message='Search saved. Running work keeps its original settings.';}catch(e){error=true;message=(e as Error).message;}finally{busy=false;}}
  async function action(s:Search,kind:string){busy=true;try{searches=(await api.request<{searches:Search[]}>(`/api/search-settings/${s.id}/${kind}`,{expected_revision:s.revision,...(kind==='pause'?{paused:!s.paused}:{})})).searches;error=false;message=kind==='delete'?'Search removed; history is retained.':s.paused?'Search resumed.':'Search paused; existing work continues until cancelled.';}catch(e){error=true;message=(e as Error).message;}finally{busy=false;}}
  onMount(()=>{void load();});
</script>
{#if allowRun}<JobIngestion />{/if}
<SourceLibrary {searches} {ready} {busy} {allowRun} onedit={showEditor} onaction={action} />
{#if error && !ready}<p role="alert">{message}</p><button class="secondary" onclick={load}>Retry loading sources</button>{/if}
{#if ready && !editorOpen}<p class="source-message" role={error?'alert':'status'}>{message}</p>{/if}
<details class="available-sources">
  <summary>Add a source</summary>
  <p>Choose a source to configure a new search. Save it below to add it to your collection.</p>
  <h4>Search job sites</h4>
  <p class="field-help">Search by role and location. Availability and supported filters vary by site and country.</p>
  <div class="actions">
    {#each sites as site (site.value)}
      <button type="button" class="secondary" disabled={busy||!ready} onclick={() => addSource('jobspy',site.value)} aria-label={`Add ${site.label} search`}>{site.label}</button>
    {/each}
  </div>
  <h4>Follow company boards</h4>
  <p class="field-help">Collect directly from an employer’s board. You’ll need its company board token.</p>
  <div class="actions">
    {#each boards as board (board.value)}
      <button type="button" class="secondary" disabled={busy||!ready} onclick={() => addSource(board.value)} aria-label={`Add ${board.label} company board`}>{board.label}</button>
    {/each}
  </div>
</details>
<details class="source-editor" bind:open={editorOpen}>
<summary>{draft.id?`Edit ${draft.name}`:'Configure a saved search'}{dirty?' · Unsaved changes':''}</summary>
<form class="source-settings" bind:this={form} onsubmit={e=>{e.preventDefault();void save();}}><fieldset disabled={busy||!ready}>
  <h3>{draft.id?'Edit search':'Add a saved search'}</h3>
  <div class="form-group"><label for="source-name">Search name</label><input id="source-name" bind:value={draft.name} required maxlength="120" disabled={!ready||busy}/></div>
  <div class="form-group"><label for="source-type">Source</label><select id="source-type" bind:value={draft.source}><option value="greenhouse">Greenhouse company board</option><option value="lever">Lever company board</option><option value="ashby">Ashby company board</option><option value="jobspy">Job site search</option></select></div>
  {#if draft.source==='jobspy'}
    <div class="form-group"><label for="search-term">Search term</label><input id="search-term" bind:value={draft.search_term} required maxlength="200"/></div>
    <div class="form-group"><label for="search-location">Location</label><input id="search-location" bind:value={draft.location} maxlength="200"/></div>
    <div class="form-group"><ChoiceField name="search-country" label="Country" options={countries} max={1} required disabled={busy||!ready} bind:values={() => draft.country ? [draft.country] : [], values => {draft.country=values[0]??'';}} help="Countries supported by the search provider."/></div>
    <div class="form-group"><ChoiceField name="search-sites" label="Job sites" options={sites} bind:values={draft.sites} max={8} required disabled={busy||!ready} help="Choose one or more sites to search."/></div>
    <div class="form-group"><label for="search-age">Hours old</label><input id="search-age" type="number" bind:value={draft.hours_old} min="1" max="8760" required/></div>
    <div class="form-group"><label for="search-results">Results wanted</label><input id="search-results" type="number" bind:value={draft.results_wanted} min="1" max="1000" required/></div>
  {:else}<div class="form-group"><label for="source-board">Company board token</label><input id="source-board" bind:value={draft.board} required maxlength="80" pattern={'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}'}/><p class="field-help">For {boards.find(board=>board.value===draft.source)?.example}, enter example.</p></div>{/if}
  <div class="form-group"><label for="search-time">Daily run time (clear for manual only)</label><input id="search-time" type="time" bind:value={schedule}/></div>
  <div class="form-group"><ChoiceField name="search-zone" label="IANA timezone" options={timezoneOptions} max={1} required disabled={busy||!ready} bind:values={() => draft.timezone ? [draft.timezone] : [], values => {draft.timezone=values[0]??'';}} placeholder="Search cities or timezones…" help="A nonexistent DST time skips that day; repeated times run once."/></div>
  <details><summary>Model usage limits</summary><p class="field-help">Limit how much evaluation and generation each run can request.</p>
  <div class="form-group"><label for="search-jobs">Maximum model-reviewed jobs per run</label><input id="search-jobs" type="number" bind:value={draft.max_jobs} min="0" max="1000" required/></div>
  <div class="form-group"><label for="search-calls">Maximum model calls per run</label><input id="search-calls" type="number" bind:value={draft.max_calls} min="0" max="3000" required/></div>
  <div class="form-group"><label for="search-tokens">Maximum reserved model tokens per run</label><input id="search-tokens" type="number" bind:value={draft.max_tokens} min="0" max="100000000" required/><p class="field-help">Conservative request reservations cap admitted work, including retries and drafts. Unknown usage stays reserved. This is not a dollar billing guarantee.</p></div>
  </details>
  <div class="settings-save"><p role={error?'alert':'status'}>{message}</p><div><button type="button" class="subtle" onclick={()=>{if(!dirty||confirm('Discard the unsaved search draft and start a new search?'))edit();}}>New search</button><button type="button" class="subtle" disabled={busy||!dirty} onclick={()=>{const saved=JSON.parse(savedDraft);draft=saved.draft;schedule=saved.schedule;}}>Discard search changes</button><button class="primary" disabled={!ready||busy}>{busy?'Saving…':'Save search'}</button></div></div>
</fieldset></form>
</details>
<style>
  fieldset{border:0;padding:0;margin:0;min-width:0}
  .available-sources,.source-editor{border-bottom:1px solid var(--border);padding-bottom:12px;margin-bottom:12px}
  summary{font-weight:600;cursor:pointer;padding:12px 0;min-height:44px;overflow-wrap:anywhere}
  .available-sources h4{margin:20px 0 8px}.available-sources p{margin:8px 0 12px}.available-sources button{min-height:44px}
  .source-settings{scroll-margin-top:24px}.actions{display:flex;gap:8px;flex-wrap:wrap}p{overflow-wrap:anywhere}
  .source-message{color:var(--muted);font-size:13px}.source-message[role=alert]{color:var(--ink)}
  .source-settings .form-group{border:0;padding:12px 0}.source-settings h3{margin:24px 0 4px}.source-settings details{margin:20px 0}
</style>
