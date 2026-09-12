import { profilePath } from './helpers.mjs';
export async function request<T>(path: string, body?: unknown, profileId?: string): Promise<T> {
  const endpoint = profileId === undefined ? path : profilePath(path, profileId);
  const response = await fetch(endpoint, body === undefined ? undefined : body instanceof FormData ? {method: 'POST', body} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item: {loc?: string[]; msg?: string}) => `${item.loc?.slice(1).join('.')}: ${item.msg}`).join('; ') : `Request failed (${response.status})`);
  }
  return data as T;
}
