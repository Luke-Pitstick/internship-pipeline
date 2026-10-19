<script lang="ts">
  import { newFact, type Fact, type Profile, type FieldErrors } from '#lib/settings.ts';
  import { skillOptions } from '#lib/input-options.ts';
  import ListField from './ListField.svelte';
  let { profile = $bindable(), disabled = false, errors = {} }: {profile: Profile; disabled?: boolean; errors?: FieldErrors} = $props();
  const skillFacts = $derived(profile.facts.filter(fact => fact.kind === 'skill'));
  const names = (fact: Fact) => fact.skills.length ? fact.skills : [fact.text];
  const values = $derived([...new Set(skillFacts.flatMap(names))]);
  const confirmed = $derived(skillFacts.length > 0 && skillFacts.every(fact => fact.status === 'confirmed'));
  const error = $derived(profile.facts.flatMap((fact, i) => fact.kind === 'skill' ? [errors[`profile.facts.${i}.text`], errors[`profile.facts.${i}.skills`]] : []).filter(Boolean).join(' '));
  function updateSkills(next: string[]) {
    const previous = new Set(values);
    profile.facts = profile.facts.flatMap(fact => {
      if (fact.kind !== 'skill') return [fact];
      const remaining = names(fact).filter(name => next.includes(name));
      if (!remaining.length) return [];
      if (remaining.length === names(fact).length) return [fact];
      return [{...fact, text: remaining.join(', '), skills: remaining}];
    });
    for (const name of next.filter(name => !previous.has(name))) {
      profile.facts.push({...newFact('skill'), text: name, skills: [name], status: 'confirmed'});
    }
  }
</script>

<div class="form-group">
  <h3>Skills</h3>
  <ListField {disabled} options={skillOptions} label="Your skills" name="profile.skills" bind:values={() => values, updateSkills} {error} max={Math.min(100, values.length + 100 - profile.facts.length)} help="Add the skills you can support." />
  {#if skillFacts.length && !confirmed}
    <p class="field-help">Some skills still need your confirmation before they’re used in matching or résumés.</p>
    <button type="button" class="secondary" {disabled} onclick={() => { for (const fact of skillFacts) fact.status = 'confirmed'; }}>Confirm these skills</button>
  {/if}
</div>
