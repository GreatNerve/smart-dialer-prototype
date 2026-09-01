import { useCallback, useEffect, useMemo, useState } from "react";

const API = import.meta.env.VITE_API_BASE || "http://localhost:8000";

type Decision = {
  id: string;
  desired: number;
  approved: number;
  outcome: string;
  mode: string;
  reason_codes: string[];
  created_at?: string;
};

type Snapshot = {
  id: string;
  name: string;
  status: string;
  pacing_mode: string;
  force_progressive: boolean;
  provider_name: string;
  time_scale: number;
  overdial_allowance: number;
  abandon_rate_ceiling: number;
  agents: Record<string, number>;
  calls: Record<string, number>;
  metrics: {
    answer_rate_ewma: number;
    setup_sec_ewma: number;
    talk_sec_ewma: number;
    samples: number;
    aggressiveness: number;
    abandons_window: number;
    answered_window: number;
    abandon_rate: number;
    last_approved: number;
  };
  pacing_timeline: Decision[];
  decisions: Decision[];
  provider_health: {
    provider_name: string;
    error_rate_ewma: number;
    p95_latency_ms: number;
    circuit_open_until: string | null;
    circuit_open: boolean;
  };
};

type CampaignListItem = {
  id: string;
  name: string;
  status: string;
  provider_name?: string;
  pacing_mode?: string;
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || res.statusText);
  }
  return res.json() as Promise<T>;
}

function sum(data: Record<string, number> | undefined) {
  return Object.values(data || {}).reduce((a, b) => a + b, 0);
}

function StateBars({ data, tone = "ok" }: { data: Record<string, number>; tone?: "ok" | "warn" }) {
  const entries = Object.entries(data || {}).sort((a, b) => b[1] - a[1]);
  const total = Math.max(1, sum(data));
  if (!entries.length) return <div className="empty">No data yet</div>;
  return (
    <div className="bars">
      {entries.map(([k, v]) => (
        <div className="bar-row" key={k}>
          <span>{k}</span>
          <div className={`bar-track ${tone === "warn" ? "warn" : ""}`}>
            <i style={{ width: `${(v / total) * 100}%` }} />
          </div>
          <span className="mono">{v}</span>
        </div>
      ))}
    </div>
  );
}

function PacingSpark({ points }: { points: Decision[] }) {
  const w = 560;
  const h = 120;
  const pad = 8;
  if (!points.length) {
    return <div className="empty">Start the campaign to see desired vs approved over time</div>;
  }
  const maxY = Math.max(1, ...points.map((p) => Math.max(p.desired, p.approved)));
  const step = points.length > 1 ? (w - pad * 2) / (points.length - 1) : 0;
  const toY = (v: number) => h - pad - (v / maxY) * (h - pad * 2);
  const toX = (i: number) => pad + i * step;
  const path = (key: "desired" | "approved") =>
    points
      .map((p, i) => `${i === 0 ? "M" : "L"} ${toX(i).toFixed(1)} ${toY(p[key]).toFixed(1)}`)
      .join(" ");

  return (
    <>
      <svg className="spark" viewBox={`0 0 ${w} ${h}`} role="img" aria-label="Pacing timeline">
        <path d={path("desired")} fill="none" stroke="#f4a261" strokeWidth="2.5" strokeLinecap="round" />
        <path d={path("approved")} fill="none" stroke="#2ec4b6" strokeWidth="2.5" strokeLinecap="round" />
        {points.map((p, i) => (
          <circle key={p.id} cx={toX(i)} cy={toY(p.approved)} r="2.5" fill="#2ec4b6" />
        ))}
      </svg>
      <div className="spark-legend">
        <span><span className="dot desired" />Desired</span>
        <span><span className="dot approved" />Approved</span>
        <span>max {maxY}</span>
      </div>
    </>
  );
}

function SkeletonPanel() {
  return (
    <>
      <div className="skeleton" style={{ width: "40%" }} />
      <div className="skeleton" />
      <div className="skeleton" style={{ width: "70%" }} />
      <div className="skeleton" style={{ width: "55%" }} />
    </>
  );
}

