// Every request goes through here so a failing call reads the same everywhere.
// Vite proxies /api to FastAPI in dev; in the built app they share an origin.
export async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const d = JSON.parse(text).detail;
      // FastAPI: a string, or a list of validation errors
      detail = typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg).join("; ") : text;
    } catch {
      // not JSON; show the text as is
    }
    const err = new Error(detail.slice(0, 200));
    err.status = res.status;
    throw err;
  }
  return res.json();
}
