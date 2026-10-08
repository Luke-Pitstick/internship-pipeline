<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import { Api } from '#lib/api.ts';
  const api = getContext<Api>('api');
  type Config = {host:string;port:number;username:string;sender:string;recipient:string;security:string;enabled:boolean;mode:string;minimum_score:number;digest_hour:number;timezone:string;attach_pdf:boolean};
  type Summary = {revision:number;config:Config|null;deliveries:{id:string;status:string;created:number;error:string|null}[]};
  let data = $state<Summary>({revision:0,config:null,deliveries:[]});
  const blank = ():Config => ({host:'',port:587,username:'',sender:'',recipient:'',security:'starttls',enabled:false,mode:'alerts',minimum_score:70,digest_hour:9,timezone:'UTC',attach_pdf:false});
  let draft = $state<Config>(blank());
  let password = $state('');
  let { ondirty = () => {} } = $props<{ondirty?: (value: boolean) => void}>();
  let draftRevision = $state(0);
  let savedDraft = $state('');
  const dirty = $derived(!!password || (!!savedDraft && JSON.stringify(draft) !== savedDraft));
  $effect(() => { ondirty(dirty); });
   let feedback = $state(''); let busy = $state(false);let ready=$state(false);
  async function load() { try {data = await api.request<Summary>('/api/email'); draft = data.config ? {...data.config} : blank(); draftRevision=data.revision; savedDraft=JSON.stringify(draft); password='';ready=true;} catch(e) {feedback=(e as Error).message;} }
  async function action(kind:string, id='') {busy=true; try {
    if(kind==='save') {const secret=password;password='';data = await api.request<Summary>('/api/email/save',{...draft,expected_revision:draftRevision,...(secret?{password:secret}:{})});draftRevision=data.revision;savedDraft=JSON.stringify(draft); feedback='Email settings saved.';}
    else if(kind==='test') {const r=await api.request<{message:string}>('/api/email/test',{expected_revision:draftRevision});feedback=r.message;data=await api.request<Summary>('/api/email');}
    else {data=await api.request<Summary>(`/api/email/${id}/retry`,{});feedback='Retry queued; the remote recipient may receive a duplicate.';}
  } catch(e) {feedback=(e as Error).message;} finally {busy=false;} }
  onMount(()=>{void load();const timer=setInterval(()=>{void api.request<Summary>('/api/email').then(r=>data=r).catch(()=>{});},3000);return()=>clearInterval(timer);});
</script>
<section><h3>Email alerts</h3><p class="field-help">Connect an SMTP mailbox using TLS. Alerts need no résumé. A test sends a synthetic message to your saved recipient.</p>
<form onsubmit={e=>{e.preventDefault();void action('save');}}><fieldset disabled={busy||!ready}>
<div class="form-grid">
<label class="form-group">SMTP host<input bind:value={draft.host} required placeholder="smtp.example.com" /></label>
<label class="form-group">Port<input type="number" bind:value={draft.port} min="1" max="65535" /></label>
<label class="form-group">Username<input bind:value={draft.username} autocomplete="off" required /></label>
<label class="form-group">Password<input type="password" bind:value={password} autocomplete="new-password" placeholder={data.revision?'Leave blank to keep saved password':''} /></label>
<label class="form-group">Sender email<input type="email" bind:value={draft.sender} required /></label>
<label class="form-group">Recipient email<input type="email" bind:value={draft.recipient} required /></label>
<label class="form-group">TLS mode<select bind:value={draft.security}><option value="starttls">STARTTLS (usually 587)</option><option value="ssl">TLS (usually 465)</option></select></label>
<label class="form-group">Delivery mode<select bind:value={draft.mode}><option value="alerts">Individual qualifying jobs</option><option value="digest">Daily digest</option></select></label>
<label class="form-group">Minimum fit score<input type="number" bind:value={draft.minimum_score} min="0" max="100" /></label>
<label class="form-group">Timezone<input bind:value={draft.timezone} placeholder="America/Denver" /></label>
<label class="form-group">Digest hour (0–23)<input type="number" bind:value={draft.digest_hour} min="0" max="23" /></label>
</div><label class="toggle-label"><input type="checkbox" bind:checked={draft.enabled} />Enable automatic email delivery</label>
<label class="toggle-label"><input type="checkbox" bind:checked={draft.attach_pdf} />Attach available current PDFs (up to ten per message)</label>
<button class="primary" type="submit">Save email settings</button> <button class="secondary" type="button" disabled={!data.revision} onclick={()=>action('test')}>Send test email</button>
</fieldset></form><p role="status">{feedback}</p><button class="subtle" disabled={busy} onclick={()=>{if(!dirty||confirm('Discard the unsaved email draft and reload saved settings?'))void load();}}>Reload email settings</button>
<p class="field-help">Only current recommended assessments above the threshold qualify. Accepted means the transport acknowledged the message. An interrupted or uncertain send needs review; deliberate retries can duplicate mail. Disabling cancels queued deliveries; an in-flight send may finish.</p>
<ul>{#each data.deliveries as d}<li>{new Date(d.created*1000).toLocaleString()} · {d.status}{d.error?` · ${d.error}`:''}{#if d.status==='uncertain'||d.status==='failed'} <button class="subtle" disabled={busy} onclick={()=>{if(confirm('Retry this delivery? If remote acceptance was uncertain, this may send a duplicate.'))void action('retry',d.id);}}>Retry delivery</button>{/if}</li>{/each}</ul>
</section><style>fieldset{border:0;padding:0;min-width:0}.toggle-label{display:flex;gap:10px;margin:16px 0}ul{padding-left:20px;overflow-wrap:anywhere}</style>
