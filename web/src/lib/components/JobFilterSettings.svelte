<script lang="ts">
  import { untrack } from 'svelte';
  import type { Preferences, FieldErrors } from '#lib/settings.ts';
  import ListField from './ListField.svelte';
  import ChoiceField from './ChoiceField.svelte';
  import { countryOptions, skillOptions } from '#lib/input-options.ts';
  let { preferences = $bindable(), errors = {}, disabled = false }: {preferences: Preferences; errors?: FieldErrors; disabled?: boolean} = $props();
  let openToOtherLocations = $state(true);
  const locations = $derived([...new Set([...preferences.hard.locations, ...preferences.soft.locations])]);
  const locationField = $derived(openToOtherLocations ? 'preferences.soft.locations' : 'preferences.hard.locations');
  $effect(() => {
    const current = preferences;
    untrack(() => { openToOtherLocations = current.hard.locations.length === 0; });
  });
  function setLocations(values: string[]) {
    preferences.hard.locations = openToOtherLocations ? [] : values;
    preferences.soft.locations = openToOtherLocations ? values : [];
  }
  function setLocationFlexibility(event: Event) {
    const selected = [...locations];
    openToOtherLocations = (event.currentTarget as HTMLInputElement).checked;
    setLocations(selected);
  }
</script>
<p class="form-intro">Jev uses your saved settings when evaluating jobs; changes apply to future evaluations.</p>
<div class="form-group location-group">
  <ListField {disabled} label="Locations" name={locationField} error={errors['preferences.hard.locations'] || errors['preferences.soft.locations']} bind:values={() => locations, setLocations} help="Add cities or regions, such as Denver, CO. Leave empty if you’re open to anywhere." />
  <label class="toggle-label"><input type="checkbox" {disabled} checked={openToOtherLocations} onchange={setLocationFlexibility} aria-describedby="location-flexibility-help" /> I’m open to locations beyond those selected</label>
  <p class="field-help" id="location-flexibility-help">{openToOtherLocations ? 'Selected locations are preferences. Jobs elsewhere can still match, subject to your other requirements.' : 'Only jobs in your selected locations can match. Unknown job locations still need review.'}</p>
</div>
<div class="form-group">
  <h3>Mandatory constraints</h3><p class="field-help">Use these only for requirements you cannot compromise on. An empty list adds no restriction; an unknown job detail must be reviewed rather than assumed to violate it.</p>
  <ChoiceField {disabled} options={countryOptions} label="Required countries" name="preferences.hard.countries" error={errors['preferences.hard.countries']} bind:values={preferences.hard.countries} placeholder="Search countries by name or code…" help="Choose any acceptable countries. Leave empty if you’re open to anywhere." />
  <ListField {disabled} label="Required terms" name="preferences.hard.term_keywords" error={errors['preferences.hard.term_keywords']} bind:values={preferences.hard.term_keywords} help="Add acceptable internship terms, such as Summer 2027." />
</div>
<div class="form-group">
  <h3>Soft preferences</h3><p class="field-help">These describe what you prefer and cannot override a mandatory constraint.</p>
  <ListField {disabled} label="Preferred roles" name="preferences.soft.roles" error={errors['preferences.soft.roles']} bind:values={preferences.soft.roles} help="Add roles you’re interested in, such as Software engineering or UX research." />
  <ListField {disabled} options={skillOptions} max={50} label="Preferred skills to use" name="preferences.soft.skills" error={errors['preferences.soft.skills']} bind:values={preferences.soft.skills} help="These are interests, not claims that you possess a skill. Add confirmed skills in Profile." />
</div>

<style>
  .location-group .toggle-label { margin-top: 12px; min-height: 44px; }
</style>
