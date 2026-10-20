<script lang="ts">
  import { tick } from 'svelte';
  import type { Fact, FieldErrors } from '#lib/settings.ts';
  import { skillOptions } from '#lib/input-options.ts';
  import ListField from './ListField.svelte';
  let { fact = $bindable(), index, number, errors = {}, disabled = false, onremove }: {
    fact: Fact; index: number; number: number; errors?: FieldErrors; disabled?: boolean; onremove: () => void;
  } = $props();
  const path = $derived(`profile.facts.${index}`);
  const label = $derived(fact.kind === 'experience' ? 'Experience' : 'Project');
  async function addLink() {
    fact.links.push('');
    await tick();
    document.getElementById(`${fact.id}-link-${fact.links.length - 1}`)?.focus();
  }
</script>

{#snippet error(field: string)}
  {#if errors[`${path}.${field}`]}<p class="field-error" id={`${path}.${field}-error`}>{errors[`${path}.${field}`]}</p>{/if}
{/snippet}

<fieldset class="fact-entry" {disabled} aria-labelledby={`${fact.id}-heading`}>
  <div class="entry-actions">
    <h4 id={`${fact.id}-heading`}>{label} {number}</h4>
    <button type="button" class="subtle remove-entry" onclick={onremove}>Remove {label.toLowerCase()} {number}</button>
  </div>
  <div class="entry-grid">
    <div class:full-width={fact.kind === 'project'}>
      <label for={`${fact.id}-title`}>{fact.kind === 'experience' ? 'Job title' : 'Project title'}</label>
      <input id={`${fact.id}-title`} name={`${path}.title`} bind:value={fact.title} maxlength="200" />
    </div>
    {#if fact.kind === 'experience'}
      <div><label for={`${fact.id}-company`}>Company</label><input id={`${fact.id}-company`} name={`${path}.company`} bind:value={fact.company} maxlength="200" /></div>
      <div class="full-width"><label for={`${fact.id}-location`}>Location</label><input id={`${fact.id}-location`} name={`${path}.location`} bind:value={fact.location} maxlength="200" placeholder="City, state or remote" /></div>
    {/if}
    <div><label for={`${fact.id}-start`}>Start date</label><input id={`${fact.id}-start`} name={`${path}.start_date`} type="month" value={fact.start_date ?? ''} onchange={event => fact.start_date = event.currentTarget.value || null} /></div>
    <div><label for={`${path}.end_date`}>End date</label><input id={`${path}.end_date`} name={`${path}.end_date`} type="month" disabled={fact.current} value={fact.end_date ?? ''} onchange={event => fact.end_date = event.currentTarget.value || null} aria-invalid={!!errors[`${path}.end_date`]} aria-describedby={errors[`${path}.end_date`] ? `${path}.end_date-error` : undefined} />{@render error('end_date')}</div>
  </div>
  <label class="check-label" for={`${fact.id}-present`}><input id={`${fact.id}-present`} type="checkbox" checked={fact.current} onchange={event => { fact.current = event.currentTarget.checked; if (fact.current) fact.end_date = null; }} /><span>{fact.kind === 'experience' ? 'I currently work here' : 'This project is ongoing'} <span class="field-help">(Present)</span></span></label>
  <label for={`${path}.text`}>{fact.kind === 'experience' ? 'Responsibilities & accomplishments' : 'Project description & accomplishments'}</label>
  <textarea id={`${path}.text`} name={`${path}.text`} bind:value={fact.text} maxlength="2000" rows="3" aria-invalid={!!errors[`${path}.text`]} aria-describedby={errors[`${path}.text`] ? `${path}.text-error` : undefined}></textarea>
  {@render error('text')}
  <ListField {disabled} options={skillOptions} label={fact.kind === 'experience' ? 'Skills used' : 'Project skills'} name={`${path}.skills`} error={errors[`${path}.skills`]} bind:values={fact.skills} />
  {#if fact.kind === 'project'}
    <div class="links-heading" id={`${path}.links`} tabindex="-1"><span>Project links</span><button type="button" class="subtle" disabled={fact.links.length >= 10} onclick={addLink}>Add link</button></div>
    {#each fact.links as link, i}
      <label for={`${fact.id}-link-${i}`}>Link {i + 1}</label>
      <div class="link-row"><input id={`${fact.id}-link-${i}`} name={`${path}.links.${i}`} type="url" bind:value={fact.links[i]} maxlength="2048" placeholder="https://github.com/you/project" aria-invalid={!!errors[`${path}.links`]} aria-describedby={errors[`${path}.links`] ? `${path}.links-error` : undefined} /><button type="button" class="subtle remove-entry" onclick={() => fact.links.splice(i, 1)}>Remove link {i + 1}</button></div>
    {/each}
    {@render error('links')}
  {/if}
  <label class="check-label" for={`${fact.id}-confirmed`}><input id={`${fact.id}-confirmed`} type="checkbox" checked={fact.status === 'confirmed'} onchange={event => fact.status = event.currentTarget.checked ? 'confirmed' : 'unknown'} /><span>I confirm this {label.toLowerCase()}</span></label>
</fieldset>

<style>
  .entry-actions { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
  .entry-actions h4 { margin: 0; font-size: 1rem; }
  .remove-entry { color: #a83424; }
  .entry-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
  .entry-grid > div, .link-row > input { min-width: 0; }
  .full-width { grid-column: 1 / -1; }
  .check-label { display: flex; align-items: center; gap: 12px; margin: 18px 0; font-weight: 400; }
  .check-label input { width: 18px; min-height: 18px; height: 18px; margin: 0; flex: 0 0 18px; accent-color: var(--accent); }
  .links-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 16px; font-weight: 600; }
  .link-row { display: flex; align-items: center; gap: 12px; }
  .link-row input { flex: 1; }
  .link-row button { flex-shrink: 0; }
  @media (max-width: 600px) { .entry-grid { grid-template-columns: minmax(0, 1fr); } .link-row { flex-wrap: wrap; } .link-row input { flex-basis: 100%; } }
</style>
