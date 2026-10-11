<script lang="ts">
  import ChoiceField from './ChoiceField.svelte';
  import type { Choice } from '#lib/input-options.ts';
  let { label, name, values = $bindable(), help = '', error = '', options = [], max = 30, disabled = false }: {label: string; name: string; values: string[]; help?: string; error?: string; options?: Choice[]; max?: number; disabled?: boolean} = $props();
</script>
<ChoiceField {disabled} {label} {name} bind:values {help} {error} {options} {max} custom placeholder="Type to add…" />
