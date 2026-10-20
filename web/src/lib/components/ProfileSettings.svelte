<script lang="ts">
  import { tick } from 'svelte';
  import { newFact, type Fact, type Profile, type FieldErrors } from '#lib/settings.ts';
  import ProfileEntry from './ProfileEntry.svelte';
  import ProfileSkills from './ProfileSkills.svelte';
  import ListField from './ListField.svelte';
  import { countryOptions } from '#lib/input-options.ts';
  let { profile = $bindable(), errors = {}, disabled = false }: {profile: Profile; errors?: FieldErrors; disabled?: boolean} = $props();
  const id = () => crypto.randomUUID();
  const sections = [{kind: 'experience', title: 'Experience', singular: 'experience', help: 'Add your work, internships, research or volunteer experience.'}, {kind: 'project', title: 'Projects', singular: 'project', help: 'Show what you built, the skills you used and where to find it.'}] as const;
  async function addEntry(kind: Fact['kind']) {
    const fact = newFact(kind);
    profile.facts.push(fact);
    await tick();
    document.getElementById(`${fact.id}-title`)?.focus();
  }
</script>
{#snippet error(path: string)}{#if errors[path]}<p class="field-error" id={`${path}-error`}>{errors[path]}</p>{/if}{/snippet}
<p class="form-intro">Keep the facts you can support. Blank fields remain unknown, and unconfirmed entries never become résumé or matching evidence.</p>
<div class="form-group">
  <h3>Personal details</h3>
  <label for="profile.name">Name</label><input id="profile.name" name="profile.name" bind:value={profile.name} maxlength="200" autocomplete="name" />
  <label for="profile.email">Email</label><input id="profile.email" name="profile.email" type="email" bind:value={profile.email} maxlength="254" autocomplete="email" aria-invalid={!!errors['profile.email']} aria-describedby={errors['profile.email'] ? 'profile.email-error' : undefined} />
  {@render error('profile.email')}
</div>
{#each sections as section}
  <section class="form-group" aria-labelledby={`profile-${section.kind}-heading`}>
    <div class="section-actions"><h3 id={`profile-${section.kind}-heading`}>{section.title}</h3><button type="button" class="secondary" disabled={disabled || profile.facts.length >= 100} onclick={() => addEntry(section.kind)}>Add {section.singular}</button></div>
    <p class="field-help">{section.help}</p>
    {#each profile.facts.map((fact, index) => ({fact, index})).filter(entry => entry.fact.kind === section.kind) as entry, number (entry.fact.id)}
      <ProfileEntry bind:fact={profile.facts[entry.index]} index={entry.index} number={number + 1} {errors} {disabled} onremove={() => profile.facts.splice(entry.index, 1)} />
    {:else}
      <p class="empty-section">No {section.singular === 'experience' ? 'experience' : 'projects'} added yet.</p>
    {/each}
  </section>
{/each}
<ProfileSkills bind:profile {disabled} {errors} />
<div class="form-group">
  <div class="section-actions"><h3>Education</h3><button type="button" class="secondary" disabled={disabled || profile.education.length >= 20} onclick={() => profile.education.unshift({id: id(), status: 'unknown', institution: '', degree: '', field: '', graduation_date: null})}>Add education</button></div>
  {#each profile.education as education, i (education.id)}
    <fieldset class="fact-entry" {disabled} aria-labelledby={`${education.id}-heading`}>
      <div class="entry-actions"><h4 id={`${education.id}-heading`}>Education {i + 1}</h4><button type="button" class="subtle remove-entry" disabled={disabled} onclick={() => profile.education.splice(i, 1)}>Remove education {i + 1}</button></div>
      <label for={`profile.education.${i}.institution`}>Institution</label><input id={`profile.education.${i}.institution`} name={`profile.education.${i}.institution`} bind:value={education.institution} maxlength="200" aria-invalid={!!errors[`profile.education.${i}.institution`]} />{@render error(`profile.education.${i}.institution`)}
      <label for={`profile.education.${i}.degree`}>Degree</label><input id={`profile.education.${i}.degree`} name={`profile.education.${i}.degree`} bind:value={education.degree} maxlength="200" aria-invalid={!!errors[`profile.education.${i}.degree`]} />{@render error(`profile.education.${i}.degree`)}
      <label for={`education-field-${education.id}`}>Field of study</label><input id={`education-field-${education.id}`} bind:value={education.field} maxlength="200" />
      <label for={`education-date-${education.id}`}>Expected or completed graduation date</label><input id={`education-date-${education.id}`} type="date" value={education.graduation_date ?? ''} onchange={event => education.graduation_date = event.currentTarget.value || null} />
      <label for={`education-status-${education.id}`}>Education confirmation</label><select id={`education-status-${education.id}`} bind:value={education.status}><option value="unknown">Unknown / needs confirmation</option><option value="confirmed">Confirmed by me</option></select>
    </fieldset>
  {/each}
</div>
<style>
  .section-actions { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
  .section-actions h3 { margin: 0; }
  .entry-actions { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }
  .entry-actions h4 { margin: 0; font-size: 1rem; }
  .remove-entry { color: #a83424; }
  .empty-section { color: var(--muted); margin: 20px 0 0; }
</style>
<div class="form-group">
  <h3>Availability & eligibility</h3><p class="field-help">Enter confirmed information only. Leaving a date or authorization blank means unknown; it does not mean unavailable or ineligible.</p>
  <label for="profile.available_from">Available from</label><input id="profile.available_from" type="date" value={profile.available_from ?? ''} onchange={event => profile.available_from = event.currentTarget.value || null} />
  <label for="profile.available_until">Available until</label><input id="profile.available_until" name="profile.available_until" type="date" value={profile.available_until ?? ''} onchange={event => profile.available_until = event.currentTarget.value || null} aria-invalid={!!errors['profile.available_until']} />{@render error('profile.available_until')}
  <label for="sponsorship">Will you need employer sponsorship?</label><select id="sponsorship" value={profile.requires_sponsorship === null ? 'unknown' : String(profile.requires_sponsorship)} onchange={event => profile.requires_sponsorship = event.currentTarget.value === 'unknown' ? null : event.currentTarget.value === 'true'}><option value="unknown">Unknown / not provided</option><option value="true">Yes</option><option value="false">No</option></select>
  <ListField {disabled} options={countryOptions} label="Confirmed work authorization" name="profile.work_authorization" error={errors['profile.work_authorization']} bind:values={profile.work_authorization} help="Choose a country or add a specific authorization description. Leave empty if unknown." />
</div>
