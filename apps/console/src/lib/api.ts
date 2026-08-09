// Central API config. In dev, VITE_API_BASE is unset → same-origin (Vite proxies
// /api/* to localhost:8000). In prod (Vercel), set VITE_API_BASE to the ngrok
// URL so the deployed console reaches your laptop's backend.
//
// The ngrok header is required on the free tier — without it, ngrok returns
// its "Visit Site" HTML instead of the API response, which breaks silently.
export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? "").replace(/\/+$/, "");

const NGROK_HEADERS: Record<string, string> = { "ngrok-skip-browser-warning": "true" };

export function apiUrl(path: string): string {
  if (path.startsWith("http")) return path;
  return `${API_BASE}${path}`;
}

export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers || {});
  for (const [k, v] of Object.entries(NGROK_HEADERS)) headers.set(k, v);
  return fetch(apiUrl(path), { ...init, headers });
}

/**
 * SSE stream via fetch + Streams API — needed because native EventSource can't
 * set custom headers, and ngrok's free tier rejects header-less API calls.
 * Calls onEvent for each parsed data-line JSON payload. Returns a stop() fn.
 */
export function apiEventStream(
  path: string,
  onEvent: (data: unknown) => void,
): () => void {
  const ctrl = new AbortController();
  (async () => {
    try {
      const res = await apiFetch(path, { signal: ctrl.signal });
      if (!res.ok || !res.body) return;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // Each SSE event is separated by a blank line
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) !== -1) {
          const chunk = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          for (const line of chunk.split("\n")) {
            if (!line.startsWith("data:")) continue;
            const payload = line.slice(5).trim();
            if (!payload) continue;
            try { onEvent(JSON.parse(payload)); } catch { /* comment / keepalive */ }
          }
        }
      }
    } catch { /* aborted or network */ }
  })();
  return () => ctrl.abort();
}
