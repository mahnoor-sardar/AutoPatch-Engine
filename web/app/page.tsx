async function loadHealth() {
  const base = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  try {
    const res = await fetch(`${base}/health`, { cache: "no-store" });
    if (!res.ok) {
      return { ok: false, postgres: false, redis: false, error: `HTTP ${res.status}` };
    }
    return await res.json();
  } catch (err) {
    return { ok: false, postgres: false, redis: false, error: String(err) };
  }
}

export default async function Page() {
  const health = await loadHealth();
  return (
    <main className="mx-auto max-w-lg p-8">
      <h1 className="text-2xl font-semibold">AutoPatch Engine</h1>
      <p className="mt-2 text-slate-400">Backend health (Weeks 1–2 status page)</p>
      <pre className="mt-6 rounded-lg bg-slate-900 p-4 text-sm">{JSON.stringify(health, null, 2)}</pre>
    </main>
  );
}
