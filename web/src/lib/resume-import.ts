import type { Snapshot } from './settings';
export interface SourceLine { id: string; location: string; text: string }
export interface ImportSelection {
  line_id: string; kind: 'name'|'email'|'education'|'experience'|'project'|'skill';
  selected: boolean; institution: string; degree: string; skills: string[];
  source_line_ids: string[]; value: string;
}
export interface ImportDraft {
  id: string; expected_revision: number; lines: SourceLine[]; suggestions: ImportSelection[];
  removable: {id: string; text: string}[];
}
export interface ImportReview {
  expected_revision: number;
  selections: Omit<ImportSelection, 'selected'>[];
  remove_ids: string[]; confirmed: boolean;
}
export interface ImportPreview {
  before: Snapshot; after: {profile: Snapshot['profile']; preferences: Snapshot['preferences']};
  evidence: {field: string; source_text: string; location: string}[];
}
export function review(draft: ImportDraft, removeIds: string[], confirmed: boolean): ImportReview {
  return {expected_revision: draft.expected_revision, remove_ids: removeIds, confirmed,
    selections: draft.suggestions.filter(item => item.selected).map(({selected: _selected, ...item}) => item)};
}
