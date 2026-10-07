export type JobStatus = 'To review' | 'Applied';
export interface Assessment {
  identity: string; recommendation: 'recommended' | 'review'; normalized_fit: number;
  profile_revision: number; connection_revision: number; job_revision: string;
  rubric_revision: string; selected_model: string; effective_model: string; assessed_at: number;
  criteria: Record<string, {outcome: string; confidence: number; probabilities: Record<string, number>; evidence_id: string; evidence_probability: number}>;
  dimensions: Record<string, {normalized: number; weight: number; confidence: number}>;
  evidence: Record<string, string>; candidate_evidence: Record<string, string>; uncertainty: string[];
  input_tokens: number; output_tokens: number;
}
export interface Evaluation {
  state: string; result: Assessment | null; error?: string | null;
  attempts?: {started: number; completed: number | null; status: string; input_tokens: number | null; output_tokens: number | null; reserved_tokens: number}[];
}
export interface Job {
  id: string;
  title: string;
  company: string;
  location: string | null;
  postedAt: string | null;
  firstObservedAt: string;
  deadline: string | null;
  score: number | null;
  eligibility: 'Eligible' | 'Needs review' | 'Pending' | 'Evaluation error';
  evaluation?: Evaluation;
  workspace?: {notes: string; saved: boolean; dismissed: boolean; decision: string | null; reason: string; history: {decision: string | null; reason: string; at: number; assessment_identity: string}[]};
  status: JobStatus;
  appliedAt: string | null;
  description: string;
  descriptionTruncated?: boolean;
  applicationUrl: string;
  resumeUrl: string | null;
}
export type SortField = 'postedAt' | 'firstObservedAt' | 'company' | 'title' | 'location' | 'deadline' | 'score';
export interface JobsQuery {
  page: number;
  pageSize: number;
  search: string;
  status: 'All' | 'Recommendations' | 'Needs review' | 'Saved' | 'Applied' | 'Rejected';
  sort: SortField;
  direction: 'asc' | 'desc';
}
export interface JobsPage {
  rows: Job[];
  total: number;
  page: number;
  pages: number;
}
export const formatDate = (value: string | null) => {
  if (!value) return 'Not provided';
  const date = new Date(value);
  return Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(date)
    : value;
};
