<script lang="ts">
  import type { Profile, FieldErrors } from '#lib/settings.ts';
  import ListField from './ListField.svelte';
  let { profile = $bindable(), errors = {} }: {profile: Profile; errors?: FieldErrors} = $props();
  const id = () => crypto.randomUUID();
</script>
{#snippet error(path: string)}{#if errors[path]}<p class="field-error" id={`${path}-error`}>{errors[path]}</p>{/if}{/snippet}
<p class="form-intro">Keep the facts you can support. Blank fields remain unknown, and unconfirmed entries never become résumé or matching evidence.</p>
<div class="form-group">
  <h3>Personal details</h3>
  <label for="profile.name">Name</label><input id="profile.name" name="profile.name" bind:value={profile.name} maxlength="200" autocomplete="name" />
  <label for="profile.email">Email</label><input id="profile.email" name="profile.email" type="email" bind:value={profile.email} maxlength="254" autocomplete="email" aria-invalid={!!errors['profile.email']} aria-describedby={errors['profile.email'] ? 'profile.email-error' : undefined} />
  {@render error('profile.email')}
</div>
<div class="form-group">
  <h3>Experience, projects & skills</h3><p class="field-help">Add one supported claim per entry. Its identifier stays the same when you edit it.</p>
  {#each profile.facts as fact, i (fact.id)}
    <fieldset class="fact-entry"><legend>Fact {i + 1}</legend>
      <label for={`fact-kind-${fact.id}`}>Type</label><select id={`fact-kind-${fact.id}`} bind:value={fact.kind}><option value="experience">Experience</option><option value="project">Project</option><option value="skill">Skill</option></select>
      <label for={`profile.facts.${i}.text`}>Supporting fact</label><textarea id={`profile.facts.${i}.text`} name={`profile.facts.${i}.text`} bind:value={fact.text} maxlength="2000" rows="3" aria-invalid={!!errors[`profile.facts.${i}.text`]} aria-describedby={errors[`profile.facts.${i}.text`] ? `profile.facts.${i}.text-error` : undefined}></textarea>
      {@render error(`profile.facts.${i}.text`)}
      <ListField label="Related skills" name={`profile.facts.${i}.skills`} error={errors[`profile.facts.${i}.skills`]} bind:values={fact.skills} help="Separate skills with commas. Only confirmed facts contribute evidence." />
      <label for={`fact-status-${fact.id}`}>Confirmation</label><select id={`fact-status-${fact.id}`} bind:value={fact.status}><option value="unknown">Unknown / needs confirmation</option><option value="confirmed">Confirmed by me</option></select>
      <p class="field-help fact-id">Fact ID: {fact.id}</p><button type="button" class="subtle" onclick={() => profile.facts.splice(i, 1)}>Remove fact {i + 1}</button>
    </fieldset>
  {/each}
  <button type="button" class="secondary" disabled={profile.facts.length >= 100} onclick={() => profile.facts.push({id: id(), kind: 'experience', status: 'unknown', text: '', skills: []})}>Add fact or skill</button>
</div>
<div class="form-group">
  <h3>Education</h3>
  {#each profile.education as education, i (education.id)}
    <fieldset class="fact-entry"><legend>Education {i + 1}</legend>
      <label for={`profile.education.${i}.institution`}>Institution</label><input id={`profile.education.${i}.institution`} name={`profile.education.${i}.institution`} bind:value={education.institution} maxlength="200" aria-invalid={!!errors[`profile.education.${i}.institution`]} />{@render error(`profile.education.${i}.institution`)}
      <label for={`profile.education.${i}.degree`}>Degree</label><input id={`profile.education.${i}.degree`} name={`profile.education.${i}.degree`} bind:value={education.degree} maxlength="200" aria-invalid={!!errors[`profile.education.${i}.degree`]} />{@render error(`profile.education.${i}.degree`)}
      <label for={`education-field-${education.id}`}>Field of study</label><input id={`education-field-${education.id}`} bind:value={education.field} maxlength="200" />
      <label for={`education-date-${education.id}`}>Expected or completed graduation date</label><input id={`education-date-${education.id}`} type="date" value={education.graduation_date ?? ''} onchange={event => education.graduation_date = event.currentTarget.value || null} />
      <label for={`education-status-${education.id}`}>Education confirmation</label><select id={`education-status-${education.id}`} bind:value={education.status}><option value="unknown">Unknown / needs confirmation</option><option value="confirmed">Confirmed by me</option></select>
      <p class="field-help fact-id">Fact ID: {education.id}</p><button type="button" class="subtle" onclick={() => profile.education.splice(i, 1)}>Remove education {i + 1}</button>
    </fieldset>
  {/each}
  <button type="button" class="secondary" disabled={profile.education.length >= 20} onclick={() => profile.education.push({id: id(), status: 'unknown', institution: '', degree: '', field: '', graduation_date: null})}>Add education</button>
</div>
<div class="form-group">
  <h3>Availability & eligibility</h3><p class="field-help">Enter confirmed information only. Leaving a date or authorization blank means unknown; it does not mean unavailable or ineligible.</p>
  <label for="profile.available_from">Available from</label><input id="profile.available_from" type="date" value={profile.available_from ?? ''} onchange={event => profile.available_from = event.currentTarget.value || null} />
  <label for="profile.available_until">Available until</label><input id="profile.available_until" name="profile.available_until" type="date" value={profile.available_until ?? ''} onchange={event => profile.available_until = event.currentTarget.value || null} aria-invalid={!!errors['profile.available_until']} />{@render error('profile.available_until')}
  <label for="sponsorship">Will you need employer sponsorship?</label><select id="sponsorship" value={profile.requires_sponsorship === null ? 'unknown' : String(profile.requires_sponsorship)} onchange={event => profile.requires_sponsorship = event.currentTarget.value === 'unknown' ? null : event.currentTarget.value === 'true'}><option value="unknown">Unknown / not provided</option><option value="true">Yes</option><option value="false">No</option></select>
  <ListField label="Confirmed work authorization" name="profile.work_authorization" error={errors['profile.work_authorization']} bind:values={profile.work_authorization} help="List countries or authorization descriptions separated by commas. Leave blank if unknown." />
</div>
