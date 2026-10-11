export interface Session { authenticated: boolean; claimed: boolean; csrf: string }
export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly fields: {field: string; message: string}[] = []) { super(message); }
}
export class Api {
  csrf = '';
  constructor(private expired: () => void) {}
  async request<T>(path: string, body?: unknown): Promise<T> {
    const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store',
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json', 'X-CSRF-Token': this.csrf },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 401 && path !== '/api/login') this.expired();
      throw new ApiError(typeof result.detail === 'string' ? result.detail : 'The request failed. Please retry.', response.status, result.fields ?? []);
    }
    return result as T;
  }
  async session() { const session = await this.request<Session>('/api/session'); this.csrf = session.csrf; return session; }
  async upload<T>(path: string, file: File): Promise<T> {
    const response = await fetch(path, {method: 'POST', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/octet-stream', 'X-CSRF-Token': this.csrf}, body: file});
    const result = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401) this.expired();
      throw new ApiError(typeof result?.detail === 'string' ? result.detail : response.status === 413
        ? 'The server rejected this file as too large. Choose a smaller PDF or DOCX.'
        : 'The upload could not be completed. Check the connection and try again.', response.status);
    }
    if (!result) throw new ApiError('The server returned an unreadable upload response. Please try again.', response.status);
    return result as T;
  }
}
