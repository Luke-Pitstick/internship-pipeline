export const categories = ['Profile', 'Job Filters', 'Sources', 'Resume Generation', 'AI Models', 'Notifications & Integrations', 'Diagnostics'] as const;
export type Category = typeof categories[number];
export type Confirmation = 'confirmed' | 'unknown';
export interface Fact {
  id: string; kind: 'experience'|'project'|'skill'; status: Confirmation; text: string; skills: string[];
  title: string; company: string; location: string; start_date: string|null; end_date: string|null;
  current: boolean; links: string[];
}
export function newFact(kind: Fact['kind']): Fact {
  return {id: crypto.randomUUID(), kind, status: 'unknown', text: '', skills: [], title: '', company: '', location: '', start_date: null, end_date: null, current: false, links: []};
}
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
    const path = `profile.facts.${index}`;
    if (fact.status === 'confirmed' && !fact.text.trim() && !(fact.kind !== 'skill' && fact.title.trim())) errors[`${path}.text`] = 'Add a title or description before confirming this entry.';
    if (fact.start_date && fact.end_date && fact.end_date < fact.start_date) errors[`${path}.end_date`] = 'End date must be on or after the start date.';
    if (fact.links.some(link => { try { return !['https:', 'http:'].includes(new URL(link).protocol) || link.length > 2048; } catch { return true; } })) errors[`${path}.links`] = 'Enter complete links starting with https:// or http://.';
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
    ['preferences.soft.roles', snapshot.preferences.soft.roles, 30],
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
