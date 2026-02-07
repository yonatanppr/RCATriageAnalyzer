import { useEffect, useMemo, useState } from "react";

type Incident = {
  id: string;
  service: string;
  env: string;
  status: string;
  updated_at: string;
};

const API_BASE = (import.meta as any).env.VITE_API_BASE || "http://localhost:8000";

function authHeaders(token: string) {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

export function App() {
  const [token, setToken] = useState<string>(() => localStorage.getItem("iats_token") || "dev-shared-token");
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [evidence, setEvidence] = useState<any>(null);
  const [report, setReport] = useState<any>(null);
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [statusBusy, setStatusBusy] = useState(false);
  const [focusedArtifactId, setFocusedArtifactId] = useState<string | null>(null);

  const refreshIncident = async (incidentId: string) => {
    const [d, e, r] = await Promise.all([
      fetch(`${API_BASE}/v1/incidents/${incidentId}`, { headers: authHeaders(token) }).then((res) => res.json()),
      fetch(`${API_BASE}/v1/incidents/${incidentId}/evidence`, { headers: authHeaders(token) }).then((res) => res.json()),
      fetch(`${API_BASE}/v1/incidents/${incidentId}/report`, { headers: authHeaders(token) }).then((res) => res.json()),
    ]);
    setDetail(d);
    setEvidence(e);
    setReport(r);
  };

  useEffect(() => {
    localStorage.setItem("iats_token", token);
    fetch(`${API_BASE}/v1/incidents`, { headers: authHeaders(token) })
      .then((r) => r.json())
      .then((data) => {
        if (!Array.isArray(data)) {
          setIncidents([]);
          return;
        }
        setIncidents(data);
        if (data.length > 0 && !selected) {
          setSelected(data[0].id);
        }
      });
  }, [token]);

  useEffect(() => {
    if (!selected) return;
    refreshIncident(selected);
  }, [selected, token]);

  const submitDecision = async (decision: "approve" | "reject") => {
    if (!selected) return;
    setDecisionBusy(true);
    try {
      const body: any = { decision };
      if (decision === "reject") {
        body.notes = "Rejected in UI review";
      }
      await fetch(`${API_BASE}/v1/incidents/${selected}/decision`, {
        method: "POST",
        headers: authHeaders(token),
        body: JSON.stringify(body),
      });
      await refreshIncident(selected);
    } finally {
      setDecisionBusy(false);
    }
  };

  const updateIncidentStatus = async (status: "mitigated" | "resolved" | "postmortem_required") => {
    if (!selected) return;
    setStatusBusy(true);
    try {
      await fetch(`${API_BASE}/v1/incidents/${selected}/status`, {
        method: "POST",
        headers: authHeaders(token),
        body: JSON.stringify({ status }),
      });
      await refreshIncident(selected);
    } finally {
      setStatusBusy(false);
    }
  };

  const submitFeedback = async (helpful: boolean) => {
    if (!selected) return;
    await fetch(`${API_BASE}/v1/incidents/${selected}/feedback`, {
      method: "POST",
      headers: authHeaders(token),
      body: JSON.stringify({ helpful, correct: helpful }),
    });
  };

  const artifacts = useMemo(() => evidence?.artifacts || [], [evidence]);
  const artifactById = useMemo(() => {
    const map = new Map<string, any>();
    artifacts.forEach((a: any) => {
      if (a.artifact_id) map.set(a.artifact_id, a);
    });
    return map;
  }, [artifacts]);

  const timeline = useMemo(() => artifacts.find((a: any) => a.type === "timeline")?.events || [], [artifacts]);
  const signatures = useMemo(() => artifacts.find((a: any) => a.type === "log_signatures")?.signatures || [], [artifacts]);
  const snippets = useMemo(() => artifacts.filter((a: any) => a.type === "repo_snippet"), [artifacts]);

  const renderRefs = (refs: any[] = []) => (
    <ul>
      {refs.map((ref: any, idx: number) => (
        <li key={`${ref.artifact_id}-${idx}`}>
          <button onClick={() => setFocusedArtifactId(ref.artifact_id)}>
            {ref.artifact_id} :: {ref.pointer}
          </button>
        </li>
      ))}
    </ul>
  );

  return (
    <div className="layout">
      <aside>
        <h2>Auth</h2>
        <input value={token} onChange={(e) => setToken(e.target.value)} />
        <h2>Incidents</h2>
        {incidents.map((incident) => (
          <button key={incident.id} onClick={() => setSelected(incident.id)} className={selected === incident.id ? "active" : ""}>
            <div>{incident.service}</div>
            <small>{incident.env} | {incident.status}</small>
          </button>
        ))}
      </aside>
      <main>
        {!detail && <p>No incident selected.</p>}
        {detail && (
          <>
            <h1>{detail.service} ({detail.env})</h1>
            <p><b>Alert:</b> {detail.alert_title || "n/a"}</p>
            <p><b>Alert time:</b> {detail.alert_fired_at ? new Date(detail.alert_fired_at).toLocaleString() : "n/a"}</p>
            <p><b>Correlation ID:</b> {detail.correlation_id || "n/a"}</p>
            <p><b>Version/SHA:</b> {detail.service_version || "n/a"} / {detail.git_sha || "n/a"}</p>
            <p><b>Owners:</b> {(detail.owners || []).join(", ") || "n/a"}</p>
            <p>Status: <b>{detail.status}</b></p>
            <p>Updated: {new Date(detail.updated_at).toLocaleString()}</p>

            <section>
              <h3>One-click Actions</h3>
              <button onClick={() => window.open(detail.runbook_url || "#", "_blank")}>Open Runbook</button>
              <button onClick={() => window.open(detail.dashboard_url || "#", "_blank")}>Open Dashboard</button>
              <button onClick={() => alert(`Ping owners: ${(detail.owners || []).join(", ")}`)}>Ping Owner</button>
              <button onClick={() => alert(`Ticket template for ${detail.service}`)}>Open Ticket Template</button>
            </section>

            {(detail.status === "triaged" || detail.status === "mitigated" || detail.status === "resolved") && (
              <section>
                <h3>Lifecycle Actions</h3>
                <button onClick={() => updateIncidentStatus("mitigated")} disabled={statusBusy || detail.status !== "triaged"}>
                  Mark Mitigated
                </button>
                <button onClick={() => updateIncidentStatus("resolved")} disabled={statusBusy || (detail.status !== "triaged" && detail.status !== "mitigated")}>
                  Mark Resolved
                </button>
                <button onClick={() => updateIncidentStatus("postmortem_required")} disabled={statusBusy}>
                  Require Postmortem
                </button>
              </section>
            )}

            <section>
              <h3>Timeline</h3>
              {timeline.length === 0 && <p>No timeline events.</p>}
              <ul>
                {timeline.map((evt: any, idx: number) => (
                  <li key={idx}>{evt.time} | {evt.type} | {evt.label}</li>
                ))}
              </ul>
            </section>

            <section>
              <h3>Error Signatures</h3>
              {signatures.map((sig: any) => (
                <div key={sig.signature_id} className="card">
                  <b>{sig.signature_id}</b> ({sig.count})
                  <pre>{(sig.samples || []).join("\n")}</pre>
                </div>
              ))}
            </section>

            <section>
              <h3>Repo Snippets</h3>
              {snippets.length === 0 && <p>No snippets found.</p>}
              {snippets.map((s: any) => (
                <div key={s.snippet_id} className="card">
                  <b>{s.file_path} ({s.start_line}-{s.end_line})</b>
                  <pre>{s.content}</pre>
                </div>
              ))}
            </section>

            <section>
              <h3>Triage Summary Card</h3>
              {report?.summary && (
                <>
                  {report?.decision_required && (
                    <div className="card">
                      <b>Human Decision Required</b>
                      <p>This report is pending review before it is marked triaged.</p>
                      <button onClick={() => submitDecision("approve")} disabled={decisionBusy}>Approve</button>
                      <button onClick={() => submitDecision("reject")} disabled={decisionBusy}>Reject</button>
                    </div>
                  )}
                  <p><b>Summary:</b> {report.summary}</p>
                  <p><b>Mode:</b> {report.mode}</p>
                  <h4>Facts</h4>
                  <ul>
                    {(report.facts || []).map((f: any) => (
                      <li key={f.claim_id}>
                        {f.text}
                        {renderRefs(f.evidence_refs)}
                      </li>
                    ))}
                  </ul>
                  <h4>Top Hypothesis</h4>
                  {(report.hypotheses || []).slice(0, 1).map((h: any) => (
                    <div key={h.rank} className="card">
                      <b>{h.title}</b> ({h.confidence})
                      <p>{h.explanation}</p>
                      <p><b>Disconfirming:</b> {(h.disconfirming_signals || []).join(", ") || "n/a"}</p>
                      <p><b>Missing data:</b> {(h.missing_data || []).join(", ") || "n/a"}</p>
                      {renderRefs(h.evidence_refs)}
                    </div>
                  ))}
                  <h4>Next Checks</h4>
                  <ul>
                    {(report.next_checks || []).map((n: any) => (
                      <li key={n.check_id}>
                        {n.step}
                        {renderRefs(n.evidence_refs)}
                      </li>
                    ))}
                  </ul>
                  <h4>Mitigations</h4>
                  <ul>
                    {(report.mitigations || []).map((m: any) => (
                      <li key={m.mitigation_id}>
                        {m.action} (risk: {m.risk})
                        {renderRefs(m.evidence_refs)}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {!report?.summary && (
                <p>{report?.message || "LLM not configured"} {report?.reason ? `(${report.reason})` : ""}</p>
              )}
            </section>

            {focusedArtifactId && (
              <section>
                <h3>Focused Evidence</h3>
                <pre>{JSON.stringify(artifactById.get(focusedArtifactId), null, 2)}</pre>
              </section>
            )}

            <section>
              <h3>Feedback</h3>
              <button onClick={() => submitFeedback(true)}>Helpful</button>
              <button onClick={() => submitFeedback(false)}>Not Helpful</button>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
