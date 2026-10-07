<script lang="ts">
import {getContext,onMount} from 'svelte';import {Api} from '#lib/api.ts';
const api=getContext<Api>('api');
type Data={workers:{healthy:boolean;roles:string[];at:number|null};sources:{id:string;provider:string;age_seconds:number|null;last_success:number|null;healthy:boolean;error:string|null}[];queue:{kind:string;status:string;count:number}[];activity:{kind:string;running:number;oldest_update:number;lease_until:number}[];failed:{id:number;kind:string;attempts:number;error:string;retryable:boolean}[];models:{operation:string;status:string;count:number}[];logs:{at:number;kind:string;message:string}[]};
let data=$state<Data|null>(null);let error=$state('');let busy=$state(false);
async function load(){try{data=await api.request<Data>('/api/diagnostics');error='';}catch(e){error=(e as Error).message;}}
async function retry(id:number){busy=true;try{data=await api.request<Data>(`/api/diagnostics/${id}/retry`,{});error='';}catch(e){error=(e as Error).message;}finally{busy=false;}}
onMount(()=>{void load();const timer=setInterval(()=>{void load();},5000);return()=>clearInterval(timer);});
</script>
<p class="form-intro">Inspect persisted work and source freshness. Diagnostic messages exclude raw provider responses, private paths and credentials.</p>
{#if data}
<h3>Workers</h3><p>{data.workers.healthy?'Supervisor active.':'Supervisor heartbeat unavailable or stale; check the local service.'} {data.workers.roles.join(', ')}</p>
<h3>Active work</h3>{#each data.activity as item}<p>{item.kind} · {item.running} running · Last activity {new Date(item.oldest_update*1000).toLocaleString()} · Lease expires {new Date(item.lease_until*1000).toLocaleString()}</p>{/each}
<h3>Source freshness</h3>{#each data.sources as source}<p>{source.id} · {source.provider} · Last success {source.last_success?new Date(source.last_success*1000).toLocaleString():'Never'} · {source.healthy?'Healthy':source.error}. {source.age_seconds===null?'':`${Math.floor(source.age_seconds/60)} minutes old.`}</p>{/each}
<h3>Queue</h3>{#each data.queue as item}<p>{item.kind} · {item.status} · {item.count}</p>{/each}
<h3>Model attempts</h3>{#each data.models as item}<p>{item.operation} · {item.status} · {item.count}</p>{/each}
<h3>Failed work</h3>{#each data.failed as item}<div><p>Task {item.id} · {item.kind} · {item.attempts} attempts · {item.error}</p>{#if item.retryable}<button class="secondary" disabled={busy} onclick={()=>retry(item.id)}>Retry task {item.id}</button>{:else}<p>Inspect the integration's delivery state before deliberately retrying.</p>{/if}</div>{/each}
<details><summary>Sanitized diagnostic log</summary>{#each data.logs as log}<p>{new Date(log.at*1000).toLocaleString()} · {log.kind} · {log.message}</p>{/each}</details>
<h3>Backup and owner recovery</h3><p>Stop the application, then use the local backup command to capture both databases, documents, settings and encryption key. Restore into a new directory and sign in with the saved owner account. Local owner recovery revokes existing sessions; the web application has no recovery bypass.</p>
{/if}
{#if error}<p role="alert">{error}</p>{/if}
<style>p{overflow-wrap:anywhere}</style>
