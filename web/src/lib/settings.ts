export const categories = ['Profile', 'Job Filters', 'Sources', 'Resume Generation', 'AI Models', 'Notifications & Integrations', 'Diagnostics'] as const;
export type Category = typeof categories[number];
export type Confirmation = 'confirmed' | 'unknown';
export interface Fact { id: string; kind: 'experience'|'project'|'skill'; status: Confirmation; text: string; skills: string[] }
export interface Education { id: string; status: Confirmation; institution: string; degree: string; field: string; graduation_date: string|null }
export interface Profile { name: string; email: string; facts: Fact[]; education: Education[]; available_from: string|null; available_until: string|null; requires_sponsorship: boolean|null; work_authorization: string[] }
export interface Preferences { hard: { countries: string[]; locations: string[]; term_keywords: string[] }; soft: { roles: string[]; locations: string[]; skills: string[] } }
export interface Snapshot { revision: number; saved_at: string|null; profile: Profile; preferences: Preferences }
export type FieldErrors = Record<string, string>;
export function validateSettings(snapshot: Snapshot): FieldErrors {
  const errors: FieldErrors = {};
  if (snapshot.profile.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(snapshot.profile.email)) errors['profile.email'] = 'Enter a valid email or leave it unknown.';
  if (snapshot.profile.available_from && snapshot.profile.available_until && snapshot.profile.available_until < snapshot.profile.available_from) errors['profile.available_until'] = 'End date must be on or after the start date.';
  snapshot.profile.facts.forEach((fact, index) => {
    if (fact.status === 'confirmed' && !fact.text.trim()) errors[`profile.facts.${index}.text`] = 'Add supporting text before confirming this fact.';
  });
  snapshot.profile.education.forEach((education, index) => {
    if (education.status === 'confirmed') {
      if (!education.institution.trim()) errors[`profile.education.${index}.institution`] = 'Enter the institution before confirming education.';
      if (!education.degree.trim()) errors[`profile.education.${index}.degree`] = 'Enter the degree before confirming education.';
    }
  });
  const lists: [string, string[], number][] = [
    ['profile.work_authorization', snapshot.profile.work_authorization, 30],
    ['preferences.hard.countries', snapshot.preferences.hard.countries, 30],
    ['preferences.hard.locations', snapshot.preferences.hard.locations, 30],
    ['preferences.hard.term_keywords', snapshot.preferences.hard.term_keywords, 30],
    ['preferences.soft.locations', snapshot.preferences.soft.locations, 30],
    ['preferences.soft.skills', snapshot.preferences.soft.skills, 50],
    ...snapshot.profile.facts.map((fact, index): [string, string[], number] => [`profile.facts.${index}.skills`, fact.skills, 30])
  ];
  for (const [path, values, limit] of lists) {
    if (values.length > limit) errors[path] = `Use at most ${limit} entries.`;
    else if (values.some(value => !value.trim() || value.length > 200)) errors[path] = 'Each entry must contain 1–200 characters.';
  }
  return errors;
}
