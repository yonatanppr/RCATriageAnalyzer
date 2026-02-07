import { useEffect, useMemo, useState } from "react";

type Incident = {
  id: string;
  service: string;
  env: string;
  status: string;
  updated_at: string;
};

const API_BASE = (import.meta as any).env.VITE_API_BASE || "http://localhost:8000";

export function App() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [evidence, setEvidence] = useState<any>(null);
  const [report, setReport] = useState<any>(null);

  useEffect(() => {
    fetch(`${API_BASE}/v1/incidents`)
      .then((r) => r.json())
      .then((data) => {
        setIncidents(data);
        if (data.length > 0 && !selected) {
          setSelected(data[0].id);
        }
      });
  }, []);

  useEffect(() => {
    if (!selected) return;
    Promise.all([
      fetch(`${API_BASE}/v1/incidents/${selected}`).then((r) => r.json()),
      fetch(`${API_BASE}/v1/incidents/${selected}/evidence`).then((r) => r.json()),
      fetch(`${API_BASE}/v1/incidents/${selected}/report`).then((r) => r.json()),
    ]).then(([d, e, r]) => {
      setDetail(d);
      setEvidence(e);
      setReport(r);
    });
  }, [selected]);

  const patterns = useMemo(() => {
    const summary = evidence?.artifacts?.find((a: any) => a.type === "log_summary");
    return summary?.patterns || [];
  }, [evidence]);

  const snippets = useMemo(() => {
    return (evidence?.artifacts || []).filter((a: any) => a.type === "repo_snippet");
  }, [evidence]);

  return (
    <div className="layout">
      <aside>
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
            <p>Status: <b>{detail.status}</b></p>
            <p>Updated: {new Date(detail.updated_at).toLocaleString()}</p>

            <section>
              <h3>Log Summary</h3>
              {patterns.map((p: any) => (
                <div key={p.pattern_id} className="card">
                  <b>{p.pattern_id}</b> ({p.count})
                  <pre>{p.sample_lines?.join("\n")}</pre>
                </div>
              ))}
            </section>

            <section>
              <h3>Repo Snippets</h3>
              {snippets.length === 0 && <p>No snippets found.</p>}
              {snippets.map((s: any) => (
                <div key={s.snippet_id} className="card">
                  <b>{s.file_path}</b>
                  <pre>{s.content}</pre>
                </div>
              ))}
            </section>

            <section>
              <h3>Triage Report</h3>
              {report?.summary && (
                <>
                  <p><b>Summary:</b> {report.summary}</p>
                  <h4>Symptoms</h4>
                  <ul>{(report.symptoms || []).map((s: any, idx: number) => <li key={idx}>{s.text}</li>)}</ul>
                  <h4>Hypotheses</h4>
                  <ul>{(report.hypotheses || []).map((h: any, idx: number) => <li key={idx}>#{h.rank} {h.title} ({h.confidence})</li>)}</ul>
                  <h4>Verification Steps</h4>
                  <ul>{(report.verification_steps || []).map((v: any, idx: number) => <li key={idx}>{v.step}</li>)}</ul>
                  <h4>Mitigations</h4>
                  <ul>{(report.mitigations || []).map((m: any, idx: number) => <li key={idx}>{m.action} (risk: {m.risk})</li>)}</ul>
                </>
              )}
              {!report?.summary && (
                <p>{report?.message || "LLM not configured"} {report?.reason ? `(${report.reason})` : ""}</p>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
