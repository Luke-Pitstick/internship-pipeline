<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import { Api } from '#lib/api.ts';
  import ChatGPTConnection from '#lib/components/ChatGPTConnection.svelte';
  import ApiModelPicker from '#lib/components/ApiModelPicker.svelte';
  import { generalProviders, endpoints, modelConnections, type ModelConfig, type ModelConnections, type ModelKind } from '#lib/model-connections.ts';
  let {ondirty=()=>{}}=$props<{ondirty?:(value:boolean)=>void}>();
  const client = modelConnections(getContext<Api>('api'));
  const kinds: ModelKind[] = ['jev', 'general'];
  const labels = {jev: 'Jev', general: 'General LLM'};
  let connections = $state<ModelConnections | null>(null);
  let drafts = $state<Record<ModelKind, ModelConfig>>({
    jev: {model: 'jev-1.13.0', endpoint: endpoints.jev, timeout_seconds: 30, max_output_tokens: 1024},
    general: {model: '', endpoint: endpoints.general, timeout_seconds: 30, max_output_tokens: 1024}
  });
  let savedDrafts = $state({jev:'',general:''});
  let draftRevisions = $state({jev:0,general:0});
  let keys = $state({jev: '', general: ''});
  let busy = $state<ModelKind | null>(null);
  let loading = $state(false);
  let message = $state('');
  let error = $state('');
  let confirmRemove = $state<ModelKind | null>(null);
  function dirty(kind: ModelKind) {
    return !!keys[kind] || (!!savedDrafts[kind] && JSON.stringify(drafts[kind]) !== savedDrafts[kind]);
  }
  function needsKey(kind: ModelKind) {
    return !connections?.[kind].configured || connections[kind].config?.endpoint !== drafts[kind].endpoint || connections[kind].config?.auth_mode === 'chatgpt';
  }
  function changeProvider(endpoint: string) {
    drafts.general = {...drafts.general,
      endpoint: endpoint === 'chatgpt' ? endpoints.general : endpoint,
      auth_mode: endpoint === 'chatgpt' ? 'chatgpt' : 'api_key',
      chatgpt_account_id: null, model: ''};
    keys.general = '';
    message = ''; error = '';
  }
  $effect(()=>{ondirty(kinds.some(kind=>dirty(kind)));});
  async function load() {
    if (loading) return;
    loading = true; error = '';
    try {
      connections = await client.read();
      for (const kind of kinds) {if (connections[kind].config) drafts[kind] = {...connections[kind].config!};savedDrafts[kind]=JSON.stringify(drafts[kind]);draftRevisions[kind]=connections[kind].revision;keys[kind]='';}
    } catch (reason) { error = (reason as Error).message; }
    finally { loading = false; }
  }
  onMount(load);
  async function action(kind: ModelKind, action: 'save' | 'test' | 'remove') {
    if (!connections || loading || busy) return;
    busy = kind; error = ''; message = '';
    const secret = keys[kind];
    try {
      const revision = draftRevisions[kind];
      if (action === 'save') {
        connections[kind] = await client.save(kind, drafts[kind], revision, secret);keys[kind]='';draftRevisions[kind]=connections[kind].revision;savedDrafts[kind]=JSON.stringify(drafts[kind]);
        message = `${labels[kind]} saved. Test this revision to verify its capabilities.`;
      } else if (action === 'remove') {
        connections[kind] = await client.remove(kind, revision);keys[kind]='';draftRevisions[kind]=connections[kind].revision;
        message = `${labels[kind]} connection removed. Its credential is no longer available to the application.`;
        confirmRemove = null;savedDrafts[kind]=JSON.stringify(drafts[kind]);
      } else {
        const result = await client.test(kind, revision);
        connections[kind] = result.connection;
        if (result.status === 'success') message = result.message;
        else error = result.message;
      }
    } catch (reason) { error = (reason as Error).message; }
    finally { busy = null; }
  }
</script>

