import type { Category, Profile, Preferences } from '#lib/settings.ts';
export const steps = ['models', 'profile', 'filters', 'search', 'integrations', 'review', 'results'] as const;
export type Step = typeof steps[number];
export const labels: Record<Step, string> = {models:'Models', profile:'Profile & résumé', filters:'Job filters', search:'Saved search', integrations:'Optional integrations', review:'Configuration preview', results:'First results'};
export const category: Partial<Record<Step, Category>> = {models:'AI Models', profile:'Profile', filters:'Job Filters', search:'Sources', integrations:'Notifications & Integrations'};
export const correction = (step: Step) => `/settings/?setup=1#${encodeURIComponent(category[step] ?? 'Sources')}`;
export interface Setup {
  step: Step; reviewed: Step[]; defer_models: boolean; email: 'skip'|'connect'|null; sheets:'skip'|'connect'|null; complete:boolean; run_id:string|null;
  preview_token:string; blockers:{step:Step;message:string}[];
  preview: {
    profile_revision:number; confirmed_facts:number; profile:Profile; preferences:Preferences; defer_models:boolean;
    models:Record<string,{revision:number;status:string;model:string|null}>;
    searches:{id:string;name:string;source:string;board:string;search_term:string;paused:boolean;max_jobs:number;max_calls:number;max_tokens:number;daily_at:string|null;timezone:string}[];
    generation:{enabled:boolean;minimum_fit:number;recommendation:string;eligibility:string};
    email:{choice:string|null;status:string;enabled:boolean}; sheets:{choice:string|null;status:string;enabled:boolean};
  };
  run:{id:string;name:string;stage:string;collected:number;evaluated:number;pending:number;recommended:number;source_error:string|null;evaluation_error_codes:string[]}|null;
}
