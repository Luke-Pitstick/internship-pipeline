import type { Category, Profile, Preferences } from '#lib/settings.ts';
export const steps = ['models', 'profile', 'filters', 'integrations', 'review'] as const;
export type Step = typeof steps[number];
export const labels: Record<Step, string> = {models:'Models', profile:'Profile & résumé', filters:'Job filters', integrations:'Optional integrations', review:'Configuration preview'};
export const category: Partial<Record<Step, Category>> = {models:'AI Models', profile:'Profile', filters:'Job Filters', integrations:'Notifications & Integrations'};
export const correction = (step: Step) => `/settings/?setup=1#${encodeURIComponent(category[step] ?? 'Sources')}`;
export interface Setup {
  step: Step; reviewed: Step[]; defer_models: boolean; email: 'skip'|'connect'|null; sheets:'skip'|'connect'|null; complete:boolean;
  preview_token:string; blockers:{step:Step;message:string}[];
  preview: {
    profile_revision:number; confirmed_facts:number; profile:Profile; preferences:Preferences; defer_models:boolean;
    models:Record<string,{revision:number;status:string;model:string|null}>;
    searches:{name:string;source:string;search_term:string;location:string;country:string;sites:string[]}[];
    generation:{enabled:boolean;minimum_fit:number;recommendation:string;eligibility:string};
    email:{choice:string|null;status:string;enabled:boolean}; sheets:{choice:string|null;status:string;enabled:boolean};
  };
}