export default function App() {
  const [campaigns, setCampaigns] = useState<CampaignListItem[]>([]);
  const [campaignId, setCampaignId] = useState("");
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sseState, setSseState] = useState<"connecting" | "live" | "polling">("connecting");
  const [busy, setBusy] = useState<string | null>(null);
  const [providerChoice, setProviderChoice] = useState("mock_a");

  const loadCampaigns = useCallback(async () => {
    try {
      setError(null);
      const list = await api<CampaignListItem[]>("/api/campaigns");
      setCampaigns(list);
      if (!campaignId && list[0]) setCampaignId(list[0].id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [campaignId]);

  useEffect(() => {
    void loadCampaigns();
  }, [loadCampaigns]);

  useEffect(() => {
    if (!campaignId) return;
    let es: EventSource | null = null;
    let cancelled = false;
    let pollId = 0;
    setLoading(true);
    setSseState("connecting");

    const applySnap = (s: Snapshot) => {
      setSnap(s);
      setLoading(false);
      setError(null);
      setProviderChoice(s.provider_name);
    };

    const poll = async () => {
      try {
        const s = await api<Snapshot>(`/api/campaigns/${campaignId}/snapshot`);
        if (!cancelled) applySnap(s);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void poll();
    try {
      es = new EventSource(`${API}/api/stream?campaign_id=${campaignId}`);
      es.addEventListener("snapshot", (ev) => {
        applySnap(JSON.parse((ev as MessageEvent).data));
        setSseState("live");
      });
      es.addEventListener("delta", (ev) => {
        const data = JSON.parse((ev as MessageEvent).data);
        if (data.snapshot) applySnap(data.snapshot);
        setSseState("live");
      });
      es.addEventListener("error", () => {
        /* EventSource also fires onerror for stream errors */
      });
      es.onerror = () => {
        setSseState("polling");
        if (!pollId) pollId = window.setInterval(() => void poll(), 2000);
      };
    } catch {
      setSseState("polling");
      pollId = window.setInterval(() => void poll(), 2000);
    }

    return () => {
      cancelled = true;
      es?.close();
      if (pollId) window.clearInterval(pollId);
    };
  }, [campaignId]);

  const abandonPct = useMemo(() => {
    if (!snap) return 0;
    return (snap.metrics.abandon_rate || 0) * 100;
  }, [snap]);

  const ceilingPct = (snap?.abandon_rate_ceiling || 0.03) * 100;

  const run = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
      await loadCampaigns();
      if (campaignId) {
        setSnap(await api<Snapshot>(`/api/campaigns/${campaignId}/snapshot`));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const createDemo = (provider = "mock_a") =>
    run("create", async () => {
      const created = await api<{ id: string }>("/api/campaigns", {
        method: "POST",
        body: JSON.stringify({
          name: `demo-${provider}-${Date.now().toString().slice(-5)}`,
          pacing_mode: "auto",
          provider_name: provider,
          time_scale: 60,
          overdial_allowance: 5,
          answer_rate_sim: 0.5,
          talk_sec_sim: 90,
        }),
      });
      await api(`/api/campaigns/${created.id}/seed`, {
        method: "POST",
        body: JSON.stringify({ agents: 50, contacts: 400 }),
      });
      setCampaignId(created.id);
    });

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">SmartDialer · Operator</div>
          <h1>Campaign control & chaos</h1>
          <div className="sub">
            Progressive + predictive pacing · Safety Controller · live SSE
          </div>
        </div>
        <div className="controls">
          <select
            value={campaignId}
            onChange={(e) => setCampaignId(e.target.value)}
            aria-label="Campaign"
          >
            <option value="">Select campaign</option>
            {campaigns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.status})
              </option>
            ))}
          </select>
          <button className="btn" disabled={!!busy} onClick={() => void createDemo("mock_a")}>
            New A campaign
          </button>
          <button className="btn secondary" disabled={!!busy} onClick={() => void createDemo("mock_b")}>
            New B (messy)
          </button>
        </div>
      </header>

      {error && <div className="banner err">Error: {error}</div>}
      {sseState === "polling" && (
        <div className="banner warn">SSE disconnected — falling back to polling every 2s</div>
      )}
      {sseState === "live" && snap && (
        <div className="banner info">Live stream connected · {snap.name}</div>
      )}

      <div className="grid">
        <section className="panel span-4">
          <h2>Campaign</h2>
          {loading && !snap ? (
            <SkeletonPanel />
          ) : !snap ? (
            <div className="empty">Create a demo campaign to begin</div>
          ) : (
            <>
              <div className="stat"><span>Status</span><span className="pill">{snap.status}</span></div>
              <div className="stat"><span>Mode</span><span className="mono">{snap.pacing_mode}</span></div>
              <div className="stat">
                <span>Force progressive</span>
                <span className={`pill ${snap.force_progressive ? "warn" : ""}`}>
                  {snap.force_progressive ? "ON" : "off"}
                </span>
              </div>
              <div className="stat"><span>Overdial allowance</span><strong>{snap.overdial_allowance}</strong></div>
              <div className="stat"><span>Time scale</span><strong>{snap.time_scale}×</strong></div>
              <div className="row" style={{ marginTop: "0.9rem" }}>
                <button
                  className="btn"
                  disabled={!campaignId || !!busy}
                  onClick={() =>
                    void run("start", () =>
                      api(`/api/campaigns/${campaignId}/start`, { method: "POST" })
                    )
                  }
                >
                  Start
                </button>
                <button
                  className="btn secondary"
                  disabled={!campaignId || !!busy}
                  onClick={() =>
                    void run("stop", () =>
                      api(`/api/campaigns/${campaignId}/stop`, { method: "POST" })
                    )
                  }
                >
                  Stop
                </button>
              </div>
            </>
          )}
        </section>

        <section className="panel span-4">
          <h2>Provider health</h2>
          {!snap ? (
            <SkeletonPanel />
          ) : (
            <>
              <div className="stat">
                <span>Provider</span>
                <strong>{snap.provider_health.provider_name}</strong>
              </div>
              <div className="stat">
                <span>Circuit</span>
                <span className={`pill ${snap.provider_health.circuit_open ? "bad" : ""}`}>
                  {snap.provider_health.circuit_open ? "OPEN" : "closed"}
                </span>
              </div>
              <div className="stat">
                <span>Error EWMA</span>
                <strong>{(snap.provider_health.error_rate_ewma * 100).toFixed(1)}%</strong>
              </div>
              <div className="stat">
                <span>p95 latency</span>
                <strong>{snap.provider_health.p95_latency_ms.toFixed(0)} ms</strong>
              </div>
              <div className="row" style={{ marginTop: "0.8rem" }}>
                <select
                  value={providerChoice}
                  onChange={(e) => setProviderChoice(e.target.value)}
                  aria-label="Switch provider"
                >
                  <option value="mock_a">mock_a (fast)</option>
                  <option value="mock_b">mock_b (messy)</option>
                </select>
                <button
                  className="btn secondary"
                  disabled={!campaignId || !!busy}
                  onClick={() =>
                    void run("provider", () =>
                      api(`/api/campaigns/${campaignId}`, {
                        method: "PATCH",
                        body: JSON.stringify({ provider_name: providerChoice }),
                      })
                    )
                  }
                >
                  Apply provider
                </button>
              </div>
            </>
          )}
        </section>

        <section className="panel span-4">
          <h2>Pacing metrics</h2>
          {!snap ? (
            <SkeletonPanel />
          ) : (
            <div className="kpi">
              <div className="kpi-card">
                <div className="label">Answer EWMA</div>
                <div className="value">{(snap.metrics.answer_rate_ewma * 100).toFixed(0)}%</div>
              </div>
              <div className="kpi-card">
                <div className="label">Aggressiveness</div>
                <div className="value">{snap.metrics.aggressiveness.toFixed(2)}</div>
              </div>
              <div className="kpi-card">
                <div className="label">Setup EWMA</div>
                <div className="value">{snap.metrics.setup_sec_ewma.toFixed(1)}s</div>
              </div>
              <div className="kpi-card">
                <div className="label">Talk EWMA</div>
                <div className="value">{snap.metrics.talk_sec_ewma.toFixed(0)}s</div>
              </div>
            </div>
          )}
        </section>

        <section className="panel span-6">
          <h2>Agents · {sum(snap?.agents)} staffed</h2>
          {snap ? <StateBars data={snap.agents} /> : <SkeletonPanel />}
        </section>

        <section className="panel span-6">
          <h2>Calls · {sum(snap?.calls)} total</h2>
          {snap ? <StateBars data={snap.calls} tone="warn" /> : <SkeletonPanel />}
        </section>

        <section className="panel span-7">
          <h2>Pacing timeline · desired vs approved</h2>
          <PacingSpark points={snap?.pacing_timeline || []} />
        </section>

        <section className="panel span-5">
          <h2>Abandonment vs ceiling ({ceilingPct.toFixed(0)}%)</h2>
          {!snap ? (
            <SkeletonPanel />
          ) : (
            <>
              <div className="stat">
                <span>Rolling rate</span>
                <strong>{abandonPct.toFixed(2)}%</strong>
              </div>
              <div className={`bar-track ${abandonPct > ceilingPct ? "bad" : "warn"}`} style={{ margin: "0.6rem 0" }}>
                <i style={{ width: `${Math.min(100, (abandonPct / Math.max(ceilingPct, 0.01)) * 100)}%` }} />
              </div>
              <div className="stat">
                <span>Window answered / abandons</span>
                <strong>
                  {snap.metrics.answered_window} / {snap.metrics.abandons_window}
                </strong>
              </div>
              <div className="stat">
                <span>Last approved</span>
                <strong>{snap.metrics.last_approved}</strong>
              </div>
              <div className="stat">
                <span>Samples</span>
                <strong>{snap.metrics.samples}</strong>
              </div>
            </>
          )}
        </section>

        <section className="panel span-12">
          <h2>Chaos panel</h2>
          <div className="row">
            <button
              className="btn danger"
              disabled={!campaignId || !!busy}
              onClick={() =>
                void run("drop", () =>
                  api("/api/chaos/drop-agents", {
                    method: "POST",
                    body: JSON.stringify({ campaign_id: campaignId, count: 40 }),
                  })
                )
              }
            >
              Drop 40 agents
            </button>
            <button
              className="btn secondary"
              disabled={!!busy}
              onClick={() =>
                void run("fail-on", () =>
                  api("/api/chaos/provider", {
                    method: "POST",
                    body: JSON.stringify({
                      provider: snap?.provider_name || "mock_a",
                      failing: true,
                    }),
                  })
                )
              }
            >
              Provider failing ON
            </button>
            <button
              className="btn secondary"
              disabled={!!busy}
              onClick={() =>
                void run("fail-off", () =>
                  api("/api/chaos/provider", {
                    method: "POST",
                    body: JSON.stringify({
                      provider: snap?.provider_name || "mock_a",
                      failing: false,
                    }),
                  })
                )
              }
            >
              Provider OK
            </button>
            <button
              className="btn secondary"
              disabled={!campaignId || !!busy}
              onClick={() =>
                void run("force", () =>
                  api("/api/chaos/force-progressive", {
                    method: "POST",
                    body: JSON.stringify({ campaign_id: campaignId, enabled: true }),
                  })
                )
              }
            >
              Force progressive
            </button>
            <button
              className="btn ghost"
              disabled={!campaignId || !!busy}
              onClick={() =>
                void run("unforce", () =>
                  api("/api/chaos/force-progressive", {
                    method: "POST",
                    body: JSON.stringify({ campaign_id: campaignId, enabled: false }),
                  })
                )
              }
            >
              Clear force
            </button>
            <button
              className="btn danger"
              disabled={!!busy}
              onClick={() =>
                void run("kill", () => api("/api/chaos/kill-worker", { method: "POST" }))
              }
            >
              Kill one worker
            </button>
          </div>
          {busy && <div className="empty" style={{ marginTop: 10 }}>Working: {busy}…</div>}
        </section>

        <section className="panel span-12">
          <h2>Safety Controller decisions</h2>
          {!snap?.decisions?.length ? (
            <div className="empty">No decisions yet — start a campaign with workers running</div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Desired</th>
                  <th>Approved</th>
                  <th>Outcome</th>
                  <th>Mode</th>
                  <th>Codes</th>
                </tr>
              </thead>
              <tbody>
                {snap.decisions.map((d) => (
                  <tr key={d.id}>
                    <td className="mono">
                      {d.created_at ? new Date(d.created_at).toLocaleTimeString() : "—"}
                    </td>
                    <td className="mono">{d.desired}</td>
                    <td className="mono">{d.approved}</td>
                    <td>{d.outcome}</td>
                    <td>{d.mode}</td>
                    <td>{(d.reason_codes || []).join(", ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  );
}
