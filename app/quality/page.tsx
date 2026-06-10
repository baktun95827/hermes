import Link from "next/link";
import { ShieldAlert, SlidersHorizontal } from "lucide-react";
import {
  getDatabaseUrl,
  getPostgresQualityGateStats,
  listPostgresQualityGates,
  type PostgresAdminCount,
  type PostgresQualityGateListItem
} from "@/packages/signal-radar-core/src";

export const dynamic = "force-dynamic";

type QualityPageProps = {
  searchParams: Promise<{
    status?: string;
    severity?: string;
    evidence_kind?: string;
    target?: string;
  }>;
};

const STATUSES = ["all", "allow", "watch", "skip", "block", "needs_agent_recheck"];
const SEVERITIES = ["all", "info", "watch", "warning", "critical"];
const EVIDENCE_KINDS = ["all", "hard_evidence", "weak_evidence", "rumor", "speculation", "contradiction", "unknown"];

export default async function QualityPage({ searchParams }: QualityPageProps) {
  const filters = await searchParams;
  const databaseUrl = getDatabaseUrl();
  const [gates, stats] = databaseUrl ? await Promise.all([safeGates(filters), safeStats()]) : [[], []];

  return (
    <main className="shell">
      <div className="page-head">
        <div>
          <h1 className="page-title">Quality gates</h1>
          <p className="page-copy">
            Exception queue for weak evidence, rumor, speculation, contradictions, duplicate fragments, and agent recheck signals.
          </p>
        </div>
      </div>

      {!databaseUrl ? <div className="notice">DATABASE_URL is not set. Quality gates are unavailable.</div> : null}

      <StatsGrid stats={stats} />

      <section className="panel">
        <div className="panel-header">
          <h2 className="panel-title">
            <SlidersHorizontal aria-hidden="true" />
            Filters
          </h2>
        </div>
        <div className="panel-body filter-stack">
          <FilterRow label="Status" values={STATUSES} active={normalize(filters.status)} param="status" filters={filters} />
          <FilterRow label="Severity" values={SEVERITIES} active={normalize(filters.severity)} param="severity" filters={filters} />
          <FilterRow label="Kind" values={EVIDENCE_KINDS} active={normalize(filters.evidence_kind)} param="evidence_kind" filters={filters} />
        </div>
      </section>

      <section className="panel inspection-panel">
        <div className="panel-header">
          <h2 className="panel-title">
            <ShieldAlert aria-hidden="true" />
            Gate decisions
          </h2>
          <span className="muted">{gates.length} rows</span>
        </div>
        <div className="inspection-list">
          {gates.map((gate) => (
            <QualityGateRow gate={gate} key={gate.gate_id} />
          ))}
          {!gates.length ? <p className="muted empty-state">No quality gates match the current filters.</p> : null}
        </div>
      </section>
    </main>
  );
}

async function safeGates(filters: Awaited<QualityPageProps["searchParams"]>) {
  try {
    return listPostgresQualityGates({
      status: valueOrNull(filters.status),
      severity: valueOrNull(filters.severity),
      evidenceKind: valueOrNull(filters.evidence_kind),
      targetCode: valueOrNull(filters.target),
      limit: 160
    });
  } catch {
    return [];
  }
}

async function safeStats() {
  try {
    return getPostgresQualityGateStats();
  } catch {
    return [];
  }
}

function QualityGateRow({ gate }: { gate: PostgresQualityGateListItem }) {
  return (
    <article className="inspection-row">
      <header>
        <div className="inspection-title">
          <span className={`badge strong severity-${gate.severity}`}>{gate.severity}</span>
          <span className="badge">{gate.status}</span>
          <span className="badge">{gate.evidence_kind}</span>
        </div>
        <time className="mono muted">{gate.created_at}</time>
      </header>

      <h3>{gate.subject || gate.gate_type}</h3>
      <p>{gate.reason || "No reason captured."}</p>

      <footer className="inspection-links">
        {gate.target_code ? (
          <Link className="table-link mono" href={`/targets/${encodeURIComponent(gate.target_code)}`}>
            {gate.target_code}
          </Link>
        ) : (
          <span className="muted">no target</span>
        )}
        {gate.job_id ? (
          <Link className="table-link mono" href={`/jobs/${gate.job_id}`}>
            {gate.job_id}
          </Link>
        ) : null}
        {gate.evidence_id ? (
          <Link className="table-link" href={`/evidence?target=${encodeURIComponent(gate.target_code ?? "")}`}>
            evidence {gate.evidence_id}
          </Link>
        ) : null}
        <span className="muted">{gate.gate_type}</span>
        <span className="muted">{gate.evidence_strength}</span>
        <span className="muted">{gate.verification_status}</span>
      </footer>
    </article>
  );
}

function StatsGrid({ stats }: { stats: PostgresAdminCount[] }) {
  const primary = stats.filter((row) => row.scope === "status" || row.scope === "severity").slice(0, 8);
  if (!primary.length) return null;
  return (
    <section className="stats-grid compact">
      {primary.map((row) => (
        <div className="metric compact" key={`${row.scope}:${row.label}`}>
          <span>{row.scope}</span>
          <strong>{row.count}</strong>
          <code>{row.label}</code>
        </div>
      ))}
    </section>
  );
}

function FilterRow({
  label,
  values,
  active,
  param,
  filters
}: {
  label: string;
  values: string[];
  active: string;
  param: "status" | "severity" | "evidence_kind";
  filters: Awaited<QualityPageProps["searchParams"]>;
}) {
  return (
    <div className="filter-row">
      <span>{label}</span>
      <div className="segmented">
        {values.map((value) => (
          <Link className={active === value ? "active" : ""} href={filterHref("/quality", filters, param, value)} key={value}>
            {value}
          </Link>
        ))}
      </div>
    </div>
  );
}

function filterHref(
  pathname: string,
  filters: Awaited<QualityPageProps["searchParams"]>,
  key: "status" | "severity" | "evidence_kind",
  value: string
): string {
  const params = new URLSearchParams();
  for (const [name, current] of Object.entries(filters)) {
    if (current && current !== "all" && name !== key) params.set(name, current);
  }
  if (value !== "all") params.set(key, value);
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

function normalize(value?: string): string {
  return valueOrNull(value) ?? "all";
}

function valueOrNull(value?: string): string | null {
  const text = String(value ?? "").trim();
  return text && text !== "all" ? text : null;
}
