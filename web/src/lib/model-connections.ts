import type { Api } from '#lib/api.ts';

export type ModelKind = 'jev' | 'general';
export interface ModelConfig { model: string; endpoint: string; timeout_seconds: number; max_output_tokens: number }
export interface ModelConnection {
  configured: boolean; revision: number; tested_revision: number | null; ready: boolean;
  config: ModelConfig | null;
  last_test: { status: string; effective_model: string | null; input_tokens: number | null; output_tokens: number | null } | null;
}
export type ModelConnections = Record<ModelKind, ModelConnection>;
export const endpoints = { jev: 'https://api.typesafe.ai/v1/systemone', general: 'https://api.openai.com/v1/responses' };
export const modelConnections = (api: Api) => ({
  read: () => api.request<ModelConnections>('/api/model-connections'),
  save: (kind: ModelKind, config: ModelConfig, revision: number, key: string) => api.request<ModelConnection>(`/api/model-connections/${kind}/save`, {...config, expected_revision: revision, ...(key ? {api_key: key} : {})}),
  remove: (kind: ModelKind, revision: number) => api.request<ModelConnection>(`/api/model-connections/${kind}/remove`, {expected_revision: revision}),
  test: (kind: ModelKind, revision: number) => api.request<{connection: ModelConnection; status: string; message: string}>(`/api/model-connections/${kind}/test`, {expected_revision: revision})
});
