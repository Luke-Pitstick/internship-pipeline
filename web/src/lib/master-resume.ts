export interface MasterResumeResult {
  state: 'idle' | 'pending' | 'running' | 'failed' | 'ready' | 'stale';
  profile_revision: number;
  template_revision: string;
  key?: string;
  error?: string;
  pages?: number;
  completed_at?: string;
  preview_url?: string;
  download_url?: string;
  omitted_unknown?: number;
}
