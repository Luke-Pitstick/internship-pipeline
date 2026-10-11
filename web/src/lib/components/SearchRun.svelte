<script lang="ts">
  import {getContext,onMount} from 'svelte';import {Api} from '#lib/api.ts';
  let {disabled=false,searchId=''}=$props<{disabled?:boolean;searchId?:string}>();
  const api=getContext<Api>('api');
  type Run={id:string;search_id:string;name:string;stage:string;collected:number;evaluated:number;pending:number;review:number;rejected:number;recommended:number;evaluation_errors:number;excluded:number;source_error:string|null;evaluation_error_codes:string[];limits:{jobs:number;calls:number;tokens:number};usage:{calls:number;reserved_tokens:number;input_tokens:number|null;output_tokens:number|null}};
  type Summary={collected:number;evaluated:number;pending:number;evaluation_errors:number;excluded:number;sources:number;next_run:number|null;queued:number;collecting:number;fetched:number;scoring_resumes_at:number|null};
  let summary=$state<Summary|null>(null);
  let runs=$state<Run[]>([]);let busy=$state(false);let error=$state('');let connectionError=$state('');
  const run=$derived(runs.find(r=>!searchId||r.search_id===searchId)??null);
  const collecting=$derived(searchId ? !!run&&['queued','collecting','fetched'].includes(run.stage) : !!summary&&(summary.queued+summary.collecting+summary.fetched)>0);
  async function load(){try{const data=await api.request<{runs:Run[];summary:Summary}>(`/api/search-runs${searchId?`?search_id=${searchId}`:''}`);runs=data.runs;summary=data.summary;connectionError='';}catch(e){connectionError=(e as Error).message;}}
  async function action(kind:string){busy=true;error='';try{if(kind==='start'){
    const sources=searchId?[{id:searchId,paused:false}]:(await api.request<{searches:{id:string;paused:boolean}[]}>('/api/search-settings')).searches;
    const active=sources.filter(s=>!s.paused);
    if(!active.length)throw Error('Resume a source in Settings to collect jobs.');
    await Promise.all(active.map(s=>api.request('/api/search-runs',{search_id:s.id})));
  }else if(run)await api.request(`/api/search-runs/${run.id}/${kind}`,{});await load();}catch(e){error=(e as Error).message;}finally{busy=false;}}
  onMount(()=>{void load();const reconnect=()=>{if(!document.hidden)void load();};const timer=setInterval(reconnect,3000);window.addEventListener('online',reconnect);document.addEventListener('visibilitychange',reconnect);return()=>{clearInterval(timer);window.removeEventListener('online',reconnect);document.removeEventListener('visibilitychange',reconnect);};});
</script>
<section class="search-run" aria-label="Search run">
  <div class="run-header">
    <div class="run-summary">
      <h3><span class="status-dot" class:running={collecting} aria-hidden="true"></span>{searchId ? run?.name ?? 'Discover opportunities' : 'Automatic job discovery'}</h3>
      {#if !searchId && summary}<p role="status">{summary.collected.toLocaleString()} internships · {summary.evaluated.toLocaleString()} evaluated · {summary.pending.toLocaleString()} awaiting scoring</p>
        <p>{summary.collecting} collecting · {summary.queued} queued · {summary.sources} active sources{summary.next_run ? ` · Next automatic search ${new Date(summary.next_run*1000).toLocaleString()}` : ''}</p>
      {:else if run}<p role="status"><span class="run-stage">Run status: {run.stage.replaceAll('_',' ')}.</span> <span>{run.collected.toLocaleString()} collected · {run.evaluated.toLocaleString()} evaluated · {run.pending.toLocaleString()} pending</span></p>
      {:else}<p>Collection starts automatically when this source is scheduled.</p>{/if}
    </div>
    <div class="run-actions">
      {#if !searchId}<a class="small-button" href="/settings/#Sources">Manage sources</a>{/if}
      <button class="secondary" disabled={disabled||busy||collecting} onclick={()=>action('start')}>{collecting?'Collecting…':busy?'Working…':searchId?'Run now':'Refresh searches'}</button>
    </div>
  </div>
  {#if summary?.excluded && !searchId}<p>{summary.excluded} other listings excluded from internship discovery.</p>{/if}
  {#if summary?.scoring_resumes_at && !searchId}<p role="status">Scoring has reached its current model budget and resumes automatically at {new Date(summary.scoring_resumes_at*1000).toLocaleString()}.</p>{/if}
  {#if summary?.evaluation_errors && !searchId}<p>{summary.evaluation_errors} jobs need evaluation attention. Open a job to see its source or model error.</p>{/if}
  {#if run?.source_error && searchId}<p class="error" role="alert">Source error: {run.source_error}. This source will retry on its next schedule. Observed jobs remain stored.</p>{/if}
  {#if searchId && run?.evaluation_error_codes.length}<p class="error" role="alert">Model work needs attention: {run.evaluation_error_codes.join(', ')}. Check the model and run limits before retrying.</p>{/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if connectionError}<p class="error" role="alert">Progress disconnected: {connectionError}. Reconnecting automatically.</p>{/if}
  {#if run || runs.length}<details class="run-details"><summary>Run details and history</summary>
    {#if run}
      {#if run.excluded}<p>{run.excluded} listings excluded because they do not identify an internship or co-op role.</p>{/if}
      <p>{run.review} need review · {run.recommended} recommended · {run.rejected} rejected · {run.evaluation_errors} evaluation errors</p>
      <p>Model calls {run.usage.calls}/{run.limits.calls} · Reserved tokens {run.usage.reserved_tokens}/{run.limits.tokens} · Reported input/output {run.usage.input_tokens??'unknown'}/{run.usage.output_tokens??'unknown'}.</p>
      {#if run.pending}<p class="field-help">Pending work resumes when the profile and model are ready, subject to this run's limits. Closing this page does not stop the worker.</p>{/if}
      {#if run.stage!=='cancelled'}<button class="subtle" disabled={busy} onclick={()=>action('cancel')}>Cancel remaining run work</button>{/if}
    {/if}
    {#if !searchId}<h4>Run history</h4>{#each runs as item(item.id)}<p>{item.name} · {item.stage.replaceAll('_',' ')} · {item.collected} collected · {item.evaluated} evaluated{item.source_error ? ` · ${item.source_error}` : ''}</p>{/each}{/if}
  </details>{/if}
</section>
<style>
  .search-run {border-block:1px solid var(--border);margin:0 0 20px;padding:16px 0;font-size:13px}
  .run-header,.run-actions {display:flex;align-items:center;gap:12px;justify-content:space-between}
  .run-summary {min-width:0}.run-summary h3 {display:flex;align-items:center;gap:8px;font-size:14px;margin:0 0 6px}.status-dot {flex-shrink:0}
  p {overflow-wrap:anywhere;margin:8px 0;color:var(--muted)}.run-summary p {margin:0}.run-summary p span {margin-left:6px}
  .run-actions {flex-shrink:0;justify-content:flex-start;flex-wrap:wrap}
  .run-details {margin-top:10px}.run-details h4 {margin:18px 0 8px}.run-details .subtle {margin-top:12px}
  @media(max-width:600px){.run-header{align-items:flex-start;flex-direction:column}.run-summary p span{display:block;margin:5px 0 0}.run-actions{width:100%}.run-actions>*{flex:1}}
</style>
