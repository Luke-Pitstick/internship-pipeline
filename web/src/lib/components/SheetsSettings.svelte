<script lang="ts">
  import {getContext,onMount} from 'svelte';
  import {Api} from '#lib/api.ts';
  const api=getContext<Api>('api');
  type Config={spreadsheet_id:string;tab:string;mapping:Record<string,string>;inward_status:string|null;inward_notes:string|null;enabled:boolean;interval_minutes:number};
  type Inward={id:string;job_id:string;field:string;local_value:string;remote_value:string};
  type Summary={revision:number;config:Config|null;tested:boolean;fields:string[];runs:{id:string;state:string;error:string|null}[];inward:Inward[]};
  type Plan={id:string;rows:number;conflicts:{job_id:string;reason:string}[];changes:{job_id:string;row:number;new:boolean;desired:Record<string,string|number>}[];message:string;truncated:boolean};
  const fields=['job_id','company','title','location','score','posted_at','first_observed_at','deadline','apply_url','source_status'];
  const columns=Array.from({length:52},(_,i)=>i<26?String.fromCharCode(65+i):'A'+String.fromCharCode(65+i-26));
  let data=$state<Summary>({revision:0,config:null,tested:false,fields,runs:[],inward:[]});
  const blank=():Config=>({spreadsheet_id:'',tab:'',mapping:Object.fromEntries(fields.map((f,i)=>[f,columns[i]])),inward_status:null,inward_notes:null,enabled:false,interval_minutes:60});
  let draft=$state<Config>(blank());
  let credential=$state('');
  let {ondirty=()=>{}}=$props<{ondirty?:(value:boolean)=>void}>();
  let draftRevision=$state(0);
  let savedDraft=$state('');
  const dirty=$derived(!!credential||(!!savedDraft&&JSON.stringify(draft)!==savedDraft));
  $effect(()=>{ondirty(dirty);});
  let tabs=$state<string[]>([]);let title=$state('');let feedback=$state('');let busy=$state(false);let ready=$state(false);let plan=$state<Plan|null>(null);
  async function load(){try{data=await api.request<Summary>('/api/sheets');draft=data.config?structuredClone($state.snapshot(data.config)):blank();draftRevision=data.revision;savedDraft=JSON.stringify(draft);credential='';plan=null;ready=true;}catch(e){feedback=(e as Error).message;}}
  async function action(kind:string,id=''){busy=true;try{
    if(kind==='save'){const secret=credential;credential='';data=await api.request<Summary>('/api/sheets/save',{...draft,expected_revision:draftRevision,...(secret?{service_account:secret}:{})});draftRevision=data.revision;savedDraft=JSON.stringify(draft);plan=null;feedback='Sheets connection saved. Test current access before previewing.';}
    if(kind==='test'){const result=await api.request<{title:string;tabs:string[];message:string}>('/api/sheets/test',{expected_revision:draftRevision});tabs=result.tabs;title=result.title;data=await api.request<Summary>('/api/sheets');feedback=result.message;}
    if(kind==='preview'){plan=await api.request<Plan>('/api/sheets/preview',{expected_revision:draftRevision});feedback=plan.message;}
    if(kind==='sync'){data=await api.request<Summary>(`/api/sheets/${plan?.id}/sync`,{});plan=null;feedback='Sync queued. Review status and inward proposals below.';}
    if(kind==='remove'){data=await api.request<Summary>('/api/sheets/remove',{expected_revision:draftRevision});await load();credential='';plan=null;feedback='Google connection disconnected and encrypted credential removed.';}
    if(kind==='accept'||kind==='ignore'){data=await api.request<Summary>(`/api/sheets/inward/${id}/review`,{accept:kind==='accept'});feedback=kind==='accept'?'Reviewed spreadsheet change applied to this workspace.':'Spreadsheet proposal ignored.';}
  }catch(e){feedback=(e as Error).message;}finally{busy=false;}}
  onMount(()=>{void load();const timer=setInterval(()=>{void api.request<Summary>('/api/sheets').then(r=>data=r).catch(()=>{});},3000);return()=>clearInterval(timer);});
