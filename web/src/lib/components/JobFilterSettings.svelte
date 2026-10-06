<script lang="ts">
  import type { Preferences, FieldErrors } from '#lib/settings.ts';
  import ListField from './ListField.svelte';
  let { preferences = $bindable(), errors = {} }: {preferences: Preferences; errors?: FieldErrors} = $props();
  const roles = [{value: 'swe', label: 'Software engineering'}, {value: 'pm', label: 'Product management'}, {value: 'ml_ai', label: 'Machine learning & AI'}, {value: 'ds', label: 'Data science'}];
</script>
<p class="form-intro">Mandatory constraints and preferences are saved separately. Jev evaluation is still being built, so these settings do not yet filter or rescore the job board.</p>
<div class="form-group">
  <h3>Mandatory constraints</h3><p class="field-help">Use these only for requirements you cannot compromise on. An empty list adds no restriction; an unknown job detail must be reviewed rather than assumed to violate it.</p>
  <ListField label="Required countries" name="preferences.hard.countries" error={errors['preferences.hard.countries']} bind:values={preferences.hard.countries} help="Comma-separated alternatives, such as United States, Canada." />
  <ListField label="Required locations" name="preferences.hard.locations" error={errors['preferences.hard.locations']} bind:values={preferences.hard.locations} help="Comma-separated acceptable locations. Leave blank if flexible." />
  <ListField label="Required terms" name="preferences.hard.term_keywords" error={errors['preferences.hard.term_keywords']} bind:values={preferences.hard.term_keywords} help="Comma-separated acceptable internship terms, such as Summer 2027." />
</div>
<div class="form-group">
  <h3>Soft preferences</h3><p class="field-help">These describe what you prefer and cannot override a mandatory constraint.</p>
  <fieldset class="role-options"><legend>Preferred roles</legend>{#each roles as role}<label class="toggle-label"><input type="checkbox" value={role.value} bind:group={preferences.soft.roles} />{role.label}</label>{/each}</fieldset>
  <ListField label="Preferred locations" name="preferences.soft.locations" error={errors['preferences.soft.locations']} bind:values={preferences.soft.locations} help="Separate locations with commas." />
  <ListField label="Preferred skills to use" name="preferences.soft.skills" error={errors['preferences.soft.skills']} bind:values={preferences.soft.skills} help="These are interests, not claims that you possess a skill. Add confirmed skills in Profile." />
</div>
