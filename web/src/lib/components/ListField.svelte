<script lang="ts">
  let { label, name, values = $bindable(), help = '', error = '' }: {label: string; name: string; values: string[]; help?: string; error?: string} = $props();
  let raw = $state('');
  const parse = (text: string) => text.split(',').map(value => value.trim()).filter(Boolean);
  $effect(() => { if (JSON.stringify(parse(raw)) !== JSON.stringify(values)) raw = values.join(', '); });
</script>
<label for={name}>{label}</label>
<input id={name} name={name} value={raw} oninput={event => { raw = event.currentTarget.value; values = parse(raw); }} maxlength="6000" aria-invalid={!!error} aria-describedby={error ? `${name}-error` : undefined} />
{#if error}<p class="field-error" id={`${name}-error`}>{error}</p>{/if}
{#if help}<p class="field-help">{help}</p>{/if}
