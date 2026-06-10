import Link from "next/link";
import type { ReactNode } from "react";
import { Activity, Database, FileSearch, GitCompareArrows, ShieldAlert } from "lucide-react";
import { getDatabaseUrl, getPostgresTargetReadModelV1, type TargetReadMemoryRecord } from "@/packages/signal-radar-core/src";

export const dynamic = "force-dynamic";

type TargetPageProps = {
  params: Promise<{ code: string }>;
};

export default async function TargetPage({ params }: TargetPageProps) {
  const { code } = await params;
  const targetCode = decodeURIComponent(code);
  const databaseUrl = getDatabaseUrl();
  const model = databaseUrl ? await getModel(targetCode) : null;
  const target = model?.overview.target ?? null;
  const memoryCount = model?.overview.counts.memory_records ?? 0;
  const changes = model?.latest_changes ?? [];
  const evidence = model?.evidence ?? [];
  const gates = model?.quality_gates ?? [];

  return (
    <main className="shell target-shell">
      <div className="page-head">
        <div>
          <h1 className="page-title mono">{target?.symbol ?? targetCode.toUpperCase()}</h1>
          <p className="page-copy">
            {target
              ? `${target.display_name} · ${target.asset_type} · ${target.exchange ?? "no exchange"}`
              : "No target record yet. Submit target-coded evidence to create the first projection."}
          </p>
        </div>
        <div className="actions">
          <Link className="button secondary" href={`/evidence?target=${encodeURIComponent(targetCode)}`}>
            <FileSearch aria-hidden="true" />
            Evidence
          </Link>
          <Link className="button secondary" href={`/quality?target=${encodeURIComponent(targetCode)}`}>
            <ShieldAlert aria-hidden="true" />
            Quality
          </Link>
        </div>
      </div>

      {!databaseUrl ? <div className="notice">DATABASE_URL is not set. Target projections are unavailable.</div> : null}
      {databaseUrl && !target ? (
        <div className="notice">Target code {targetCode.toUpperCase()} is not registered yet. Add it through manual ingest with a target code.</div>
      ) : null}

      <section className="stats-grid">
        <Metric icon={<Database aria-hidden="true" />} label="Memory" value={memoryCount} />
        <Metric icon={<GitCompareArrows aria-hidden="true" />} label="Changes" value={changes.length} />
        <Metric icon={<FileSearch aria-hidden="true" />} label="Evidence" value={evidence.length} />
        <Metric icon={<ShieldAlert aria-hidden="true" />} label="Gates" value={gates.length} />
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2 className="panel-title">
            <Activity aria-hidden="true" />
            Target projection
          </h2>
          <span className="muted">{model?.schema_version ?? "target_read_model/v1"}</span>
        </div>
        <div className="target-tabs" aria-label="Target sections">
          <a href="#overview">Overview</a>
          <a href="#fundamentals">Fundamentals</a>
          <a href="#segments">Segments</a>
          <a href="#concepts">Concepts</a>
          <a href="#timeline">Timeline</a>
          <a href="#changes">Changes</a>
          <a href="#evidence">Evidence</a>
          <a href="#quality">Quality</a>
        </div>
      </section>

      <div className="target-grid">
        <section className="artifact-panel" id="overview">
          <h2>Overview</h2>
          <dl className="meta-list">
            <div>
              <dt>Code</dt>
              <dd className="mono">{target?.symbol ?? targetCode.toUpperCase()}</dd>
            </div>
            <div>
              <dt>Name</dt>
              <dd>{target?.display_name ?? "No target record"}</dd>
            </div>
            <div>
              <dt>Country</dt>
              <dd>{target?.country ?? "unknown"}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd className="mono">{target?.updated_at ?? "n/a"}</dd>
            </div>
          </dl>
        </section>

        <MemorySection id="fundamentals" title="Fundamentals" rows={model?.fundamentals.records ?? []} />
        <MemorySection id="segments" title="Segments" rows={model?.segments.records ?? []} />
        <MemorySection id="concepts" title="Concepts" rows={model?.concepts.records ?? []} />
        <MemorySection id="timeline" title="Timeline" rows={model?.timeline.records ?? []} />

        <section className="artifact-panel" id="changes">
          <h2>Latest changes</h2>
          <div className="compact-list">
            {changes.map((change) => (
              <article key={String(change.version_id ?? change.update_id)}>
                <span className="badge">{change.collection}</span>
                <h3>{change.title || change.record_key}</h3>
                <p className="mono muted">v{change.version_number} · {change.operation} · {change.created_at}</p>
                <pre>{JSON.stringify(change.diff, null, 2)}</pre>
              </article>
            ))}
            {!changes.length ? <p className="muted empty-state">No version changes yet.</p> : null}
          </div>
        </section>

        <section className="artifact-panel" id="evidence">
          <h2>Evidence</h2>
          <div className="compact-list">
            {evidence.slice(0, 12).map((item) => (
              <article key={item.evidence_id}>
                <div className="inspection-title">
                  <span className="badge strong">{item.usefulness_status}</span>
                  <span className="badge">{item.evidence_kind}</span>
                  <span className="badge">{item.source_quality}</span>
                </div>
                <h3>{item.title || item.evidence_id}</h3>
                <p>{item.text_excerpt}</p>
                {item.job_id ? (
                  <Link className="table-link mono" href={`/jobs/${item.job_id}`}>
                    {item.job_id}
                  </Link>
                ) : null}
              </article>
            ))}
            {!evidence.length ? <p className="muted empty-state">No evidence snapshots yet.</p> : null}
          </div>
        </section>

        <section className="artifact-panel" id="quality">
          <h2>Quality gates</h2>
          <div className="compact-list">
            {gates.slice(0, 12).map((gate) => (
              <article key={gate.gate_id}>
                <div className="inspection-title">
                  <span className="badge strong">{gate.severity}</span>
                  <span className="badge">{gate.status}</span>
                  <span className="badge">{gate.evidence_kind}</span>
                </div>
                <h3>{gate.subject || gate.gate_type}</h3>
                <p>{gate.reason}</p>
              </article>
            ))}
            {!gates.length ? <p className="muted empty-state">No quality gates yet.</p> : null}
          </div>
        </section>
      </div>
    </main>
  );
}

async function getModel(code: string) {
  try {
    return getPostgresTargetReadModelV1(code);
  } catch {
    return null;
  }
}

function MemorySection({
  id,
  title,
  rows
}: {
  id: string;
  title: string;
  rows: TargetReadMemoryRecord[];
}) {
  return (
    <section className="artifact-panel" id={id}>
      <h2>{title}</h2>
      <div className="compact-list">
        {rows.map((record) => (
          <article key={record.memory_id}>
            <span className="badge">{record.collection}</span>
            <h3>{record.title || record.record_key}</h3>
            <p>{record.preview || "No preview payload."}</p>
            <Link className="table-link mono" href={`/memory/${record.memory_id}`}>
              v{record.current_version}
            </Link>
          </article>
        ))}
        {!rows.length ? <p className="muted empty-state">No {title.toLowerCase()} records yet.</p> : null}
      </div>
    </section>
  );
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: number }) {
  return (
    <div className="metric">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
