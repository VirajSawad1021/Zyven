export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let why = "";  // the server explains refusals in `detail`: show that, not just the status code
    try { const body = await res.json(); why = typeof body?.detail === "string" ? body.detail : ""; } catch { /* not JSON */ }
    throw new Error(why || `${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
