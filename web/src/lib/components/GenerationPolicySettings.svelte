<script lang="ts">
  import { getContext, onMount } from 'svelte';
  import { Api } from '#lib/api.ts';
  let {ondirty=()=>{}}=$props<{ondirty?:(value:boolean)=>void}>();
  const api = getContext<Api>('api');
  type Policy = {enabled: boolean; minimum_fit: number; recommendation: 'recommended' | 'recommended_or_review'; eligibility: 'confirmed' | 'confirmed_or_unknown'};
  type View = {revision: number; policy: Policy; preview: {qualifying_count: number; open_count: number}; explanation: string};
  let view = $state<View>();
  let draft = $state<Policy>({enabled: false, minimum_fit: 75, recommendation: 'recommended', eligibility: 'confirmed'});
  let savedDraft=$state('');
  let draftRevision=$state(0);
  const dirty=$derived(!!savedDraft&&JSON.stringify(draft)!==savedDraft);
  $effect(()=>{ondirty(dirty);});
  let message = $state('Loading generation rules…');
  let busy = $state(false);
  let failed = $state(false);
  async function load() {
    try { view = await api.request<View>('/api/generation-policy'); draft = {...view.policy};savedDraft=JSON.stringify(draft);draftRevision=view.revision; message = 'Saved generation rules loaded.'; }
    catch (error) { failed = true; message = (error as Error).message; }
  }
  async function action(save: boolean) {
    if (busy || !view) return;
    busy = true; failed = false;
    try {
      const result = await api.request<View>(save ? '/api/generation-policy' : '/api/generation-policy/preview', save ? {...draft, expected_revision: draftRevision} : draft);
      view = result;
      if (save) {draft = {...result.policy};savedDraft=JSON.stringify(draft);draftRevision=result.revision;}
      message = save ? 'Generation rules saved. Manual generation remains available.' : 'Preview updated for the rules shown below.';
    } catch (error) { failed = true; message = (error as Error).message; }
    finally { busy = false; }
  }
  onMount(() => { void load(); });
</script>
<p class="form-intro">Create job-specific drafts automatically using your saved general LLM. These rules are separate from search inclusion and email alerts. Every generated draft still needs your review.</p>
<div class="form-group">
  <label class="toggle-label"><input type="checkbox" disabled={!view||busy} bind:checked={draft.enabled} /> Automatically generate qualifying drafts</label>
  <p class="field-help">Off by default. Turning this off stops pending automatic work from starting. Manual generation stays available in each job.</p>
  <label for="generation-fit">Minimum fit</label><input id="generation-fit" disabled={!view||busy} type="number" min="0" max="100" step="1" bind:value={draft.minimum_fit} />
  <p class="field-help">Fit is rubric alignment on a 0–100 scale, not interview probability. Only current assessments qualify.</p>
  <label for="generation-recommendation">Recommendation rule</label><select id="generation-recommendation" disabled={!view||busy} bind:value={draft.recommendation}><option value="recommended">Recommended only</option><option value="recommended_or_review">Recommended or needs review</option></select>
  <label for="generation-eligibility">Eligibility rule</label><select id="generation-eligibility" disabled={!view||busy} bind:value={draft.eligibility}><option value="confirmed">Confirmed eligible only</option><option value="confirmed_or_unknown">Confirmed or unknown eligibility</option></select>
  <p class="field-help">Unknown eligibility stays unknown and needs review. Generation never establishes eligibility or rejects a job.</p>
  {#if view}<p aria-live="polite"><strong>{view.preview.qualifying_count}</strong> of {view.preview.open_count} current open jobs qualify. Applied jobs and stale assessments are excluded.</p>{/if}
  <div class="actions"><button disabled={busy || !view} onclick={() => action(false)}>Preview qualifying jobs</button><button class="primary" disabled={busy || !view} onclick={() => action(true)}>{busy ? 'Working…' : 'Save generation rules'}</button><button disabled={busy} onclick={()=>{if(!dirty||confirm('Discard the unsaved generation rules and reload saved settings?'))void load();}}>Reload rules</button></div>
  <p class:error={failed} role={failed ? 'alert' : 'status'}>{message}</p>
</div>
<style>.actions{display:flex;flex-wrap:wrap;gap:.75rem;margin-top:1rem}input[type="number"],select{display:block;max-width:100%;width:100%;margin:.5rem 0 1rem}.error{color:var(--danger,#c54545)}</style>
