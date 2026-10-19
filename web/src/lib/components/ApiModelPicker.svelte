<script lang="ts">
  import { getContext } from 'svelte';
  import type { Api } from '#lib/api.ts';
  import ChoiceField from '#lib/components/ChoiceField.svelte';
  import { modelConnections, type AvailableModel } from '#lib/model-connections.ts';

  let {model = $bindable(), endpoint, revision, apiKey, savedKey, disabled = false} = $props<{
    model: string; endpoint: string; revision: number; apiKey: string; savedKey: boolean; disabled?: boolean;
  }>();
  const client = modelConnections(getContext<Api>('api'));
  let models = $state<AvailableModel[]>([]);
  let loading = $state(false);
  let loaded = $state(false);
  let error = $state('');
  let request = 0;
  const publicCatalog = $derived(endpoint === 'https://openrouter.ai/api/v1/chat/completions');
  const canLoad = $derived(publicCatalog || !!apiKey || savedKey);
  const choices = $derived(models.map(item => ({label: item.name, value: item.id, search: item.id})));
  const unavailable = $derived(loaded && !!model && !models.some(item => item.id === model));

  async function fetchModels(id: number, source: {endpoint: string; revision: number; key: string}) {
    try {
      const result = await client.models(source.endpoint, source.revision, source.key);
      if (id !== request) return;
      models = result.models; loaded = true;
    } catch (reason) { if (id === request) error = (reason as Error).message; }
    finally { if (id === request) loading = false; }
  }
  function refresh() {
    const id = ++request;
    models = []; loaded = false; error = ''; loading = true;
    void fetchModels(id, {endpoint, revision, key: publicCatalog ? '' : apiKey});
  }
  $effect(() => {
    const source = {endpoint, revision, key: publicCatalog ? '' : apiKey};
    const ready = canLoad;
    const id = ++request;
    models = []; loaded = false; error = ''; loading = ready;
    const timer = ready ? window.setTimeout(() => void fetchModels(id, source), source.key ? 600 : 0) : undefined;
    return () => { ++request; window.clearTimeout(timer); };
  });
</script>

<ChoiceField label="Model" name="general-model" options={choices} max={1} required
  bind:values={() => model ? [model] : [], values => model = values[0] ?? ''}
  disabled={disabled || loading || !models.length} placeholder="Search available models…"
  {error} help={unavailable ? 'The selected model is no longer listed. Choose an available model.' : 'Search by model name or ID. Save and test your choice before generating a résumé.'} />
<p role="status" aria-live="polite">
  {#if loading}Loading available models…
  {:else if loaded}{models.length ? `${models.length} model${models.length === 1 ? '' : 's'} available.` : 'No models are available for this connection.'}
  {:else if !canLoad}Enter an API key to load available models.{/if}
</p>
<button type="button" disabled={disabled || loading || !canLoad} onclick={refresh}>Refresh available models</button>

<style>
  p { color: var(--muted); font-size: .85rem; line-height: 1.5; }
  button { font: inherit; font-size: .85rem; padding: .65rem .85rem; border-radius: var(--radius); border: 1px solid var(--border); background: transparent; color: inherit; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
</style>
