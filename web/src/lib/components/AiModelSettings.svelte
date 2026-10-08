<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import { Api } from '#lib/api.ts';
  import { endpoints, modelConnections, type ModelConfig, type ModelConnections, type ModelKind } from '#lib/model-connections.ts';
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
  let message = $state('');
  let error = $state('');
  let confirmRemove = $state<ModelKind | null>(null);
  function dirty(kind: ModelKind) {
    return !!keys[kind] || (!!savedDrafts[kind] && JSON.stringify(drafts[kind]) !== savedDrafts[kind]);
  }
  $effect(()=>{ondirty(kinds.some(kind=>dirty(kind)));});
  async function load() {
    try {
      connections = await client.read();
      for (const kind of kinds) {if (connections[kind].config) drafts[kind] = {...connections[kind].config!};savedDrafts[kind]=JSON.stringify(drafts[kind]);draftRevisions[kind]=connections[kind].revision;keys[kind]='';}
    } catch (reason) { error = (reason as Error).message; }
  }
  onMount(load);
  async function action(kind: ModelKind, action: 'save' | 'test' | 'remove') {
    if (!connections) return;
    busy = kind; error = ''; message = '';
    const secret = keys[kind]; keys[kind] = '';
    try {
      const revision = draftRevisions[kind];
      if (action === 'save') {
        connections[kind] = await client.save(kind, drafts[kind], revision, secret);draftRevisions[kind]=connections[kind].revision;savedDrafts[kind]=JSON.stringify(drafts[kind]);
        message = `${labels[kind]} saved. Test this revision to verify its capabilities.`;
      } else if (action === 'remove') {
        connections[kind] = await client.remove(kind, revision);draftRevisions[kind]=connections[kind].revision;
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

<p class="form-intro">Configure each provider independently. Saving never sends a model request. Tests send only synthetic facts and may incur a small provider charge.</p>
<p class="field-help">Credentials are encrypted on the server and never read back. Back up the private instance key with your database to recover them. Tests allow one request at a time and five per provider per hour, with no automatic retries or model fallback.</p>
{#if error}<p class="model-error" role="alert">{error}</p>{/if}
<p role="status" aria-live="polite">{message}</p>
<button type="button" disabled={busy!==null} onclick={()=>{if(!kinds.some(kind=>dirty(kind))||confirm('Discard unsaved model changes and reload saved connections?'))void load();}}>Reload model connections</button>
{#if connections}
  {#each kinds as kind}
    <form class="model-card" onsubmit={(event) => {event.preventDefault(); action(kind, 'save');}}>
      <div class="model-heading"><h3>{labels[kind]}</h3><span>{connections[kind].ready ? 'Capability test passed' : connections[kind].configured ? 'Saved · test required' : 'Not configured'}</span></div>
      <p>{kind === 'jev' ? 'TypeSafe System One API: typed criteria, evidence choices, and fit scores. Future matching will send confirmed candidate skills, experience, eligibility facts and preferences alongside job descriptions.' : 'OpenAI Responses API: requires strict JSON Schema output and token usage. Future extraction and résumé generation will send selected résumé text, confirmed candidate facts and job context.'}</p>
      <p class="field-help">{kind === 'jev' ? 'A passing connection test does not validate eligibility judgments or automatic rejection. Matching is a separate implementation step.' : 'Enter an OpenAI model with Responses and structured-output support. This contract does not promise compatibility with other providers. Generation is a separate implementation step.'}</p>
      <fieldset disabled={busy !== null}>
        <label for={`${kind}-model`}>Model</label><input id={`${kind}-model`} required maxlength="100" pattern="[A-Za-z0-9][A-Za-z0-9._:\-]*" bind:value={drafts[kind].model} autocomplete="off" />
        <label for={`${kind}-endpoint`}>Endpoint</label><input id={`${kind}-endpoint`} value={drafts[kind].endpoint} readonly /><small>Only this official endpoint is supported.</small>
        <label for={`${kind}-key`}>API key {connections[kind].configured ? '(leave blank to keep saved key)' : ''}</label><input id={`${kind}-key`} type="password" maxlength="512" bind:value={keys[kind]} required={!connections[kind].configured} autocomplete="new-password" spellcheck="false" />
        <div class="model-limits"><div><label for={`${kind}-timeout`}>Timeout (seconds)</label><input id={`${kind}-timeout`} type="number" min="5" max="60" required bind:value={drafts[kind].timeout_seconds} /></div>
        {#if kind === 'general'}<div><label for={`${kind}-tokens`}>Maximum output tokens</label><input id={`${kind}-tokens`} type="number" min="256" max="4096" required bind:value={drafts[kind].max_output_tokens} /></div>{/if}</div>
        {#if kind === 'jev'}<small>Jev's decision contract has no output-token limit parameter. The probe uses three fixed questions and a 64 KiB response limit.</small>{/if}
        <div class="model-actions"><button type="submit">Save {labels[kind]}</button><button type="button" disabled={!connections[kind].configured || dirty(kind)} onclick={() => action(kind, 'test')}>{busy === kind ? 'Working…' : `Test ${labels[kind]}`}</button>{#if connections[kind].configured}<button type="button" onclick={() => confirmRemove = kind}>Remove {labels[kind]}</button>{/if}</div>
        {#if confirmRemove === kind}<div class="remove-confirm"><p>Remove this connection and its saved credential?</p><button type="button" onclick={() => action(kind, 'remove')}>Confirm removal</button><button type="button" onclick={() => confirmRemove = null}>Cancel</button></div>{/if}
      </fieldset>
      {#if connections[kind].configured}<p class="field-help">Connection revision {connections[kind].revision}. {#if dirty(kind)}Save changes before testing.{/if}</p>{/if}
      {#if connections[kind].last_test}<p class="field-help">Last test: {connections[kind].last_test!.status}. Effective model: {connections[kind].last_test!.effective_model ?? 'unavailable'}. Input/output tokens: {connections[kind].last_test!.input_tokens ?? 'unknown'} / {connections[kind].last_test!.output_tokens ?? 'unknown'}.</p>{/if}
      <button type="button" disabled={busy!==null||!dirty(kind)} onclick={()=>{drafts[kind]=JSON.parse(savedDrafts[kind]);keys[kind]='';}}>Discard {labels[kind]} changes</button>
    </form>
  {/each}
{:else if !error}<p>Loading model connections…</p>{/if}

<style>
  .model-card {border-top: 1px solid var(--border); padding: 1.5rem 0; margin-top: 1rem; min-width: 0}
  .model-heading {display:flex; flex-wrap:wrap; gap:.75rem; align-items:center; justify-content:space-between}
  h3 {margin:0; font-size:1.15rem} .model-heading span, small {font-size:.8rem; color:var(--muted)}
  p {line-height:1.6} fieldset {border:0; padding:0; margin:0; min-width:0}
  label {display:block; margin:1rem 0 .4rem; font-size:.85rem; font-weight:600}
  input {display:block; box-sizing:border-box; width:100%; min-width:0; padding:.7rem; border:1px solid var(--border); border-radius:var(--radius); font:inherit; background:transparent; color:inherit}
  input[readonly] {background:var(--surface); font-size:.8rem} small {display:block; margin-top:.4rem; line-height:1.5}
  .model-limits {display:flex; flex-wrap:wrap; gap:1rem} .model-limits > div {flex:1; min-width:120px}
  .model-actions {display:flex; flex-wrap:wrap; gap:.6rem; margin-top:1.2rem}
  button {font:inherit; font-size:.85rem; padding:.65rem .85rem; border-radius:var(--radius); border:1px solid var(--border); background:transparent; color:inherit; cursor:pointer}
  button[type=submit] {background:var(--accent); color:white; border-color:var(--accent)} button:disabled {opacity:.5; cursor:default}
  .model-error {color:#a12822} .remove-confirm {padding:1rem; margin-top:1rem; background:#f5eee8} .remove-confirm button {margin-right:.6rem}
</style>
