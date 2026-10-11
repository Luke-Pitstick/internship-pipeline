<script lang="ts">
  import type { Preferences, FieldErrors } from '#lib/settings.ts';
  import ListField from './ListField.svelte';
  import ChoiceField from './ChoiceField.svelte';
  import { countryOptions, skillOptions } from '#lib/input-options.ts';
  let { preferences = $bindable(), errors = {}, disabled = false }: {preferences: Preferences; errors?: FieldErrors; disabled?: boolean} = $props();
  const roles = [{value: 'swe', label: 'Software engineering'}, {value: 'pm', label: 'Product management'}, {value: 'ml_ai', label: 'Machine learning & AI'}, {value: 'ds', label: 'Data science'}];
</script>
<p class="form-intro">Mandatory constraints and preferences are saved separately. Jev uses your saved settings when evaluating jobs; changes apply to future evaluations.</p>
<div class="form-group">
  <h3>Mandatory constraints</h3><p class="field-help">Use these only for requirements you cannot compromise on. An empty list adds no restriction; an unknown job detail must be reviewed rather than assumed to violate it.</p>
  <ChoiceField {disabled} options={countryOptions} label="Required countries" name="preferences.hard.countries" error={errors['preferences.hard.countries']} bind:values={preferences.hard.countries} placeholder="Search countries by name or code…" help="Choose any acceptable countries. Leave empty if you’re open to anywhere." />
  <ListField {disabled} label="Required locations" name="preferences.hard.locations" error={errors['preferences.hard.locations']} bind:values={preferences.hard.locations} help="Add each acceptable city or region separately, for example Denver, CO. Leave empty if flexible." />
  <ListField {disabled} label="Required terms" name="preferences.hard.term_keywords" error={errors['preferences.hard.term_keywords']} bind:values={preferences.hard.term_keywords} help="Add acceptable internship terms, such as Summer 2027." />
</div>
<div class="form-group">
  <h3>Soft preferences</h3><p class="field-help">These describe what you prefer and cannot override a mandatory constraint.</p>
  <fieldset class="role-options"><legend>Preferred roles</legend>{#each roles as role}<label class="toggle-label"><input type="checkbox" value={role.value} bind:group={preferences.soft.roles} />{role.label}</label>{/each}</fieldset>
  <ListField {disabled} label="Preferred locations" name="preferences.soft.locations" error={errors['preferences.soft.locations']} bind:values={preferences.soft.locations} help="Add each preferred city or region separately." />
  <ListField {disabled} options={skillOptions} max={50} label="Preferred skills to use" name="preferences.soft.skills" error={errors['preferences.soft.skills']} bind:values={preferences.soft.skills} help="These are interests, not claims that you possess a skill. Add confirmed skills in Profile." />
</div>
