import { parseFastApiErrorBody } from "../api/httpError";

/**
 * fetch() wrapper: throws Error with a readable message from FastAPI `detail`
 * (never log response bodies that might contain secrets — callers handle keys separately).
 */
export async function apiRequest(
  url: string,
  init?: RequestInit,
): Promise<Response> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      parseFastApiErrorBody(text) || `Request failed (${res.status})`,
    );
  }
  return res;
}