<p class="form-intro">Connect models for job matching and résumé writing. Each connection saves separately. Tests use sample data and may incur a small provider charge.</p>
<details class="connection-notes"><summary>Credential storage and test limits</summary><p class="field-help">Credentials are encrypted on the server and never read back. Back up the private instance key with your database to recover them. Tests allow one request at a time and five per provider per hour, with no automatic retries or model fallback.</p></details>
{#if error}<p class="model-error" role="alert">{error}</p>{/if}
<p role="status" aria-live="polite">{message}</p>
<button type="button" disabled={busy!==null || loading} onclick={()=>{if(!kinds.some(kind=>dirty(kind))||confirm('Discard unsaved model changes and reload saved connections?'))void load();}}>Reload model connections</button>
{#if connections}
  {#each kinds as kind}
    <form class="model-card" onsubmit={(event) => {event.preventDefault(); action(kind, 'save');}}>
      <div class="model-heading"><h3>{labels[kind]}</h3><span>{dirty(kind) ? 'Unsaved changes' : connections[kind].ready ? 'Capability test passed' : connections[kind].configured ? 'Saved · test required' : 'Not configured'}</span></div>
      <p>{kind === 'jev' ? 'Matches jobs against your confirmed experience, skills, eligibility and preferences.' : 'Writes résumés from your confirmed facts and the job description. Choose your ChatGPT plan, OpenAI API, Claude or OpenRouter.'}</p>
      <p class="field-help">{kind === 'jev' ? 'Connection tests verify access. Match quality depends on your saved profile and job criteria.' : 'Choose a model that supports structured outputs. OpenRouter model IDs include the provider prefix, in the form provider/model. Save and test the selected provider before generating a résumé.'}</p>
      <fieldset disabled={busy !== null || loading}>
        {#if kind === 'general'}
          <label for="general-provider">Provider</label>
          <select id="general-provider" value={drafts.general.auth_mode === 'chatgpt' ? 'chatgpt' : drafts.general.endpoint} onchange={(event) => changeProvider(event.currentTarget.value)}>
            <option value="chatgpt">ChatGPT plan</option>
            {#each generalProviders as provider}<option value={provider.endpoint}>{provider.label}</option>{/each}
          </select>
        {/if}
        {#if kind === 'general' && drafts.general.auth_mode === 'chatgpt'}
          <ChatGPTConnection bind:config={drafts.general} revision={draftRevisions.general} disabled={busy !== null} ondisconnect={() => {void load();}} />
        {:else}
        {#if kind === 'jev'}<label for="jev-model">Model</label><input id="jev-model" required maxlength="100" pattern="[A-Za-z0-9][A-Za-z0-9._:\/\-]*" bind:value={drafts.jev.model} autocomplete="off" />{/if}
        <label for={`${kind}-endpoint`}>Endpoint</label><input id={`${kind}-endpoint`} value={drafts[kind].endpoint} readonly /><small>Only this official endpoint is supported.</small>
        <label for={`${kind}-key`}>API key {connections[kind].configured ? needsKey(kind) ? '(required for selected provider)' : '(leave blank to keep saved key)' : ''}</label><input id={`${kind}-key`} type="password" maxlength="512" bind:value={keys[kind]} required={needsKey(kind)} autocomplete="new-password" spellcheck="false" />
        {#if kind === 'general'}<ApiModelPicker bind:model={drafts.general.model} endpoint={drafts.general.endpoint} revision={draftRevisions.general} apiKey={keys.general} savedKey={!needsKey('general')} disabled={busy !== null} />{/if}
        {/if}
        <div class="model-limits"><div><label for={`${kind}-timeout`}>Timeout (seconds)</label><input id={`${kind}-timeout`} type="number" min="5" max="60" required bind:value={drafts[kind].timeout_seconds} /></div>
        {#if kind === 'general' && drafts.general.auth_mode !== 'chatgpt'}<div><label for={`${kind}-tokens`}>Maximum output tokens</label><input id={`${kind}-tokens`} type="number" min="256" max="4096" required bind:value={drafts[kind].max_output_tokens} /></div>{/if}</div>
        {#if kind === 'jev'}<small>Jev's decision contract has no output-token limit parameter. The probe uses three fixed questions and a 64 KiB response limit.</small>{/if}
        <div class="model-actions"><button type="submit" disabled={kind === 'general' && (!drafts.general.model || (drafts.general.auth_mode === 'chatgpt' && !drafts.general.chatgpt_account_id))}>Save {labels[kind]}</button><button type="button" disabled={!connections[kind].configured || dirty(kind)} onclick={() => action(kind, 'test')}>{busy === kind ? 'Working…' : `Test ${labels[kind]}`}</button>{#if connections[kind].configured && drafts[kind].auth_mode !== 'chatgpt'}<button type="button" onclick={() => confirmRemove = kind}>Remove {labels[kind]}</button>{/if}</div>
        {#if confirmRemove === kind}<div class="remove-confirm"><p>Remove this connection and its saved credential?</p><button type="button" onclick={() => action(kind, 'remove')}>Confirm removal</button><button type="button" onclick={() => confirmRemove = null}>Cancel</button></div>{/if}
      </fieldset>
      {#if connections[kind].configured}<p class="field-help">Connection revision {connections[kind].revision}. {#if dirty(kind)}Save changes before testing.{/if}</p>{/if}
      {#if connections[kind].last_test}<p class="field-help">Last test: {connections[kind].last_test!.status}. Effective model: {connections[kind].last_test!.effective_model ?? 'unavailable'}. Input/output tokens: {connections[kind].last_test!.input_tokens ?? 'unknown'} / {connections[kind].last_test!.output_tokens ?? 'unknown'}.</p>{/if}
      <button type="button" disabled={busy!==null||loading||!dirty(kind)} onclick={()=>{drafts[kind]=JSON.parse(savedDrafts[kind]);keys[kind]='';}}>Discard {labels[kind]} changes</button>
    </form>
  {/each}
{:else if !error}<p>Loading model connections…</p>{/if}

<style>
  .connection-notes { margin: 0 0 16px; }
  .connection-notes summary { cursor: pointer; padding: 12px 0; font-weight: 600; color: var(--muted); }
  .model-card {border-top: 1px solid var(--border); padding: 1.5rem 0; margin-top: 1rem; min-width: 0}
  .model-heading {display:flex; flex-wrap:wrap; gap:.75rem; align-items:center; justify-content:space-between}
  h3 {margin:0; font-size:1.15rem} .model-heading span, small {font-size:.8rem; color:var(--muted)}
  p {line-height:1.6} fieldset {border:0; padding:0; margin:0; min-width:0}
  label {display:block; margin:1rem 0 .4rem; font-size:.85rem; font-weight:600}
  input, select {display:block; box-sizing:border-box; width:100%; min-width:0; padding:.7rem; border:1px solid var(--border); border-radius:var(--radius); font:inherit; background:transparent; color:inherit}
  input[readonly] {background:var(--surface); font-size:.8rem} small {display:block; margin-top:.4rem; line-height:1.5}
  .model-limits {display:flex; flex-wrap:wrap; gap:1rem} .model-limits > div {flex:1; min-width:120px}
  .model-actions {display:flex; flex-wrap:wrap; gap:.6rem; margin-top:1.2rem}
  button {font:inherit; font-size:.85rem; padding:.65rem .85rem; border-radius:var(--radius); border:1px solid var(--border); background:transparent; color:inherit; cursor:pointer}
  button[type=submit] {background:var(--accent); color:white; border-color:var(--accent)} button:disabled {opacity:.5; cursor:default}
  .model-error {color:#a12822} .remove-confirm {padding:1rem; margin-top:1rem; background:#f5eee8} .remove-confirm button {margin-right:.6rem}
</style>
