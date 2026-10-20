<script lang="ts">
  import {getContext,onMount} from 'svelte';
  import {Api} from '#lib/api.ts';
  const api=getContext<Api>('api');
  let {onrefresh}=$props<{onrefresh:()=>Promise<void>}>();
  type Status={pending:number;monitored:number;failed:number;unsupported:number;directory_checked_at:number|null;directory_error:string|null;stopped:boolean};
  let status=$state<Status|null>(null);
  let error=$state('');
  let refreshing=$state(false);
  onMount(()=>{
    let disposed=false;
    let timer:ReturnType<typeof setTimeout>;
    async function poll(){
      try {const result=await api.request<Status>('/api/source-discovery');if(!disposed){status=result;error='';}}
      catch(e){if(!disposed)error=(e as Error).message;}
      finally {if(!disposed)timer=setTimeout(poll,10000);}
    }
    void poll();
    return ()=>{disposed=true;clearTimeout(timer);};
  });
  async function refresh(){refreshing=true;try{await onrefresh();}finally{refreshing=false;}}
</script>
<section aria-labelledby="automatic-company-sources">
  <h3 id="automatic-company-sources">Automatic company discovery</h3>
  <p>Find company boards from the public directory and employer links in collected jobs. Working Greenhouse, Lever, and Ashby boards are added automatically and checked for jobs every day.</p>
  {#if status}
    <p>{status.stopped?'Paused while job ingestion is stopped.':'Discovering and checking new boards in the background.'} {status.monitored.toLocaleString()} boards validated · {status.pending.toLocaleString()} awaiting validation.</p>
    {#if status.failed}<p>{status.failed.toLocaleString()} unavailable boards will be retried automatically.</p>{/if}
    {#if status.directory_error}<p role="alert">{status.directory_error}</p>{/if}
  {:else if !error}<p>Loading discovery status…</p>{/if}
  {#if error}<p role="alert">{error} Retrying automatically.</p>{/if}
  <button class="secondary" disabled={refreshing} onclick={refresh}>{refreshing?'Refreshing…':'Refresh source list'}</button>
</section>
<style>
  section{border-bottom:1px solid var(--border);padding:16px 0;margin-bottom:16px}
  h3{font-size:14px;margin:0 0 8px}p{font-size:13px;color:var(--muted);line-height:1.6;overflow-wrap:anywhere}
  button{min-height:44px}
</style>
