<script lang="ts">
  import MultiSelect from 'svelte-multiselect/MultiSelect.svelte';
  import type { Choice } from '#lib/input-options.ts';
  let { label, name, values = $bindable(), options = [], help = '', error = '', custom = false, max = 30, required = false, disabled = false, placeholder = 'Search and select…' }: {
    label: string; name: string; values: string[]; options?: Choice[]; help?: string; error?: string;
    custom?: boolean; max?: number; required?: boolean; disabled?: boolean; placeholder?: string;
  } = $props();
  const valueOf = (option: Choice | string | number) => typeof option === 'object' ? option.value ?? option.label : String(option);
  const selected = $derived(values.map(value => options.find(option => valueOf(option) === value) ?? {label: value, value}));
  function select(selection: Choice[]) {
    const next = selection.map(valueOf);
    if (JSON.stringify(next) !== JSON.stringify(values)) values = next;
  }
</script>

<div class="choice-field">
  <label for={name}>{label}</label>
  <MultiSelect {name} id={name} {options} {required} {disabled} {placeholder}
    bind:selected={() => selected, select}
    allowEmpty allowUserOptions={custom} maxSelect={max} invalid={!!error}
    key={option => valueOf(option).toLocaleLowerCase()}
    filterFunc={(option, query) => `${option.label} ${option.search ?? ''}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())}
    oncreate={({option}) => valueOf(option).trim() ? {label: valueOf(option).trim()} : false}
    inputProps={{maxlength: 200, 'aria-describedby': `${name}-help${error ? ` ${name}-error` : ''}`}}
    closeDropdownOnSelect="retain-focus" selectedOptionsDraggable={false}
    removeBtnTitle="Remove" removeAllTitle={`Clear ${label.toLowerCase()}`}
    createOptionMsg={({searchText}) => `Add “${searchText.trim()}”`}
    noMatchingOptionsMsg="No matches. Try another name."
    parse_paste={text => text.split(/\r?\n/).flatMap(text => {
      const label = text.trim();
      const match = options.find(option => option.label.toLowerCase() === label.toLowerCase() || valueOf(option).toLowerCase() === label.toLowerCase());
      return match ? [match] : custom && label && label.length <= 200 ? [{label}] : [];
    })}
  >
    {#snippet children({option})}<span class="choice-label">{#if option.flag}<span aria-hidden="true">{option.flag}</span>{/if}<span>{option.label}</span></span>{/snippet}
  </MultiSelect>
  {#if error}<p class="field-error" id={`${name}-error`}>{error}</p>{/if}
  <p class="field-help" id={`${name}-help`}>{help}{custom ? ' Type an entry and press Enter to add it.' : ''}</p>
</div>

<style>
  .choice-field { min-width: 0; --sms-border: 1px solid #b6bed0; --sms-border-radius: var(--radius); --sms-bg: var(--surface); --sms-text-color: var(--ink); --sms-placeholder-color: var(--muted); --sms-placeholder-opacity: 1; --sms-active-color: var(--accent); --sms-focus-border: 1px solid var(--accent); --sms-min-height: 46px; --sms-padding: 6px 8px; --sms-font-size: 14px; --sms-selected-bg: var(--selected); --sms-selected-text-color: var(--ink); --sms-selected-li-padding: 3px 5px 3px 8px; --sms-options-bg: var(--surface); --sms-options-border: 1px solid var(--border); --sms-options-border-radius: var(--radius); --sms-options-shadow: none; --sms-options-max-height: 240px; --sms-options-li-padding: 10px 12px; --sms-li-active-bg: var(--selected); }
  .choice-field :global(input) { border: 0; border-radius: 0; padding: 6px 3px; width: auto; min-width: 4ch; background: transparent; box-shadow: none; }
  .choice-field :global(input:focus-visible) { outline: none; }
  .choice-field :global(.multiselect:focus-within) { outline: 2px solid var(--accent); outline-offset: 2px; }
  .choice-field :global(button) { min-width: 28px; min-height: 28px; }
  .choice-field :global(ul.selected) { min-width: 0; }
  .choice-field :global(ul.selected > li) { max-width: 100%; white-space: normal; }
  .choice-label { display: inline-flex; align-items: center; gap: 8px; overflow-wrap: anywhere; }
  @media (pointer: coarse) { .choice-field :global(button) { min-width: 36px; min-height: 36px; } }
  @media (prefers-reduced-motion: reduce) { .choice-field :global(*) { transition: none !important; animation: none !important; } }
</style>
