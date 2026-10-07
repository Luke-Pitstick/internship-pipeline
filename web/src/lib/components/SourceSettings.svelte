<script lang="ts">
  import {getContext,onMount} from 'svelte';
  import {Api} from '#lib/api.ts';
  import SearchRun from '#lib/components/SearchRun.svelte';
  const api=getContext<Api>('api');
  let {allowRun=true}=$props<{allowRun?:boolean}>();
  type Search={id:string;revision:number;name:string;source:string;board:string;search_term:string;location:string;country:string;sites:string[];hours_old:number;results_wanted:number;daily_at:string|null;timezone:string;max_jobs:number;max_calls:number;max_tokens:number;paused:boolean;next_run:number|null;last_success:number|null};
  const blank=()=>({id:'',revision:0,name:'',source:'greenhouse',board:'',search_term:'',location:'',country:'USA',sites:['indeed'],hours_old:72,results_wanted:100,daily_at:null as string|null,timezone:'UTC',max_jobs:20,max_calls:30,max_tokens:5000000,paused:false,next_run:null,last_success:null});
  let searches=$state<Search[]>([]); let draft=$state<Search>(blank());
  let ready=$state(false);let busy=$state(false);let error=$state(false);let message=$state('Loading searches…');
  let schedule=$state('');let site=$state('indeed');
  function edit(s?:Search){draft=s?structuredClone($state.snapshot(s)):blank();schedule=draft.daily_at??'';site=draft.sites.join(',');}
  async function load(){try{searches=(await api.request<{searches:Search[]}>('/api/search-settings')).searches;ready=true;error=false;message='Saved searches are ready.';}catch(e){error=true;message=(e as Error).message;}}
  async function save(){busy=true;try{const {id,revision,paused,next_run,last_success,...config}=draft;const body={...config,id:id||null,expected_revision:revision,daily_at:schedule||null,sites:site.split(',').map(s=>s.trim()).filter(Boolean)};if(body.source==='jobspy')body.board='';else body.search_term='';searches=(await api.request<{searches:Search[]}>('/api/search-settings',body)).searches;edit();error=false;message='Search saved. Running work keeps its original settings.';}catch(e){error=true;message=(e as Error).message;}finally{busy=false;}}
  async function action(s:Search,kind:string){busy=true;try{searches=(await api.request<{searches:Search[]}>(`/api/search-settings/${s.id}/${kind}`,{expected_revision:s.revision,...(kind==='pause'?{paused:!s.paused}:{})})).searches;error=false;message=kind==='delete'?'Search removed; history is retained.':s.paused?'Search resumed.':'Search paused; existing work continues until cancelled.';}catch(e){error=true;message=(e as Error).message;}finally{busy=false;}}
  const date=(n:number|null)=>n?new Date(n*1000).toLocaleString():'None';
  onMount(()=>{void load();});
</script>
<p class="form-intro">Save company boards or broad searches. Collection runs without model or notification readiness. Daily schedules use the chosen timezone.</p>
{#each searches as s(s.id)}
  <section class="saved-search" aria-label={s.name}><h3>{s.name}</h3><p>{s.source} · {s.paused?'Paused':'Active'} · Last success {date(s.last_success)} · Next run {date(s.next_run)}</p>
    <div class="actions"><button class="secondary" onclick={()=>edit(s)} disabled={busy}>Edit {s.name}</button><button class="secondary" onclick={()=>action(s,'pause')} disabled={busy}>{s.paused?'Resume':'Pause'} {s.name}</button><button class="subtle" onclick={()=>action(s,'delete')} disabled={busy}>Delete {s.name}</button></div>
    {#if allowRun}<SearchRun searchId={s.id} disabled={s.paused||busy} />{/if}
  </section>
{/each}
<form onsubmit={e=>{e.preventDefault();void save();}}>
  <h3>{draft.id?'Edit search':'Add a saved search'}</h3>
  <div class="form-group"><label for="source-name">Search name</label><input id="source-name" bind:value={draft.name} required maxlength="120" disabled={!ready||busy}/></div>
  <div class="form-group"><label for="source-type">Source</label><select id="source-type" bind:value={draft.source}><option value="greenhouse">Greenhouse company board</option><option value="lever">Lever company board</option><option value="ashby">Ashby company board</option><option value="jobspy">JobSpy broad search</option></select></div>
  {#if draft.source==='jobspy'}
    <div class="form-group"><label for="search-term">Search term</label><input id="search-term" bind:value={draft.search_term} required maxlength="200"/></div>
    <div class="form-group"><label for="search-location">Location</label><input id="search-location" bind:value={draft.location} maxlength="200"/></div>
    <div class="form-group"><label for="search-country">Country</label><input id="search-country" bind:value={draft.country} required maxlength="80"/></div>
    <div class="form-group"><label for="search-sites">Sites, comma separated</label><input id="search-sites" bind:value={site} required/><p class="field-help">indeed, linkedin, zip_recruiter, glassdoor, google, bayt, naukri, bdjobs</p></div>
    <div class="form-group"><label for="search-age">Hours old</label><input id="search-age" type="number" bind:value={draft.hours_old} min="1" max="8760" required/></div>
    <div class="form-group"><label for="search-results">Results wanted</label><input id="search-results" type="number" bind:value={draft.results_wanted} min="1" max="1000" required/></div>
  {:else}<div class="form-group"><label for="source-board">Company board token</label><input id="source-board" bind:value={draft.board} required maxlength="80" pattern={'[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}'}/><p class="field-help">Enter the token after the source hostname, such as example.</p></div>{/if}
  <div class="form-group"><label for="search-time">Daily run time (optional)</label><input id="search-time" type="time" bind:value={schedule}/></div>
  <div class="form-group"><label for="search-zone">IANA timezone</label><input id="search-zone" bind:value={draft.timezone} required/><p class="field-help">For example America/Denver. A nonexistent DST time skips that day; repeated times run once.</p></div>
  <div class="form-group"><label for="search-jobs">Maximum model-reviewed jobs per run</label><input id="search-jobs" type="number" bind:value={draft.max_jobs} min="0" max="1000" required/></div>
  <div class="form-group"><label for="search-calls">Maximum model calls per run</label><input id="search-calls" type="number" bind:value={draft.max_calls} min="0" max="3000" required/></div>
  <div class="form-group"><label for="search-tokens">Maximum reserved model tokens per run</label><input id="search-tokens" type="number" bind:value={draft.max_tokens} min="0" max="100000000" required/><p class="field-help">Conservative request reservations cap admitted work, including retries and drafts. Unknown usage stays reserved. This is not a dollar billing guarantee.</p></div>
  <div class="settings-save"><p role={error?'alert':'status'}>{message}</p><div><button type="button" class="subtle" onclick={()=>edit()}>New search</button><button class="primary" disabled={!ready||busy}>{busy?'Saving…':'Save search'}</button></div></div>
</form>
<style>.saved-search{border-bottom:1px solid var(--border);padding-bottom:20px;margin-bottom:20px}.actions{display:flex;gap:8px;flex-wrap:wrap}p{overflow-wrap:anywhere}</style>
