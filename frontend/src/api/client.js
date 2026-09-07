// Every request goes through here so a failing call reads the same everywhere.
// Vite proxies /api to FastAPI in dev; in the built app they share an origin.
export async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error((await res.text()).slice(0, 200));
  return res.json();
}