</script>
<section><h3>Google Sheets</h3><p class="field-help">Optional: use a Google Cloud service account, enable the Sheets API and share one spreadsheet with its email as Editor. Paste its JSON key here; the server encrypts it and never returns it. No domain delegation or personal Google login is required.</p>
<p><a href="https://developers.google.com/identity/protocols/oauth2/service-account" target="_blank" rel="noreferrer">Service-account setup documentation</a> · <a href="/api/sheets/export.csv" download>Download opportunities CSV</a></p>
<form onsubmit={e=>{e.preventDefault();void action('save');}}><fieldset disabled={busy||!ready}>
<label class="form-group">Spreadsheet ID<input bind:value={draft.spreadsheet_id} required placeholder="ID from the spreadsheet URL" /></label>
<label class="form-group">Google service-account JSON key<textarea bind:value={credential} rows="4" spellcheck="false" autocomplete="off" placeholder={data.revision?'Leave empty to keep the encrypted saved key':'Paste the downloaded service-account JSON'}></textarea></label>
<label class="form-group">Destination tab<select bind:value={draft.tab}><option value="">Test access to list tabs</option>{#if draft.tab&&!tabs.includes(draft.tab)}<option value={draft.tab}>{draft.tab}</option>{/if}{#each tabs as tab}<option value={tab}>{tab}</option>{/each}</select></label>
{#if title}<p>Selected spreadsheet: {title}</p>{/if}
<p class="field-help">Row 1 is your header. Application-owned facts go only to the mapped columns below, up to 10,000 rows and columns A–AZ. Put formulas and manual notes in other columns. Existing cells that differ from the last written values require review; remap occupied columns before syncing.</p>
<div class="mapping">{#each fields as field}<label class="form-group">{field.replaceAll('_',' ')} outward column<select value={draft.mapping[field]??''} onchange={e=>{const value=e.currentTarget.value;if(value)draft.mapping[field]=value;else delete draft.mapping[field];}}><option value="" disabled={field==='job_id'}>Do not sync</option>{#each columns as c}<option value={c}>{c}</option>{/each}</select></label>{/each}</div>
<label class="form-group">Inward application status column<select bind:value={draft.inward_status}><option value={null}>Disabled</option>{#each columns as c}<option value={c}>{c}</option>{/each}</select></label>
<label class="form-group">Inward notes column<select bind:value={draft.inward_notes}><option value={null}>Disabled</option>{#each columns as c}<option value={c}>{c}</option>{/each}</select></label>
<p class="field-help">Optional inward columns are preserved in Google. Only applied / not_applied and notes become proposals; every change needs your review before modifying the workspace. Accepting applied records an explicit owner decision, never a submission.</p>
<label class="toggle-label"><input type="checkbox" bind:checked={draft.enabled} />Enable scheduled spreadsheet sync</label>
<label class="form-group">Sync interval in minutes<input type="number" min="5" max="10080" bind:value={draft.interval_minutes} /></label>
<button class="primary" type="submit">Save Sheets connection</button> <button class="secondary" type="button" disabled={!data.revision} onclick={()=>action('test')}>Test spreadsheet access</button>
</fieldset></form><p role="status">{feedback}</p>
<div class="actions"><button class="secondary" disabled={busy||!data.tested||!draft.tab} onclick={()=>action('preview')}>Preview spreadsheet sync</button><button class="subtle" disabled={busy} onclick={()=>{if(!dirty||confirm('Discard the unsaved Sheets draft and reload saved settings?'))void load();}}>Reload Sheets settings</button><button class="subtle" disabled={busy||!data.revision} onclick={()=>{if(confirm('Disconnect Google and cancel queued syncs? Existing spreadsheet cells stay in Google.'))void action('remove');}}>Disconnect Google</button></div>
{#if plan}<div class="preview"><h4>Dry-run preview</h4><p>{plan.rows} job rows planned. {plan.truncated?'Showing the first 30 rows.':''}</p>{#each plan.conflicts as c}<p class="error">{c.job_id}: {c.reason}</p>{/each}<ul>{#each plan.changes as change}<li>Row {change.row} · {change.new?'New stable job ID':'Update stable job ID'} · {change.job_id}<dl>{#each Object.entries(change.desired) as [column,value]}<div><dt>Column {column}</dt><dd>{value}</dd></div>{/each}</dl></li>{/each}</ul><button class="primary" disabled={busy||!!plan.conflicts.length} onclick={()=>action('sync')}>Sync previewed records</button></div>{/if}
<h4>Sync status</h4><ul>{#each data.runs as run}<li>{run.state}{run.error?` · ${run.error}`:''}</li>{/each}</ul>
<h4>Review spreadsheet changes</h4>{#if !data.inward.length}<p class="field-help">No inward changes need review.</p>{/if}{#each data.inward as change}<div class="preview"><p>{change.job_id} · {change.field}</p><p>Workspace: {change.local_value||'(empty)'}</p><p>Spreadsheet: {change.remote_value}</p><button class="secondary" disabled={busy} onclick={()=>action('accept',change.id)}>Accept spreadsheet change</button> <button class="subtle" disabled={busy} onclick={()=>action('ignore',change.id)}>Ignore spreadsheet change</button></div>{/each}
<p class="field-help">Sync re-reads mapped cells before each row, checkpoints verified rows and resumes partial failures by stable job ID. Google offers no conditional cell writes: avoid editing app-owned mapped columns while a sync is in flight. Unrelated columns are never written. Revoked credentials or conflicts stop this integration while searches keep running.</p>
</section><style>section{margin-top:36px;border-top:1px solid var(--border);padding-top:24px;overflow-wrap:anywhere}fieldset{border:0;padding:0;min-width:0}.mapping{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.toggle-label{display:flex;gap:10px;margin:16px 0}.actions{display:flex;gap:8px;flex-wrap:wrap}.preview{padding:16px;border:1px solid var(--border);margin:16px 0;max-height:500px;overflow:auto}ul{padding-left:20px}dl{font-size:12px}dl div{display:flex;gap:10px}dt{min-width:70px}dd{margin:0;overflow-wrap:anywhere;min-width:0}.error{color:#a83424}@media(max-width:600px){.mapping{grid-template-columns:1fr}}</style>
