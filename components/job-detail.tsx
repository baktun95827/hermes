"use client";

import { useEffect, useState } from "react";
import { RefreshCcw } from "lucide-react";
import { StatusPill } from "./status-pill";

type JobPayload = {
  job_id: string;
  status?: {
    status?: string;
    provider?: string;
    model?: string;
    paths?: Record<string, string>;
    error?: string;
  };
  summary?: string;
  memory_update?: unknown;
  memory_audit?: unknown;
  log_tail?: string;
};

export function JobDetail({ initialPayload }: { initialPayload: JobPayload }) {
  const [payload, setPayload] = useState<JobPayload>(initialPayload);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const status = payload.status?.status ?? "created";

  async function refresh() {
    setIsRefreshing(true);
    try {
      const response = await fetch(`/api/jobs/${payload.job_id}`, { cache: "no-store" });
      if (response.ok) setPayload((await response.json()) as JobPayload);
    } finally {
      setIsRefreshing(false);
    }
  }

  useEffect(() => {
    if (status !== "created" && status !== "running") return;
    const handle = window.setInterval(refresh, 1500);
    return () => window.clearInterval(handle);
  }, [status]);

  return (
    <div className="artifact-grid">
      <section className="panel">
        <div className="panel-header">
          <div>
            <h1 className="page-title mono">{payload.job_id}</h1>
            <p className="page-copy">
              Provider: <span className="mono">{payload.status?.provider ?? "pending"}</span>, model:{" "}
              <span className="mono">{payload.status?.model ?? "pending"}</span>
            </p>
          </div>
          <div className="actions">
            <StatusPill status={status} />
            <button className="button secondary" type="button" onClick={refresh} disabled={isRefreshing}>
              <RefreshCcw aria-hidden="true" />
              Refresh job
            </button>
          </div>
        </div>
        {payload.status?.error ? <div className="panel-body notice">{payload.status.error}</div> : null}
      </section>

      <Artifact title="Summary" value={payload.summary || "summary not ready"} raw />
      <Artifact title="Status JSON" value={payload.status ?? {}} />
      <Artifact title="Memory Update" value={payload.memory_update ?? {}} />
      <Artifact title="Memory Audit" value={payload.memory_audit ?? {}} />
      <Artifact title="Worker Log" value={payload.log_tail || "log not ready"} raw />
    </div>
  );
}

function Artifact({ title, value, raw = false }: { title: string; value: unknown; raw?: boolean }) {
  return (
    <section className="artifact-panel">
      <h2>{title}</h2>
      <pre>{raw ? String(value) : JSON.stringify(value, null, 2)}</pre>
    </section>
  );
}
