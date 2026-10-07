<script lang="ts">
  import {getContext,onMount} from 'svelte';import {Api} from '#lib/api.ts';
  let {disabled=false,searchId=''}=$props<{disabled?:boolean;searchId?:string}>();
  const api=getContext<Api>('api');
  type Run={id:string;search_id:string;name:string;stage:string;collected:number;evaluated:number;pending:number;review:number;rejected:number;recommended:number;evaluation_errors:number;source_error:string|null;evaluation_error_codes:string[];review_backlog:boolean;backlog:number;waiting_backlog:number;limits:{jobs:number;calls:number;tokens:number};usage:{calls:number;reserved_tokens:number;input_tokens:number|null;output_tokens:number|null}};
  let runs=$state<Run[]>([]);let busy=$state(false);let error=$state('');
  const run=$derived(runs.find(r=>!searchId||r.search_id===searchId)??null);
  const collecting=$derived(!!run&&['queued','collecting','fetched'].includes(run.stage));
  async function load(){try{runs=(await api.request<{runs:Run[]}>('/api/search-runs')).runs;error='';}catch(e){error=(e as Error).message;}}
  async function action(kind:string){busy=true;try{if(kind==='start'){const chosen=searchId||(await api.request<{searches:{id:string;paused:boolean}[]}>('/api/search-settings')).searches.find(s=>!s.paused)?.id;if(!chosen)throw Error('Save and resume a search in Settings first.');await api.request('/api/search-runs',{search_id:chosen});}else if(run)await api.request(`/api/search-runs/${run.id}/${kind}`,{});await load();}catch(e){error=(e as Error).message;}finally{busy=false;}}
  onMount(()=>{void load();const timer=setInterval(()=>{void load();},3000);const reconnect=()=>{void load();};window.addEventListener('online',reconnect);document.addEventListener('visibilitychange',reconnect);return()=>{clearInterval(timer);window.removeEventListener('online',reconnect);document.removeEventListener('visibilitychange',reconnect);};});
</script>
<section class="search-run" aria-label="Search run">
  <div class="run-header"><div><h3>{run?.name??'Search progress'}</h3><p>Full collection continues independently of model and delivery work.</p></div><button class="primary" disabled={disabled||busy||collecting} onclick={()=>action('start')}>{collecting?'Collecting…':busy?'Starting…':'Run now'}</button></div>
  {#if run}<div role="status"><p>Run status: {run.stage.replaceAll('_',' ')}.</p><p>{run.collected} collected · {run.evaluated} evaluated · {run.pending} pending · {run.review} need review · {run.recommended} recommended · {run.rejected} rejected · {run.evaluation_errors} evaluation errors</p><p>Model calls {run.usage.calls}/{run.limits.calls} · Reserved tokens {run.usage.reserved_tokens}/{run.limits.tokens} · Reported input/output {run.usage.input_tokens??'unknown'}/{run.usage.output_tokens??'unknown'}.</p></div>
    {#if run.waiting_backlog&&!run.review_backlog&&run.stage!=='cancelled'}<p>{run.waiting_backlog} backlog jobs await explicit review.</p><button class="secondary" disabled={busy} onclick={()=>action('review-backlog')}>Review backlog</button>{/if}
    {#if run.stage!=='cancelled'}<button class="subtle" disabled={busy} onclick={()=>action('cancel')}>Cancel remaining run work</button>{/if}
    {#if run.pending}<p class="field-help">Pending work resumes when the profile and model are ready, subject to this run's limits. Closing this page does not stop the worker.</p>{/if}
    {#if run.source_error}<p role="alert">Source error: {run.source_error}. Check source settings and retry Run. Observed jobs remain stored.</p>{/if}
    {#if run.evaluation_error_codes.length}<p role="alert">Model work needs attention: {run.evaluation_error_codes.join(', ')}. Check the model and run limits before retrying.</p>{/if}
  {/if}
  {#if error}<p role="alert">Progress disconnected: {error}. Reconnecting automatically.</p>{/if}
  {#if !searchId}<details><summary>Run history</summary>{#each runs as item(item.id)}<p>{item.name} · {item.stage.replaceAll('_',' ')} · {item.collected} collected</p>{/each}</details><p class="field-help">Manage searches in <a href="/settings/">Settings → Sources</a>.</p>{/if}
</section>
<style>.search-run{border-top:1px solid var(--border);margin-top:24px;padding-top:18px}.run-header{display:flex;align-items:center;gap:16px;justify-content:space-between}.run-header p{max-width:60ch}p{overflow-wrap:anywhere}@media(max-width:600px){.run-header{align-items:stretch;flex-direction:column}}</style>
