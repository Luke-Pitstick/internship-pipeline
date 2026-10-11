<script lang="ts">
  import {getContext,onMount} from 'svelte';import {Api} from '#lib/api.ts';
  let {disabled=false,searchId=''}=$props<{disabled?:boolean;searchId?:string}>();
  const api=getContext<Api>('api');
  type Run={id:string;search_id:string;name:string;stage:string;collected:number;evaluated:number;pending:number;review:number;rejected:number;recommended:number;evaluation_errors:number;source_error:string|null;evaluation_error_codes:string[];review_backlog:boolean;backlog:number;waiting_backlog:number;limits:{jobs:number;calls:number;tokens:number};usage:{calls:number;reserved_tokens:number;input_tokens:number|null;output_tokens:number|null}};
  let runs=$state<Run[]>([]);let busy=$state(false);let error=$state('');let connectionError=$state('');
  const run=$derived(runs.find(r=>!searchId||r.search_id===searchId)??null);
  const collecting=$derived(!!run&&['queued','collecting','fetched'].includes(run.stage));
  async function load(){try{runs=(await api.request<{runs:Run[]}>('/api/search-runs')).runs;connectionError='';}catch(e){connectionError=(e as Error).message;}}
  async function action(kind:string){busy=true;error='';try{if(kind==='start'){const chosen=searchId||(await api.request<{searches:{id:string;paused:boolean}[]}>('/api/search-settings')).searches.find(s=>!s.paused)?.id;if(!chosen)throw Error('Save and resume a search in Settings first.');await api.request('/api/search-runs',{search_id:chosen});}else if(run)await api.request(`/api/search-runs/${run.id}/${kind}`,{});await load();}catch(e){error=(e as Error).message;}finally{busy=false;}}
  onMount(()=>{void load();const reconnect=()=>{if(!document.hidden)void load();};const timer=setInterval(reconnect,3000);window.addEventListener('online',reconnect);document.addEventListener('visibilitychange',reconnect);return()=>{clearInterval(timer);window.removeEventListener('online',reconnect);document.removeEventListener('visibilitychange',reconnect);};});
</script>
<section class="search-run" aria-label="Search run">
  <div class="run-header">
    <div class="run-summary">
      <h3><span class="status-dot" class:running={collecting} aria-hidden="true"></span>{run?.name ?? 'Discover opportunities'}</h3>
      {#if run}<p role="status"><span class="run-stage">Run status: {run.stage.replaceAll('_',' ')}.</span> <span>{run.collected.toLocaleString()} collected · {run.evaluated.toLocaleString()} evaluated · {run.pending.toLocaleString()} pending</span></p>
      {:else}<p>Run a saved search to collect new jobs.</p>{/if}
    </div>
    <div class="run-actions">
      {#if !searchId}<a class="small-button" href="/settings/#Sources">Manage sources</a>{/if}
      <button class="secondary" disabled={disabled||busy||collecting} onclick={()=>action('start')}>{collecting?'Collecting…':busy?'Working…':'Run now'}</button>
    </div>
  </div>
  {#if run?.source_error}<p class="error" role="alert">Source error: {run.source_error}. Check source settings and retry Run. Observed jobs remain stored.</p>{/if}
  {#if run?.evaluation_error_codes.length}<p class="error" role="alert">Model work needs attention: {run.evaluation_error_codes.join(', ')}. Check the model and run limits before retrying.</p>{/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if connectionError}<p class="error" role="alert">Progress disconnected: {connectionError}. Reconnecting automatically.</p>{/if}
  {#if run?.waiting_backlog&&!run.review_backlog&&run.stage!=='cancelled'}<div class="backlog-notice"><span>{run.waiting_backlog} backlog jobs await explicit review.</span><button class="small-button" disabled={busy} onclick={()=>action('review-backlog')}>Review backlog</button></div>{/if}
  {#if run || runs.length}<details class="run-details"><summary>Run details and history</summary>
    {#if run}
      <p>{run.review} need review · {run.recommended} recommended · {run.rejected} rejected · {run.evaluation_errors} evaluation errors</p>
      <p>Model calls {run.usage.calls}/{run.limits.calls} · Reserved tokens {run.usage.reserved_tokens}/{run.limits.tokens} · Reported input/output {run.usage.input_tokens??'unknown'}/{run.usage.output_tokens??'unknown'}.</p>
      {#if run.pending}<p class="field-help">Pending work resumes when the profile and model are ready, subject to this run's limits. Closing this page does not stop the worker.</p>{/if}
      {#if run.stage!=='cancelled'}<button class="subtle" disabled={busy} onclick={()=>action('cancel')}>Cancel remaining run work</button>{/if}
    {/if}
    {#if !searchId}<h4>Run history</h4>{#each runs as item(item.id)}<p>{item.name} · {item.stage.replaceAll('_',' ')} · {item.collected} collected</p>{/each}{/if}
  </details>{/if}
</section>
<style>
  .search-run {border-block:1px solid var(--border);margin:0 0 20px;padding:16px 0;font-size:13px}
  .run-header,.run-actions,.backlog-notice {display:flex;align-items:center;gap:12px;justify-content:space-between}
  .run-summary {min-width:0}.run-summary h3 {display:flex;align-items:center;gap:8px;font-size:14px;margin:0 0 6px}.status-dot {flex-shrink:0}
  p {overflow-wrap:anywhere;margin:8px 0;color:var(--muted)}.run-summary p {margin:0}.run-summary p span {margin-left:6px}
  .run-actions {flex-shrink:0;justify-content:flex-start;flex-wrap:wrap}
  .backlog-notice {justify-content:flex-start;flex-wrap:wrap;margin-top:12px;color:var(--muted)}
  .run-details {margin-top:10px}.run-details h4 {margin:18px 0 8px}.run-details .subtle {margin-top:12px}
  @media(max-width:600px){.run-header{align-items:flex-start;flex-direction:column}.run-summary p span{display:block;margin:5px 0 0}.run-actions{width:100%}.run-actions>*{flex:1}}
</style>
