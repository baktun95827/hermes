import Link from "next/link";
import { FileSearch, Filter, Link2 } from "lucide-react";
import {
  getDatabaseUrl,
  getPostgresEvidenceStats,
  listPostgresEvidenceItems,
  type PostgresAdminCount,
  type PostgresEvidenceListItem
} from "@/packages/signal-radar-core/src";

export const dynamic = "force-dynamic";

type EvidencePageProps = {
  searchParams: Promise<{
    usefulness_status?: string;
    evidence_kind?: string;
    source_quality?: string;
    target?: string;
  }>;
};

const USEFULNESS = ["all", "useful", "potential", "duplicate", "low_value", "rejected"];
const EVIDENCE_KINDS = ["all", "hard_evidence", "weak_evidence", "rumor", "speculation", "contradiction", "unknown"];
const SOURCE_QUALITY = ["all", "official", "primary", "reputable", "secondary", "social", "manual", "promotional", "unknown"];

export default async function EvidencePage({ searchParams }: EvidencePageProps) {
  const filters = await searchParams;
  const databaseUrl = getDatabaseUrl();
  const [items, stats] = databaseUrl ? await Promise.all([safeItems(filters), safeStats()]) : [[], []];

  return (
    <main className="shell">
      <div className="page-head">
        <div>
          <h1 className="page-title">Evidence ledger</h1>
          <p className="page-copy">
            Useful snapshots, duplicate fragments, weak sources, rumors, and hard evidence retained by the ingestion path.
          </p>
        </div>
      </div>

      {!databaseUrl ? <div className="notice">DATABASE_URL is not set. Evidence records are unavailable.</div> : null}

      <StatsGrid stats={stats} />

      <section className="panel">
        <div className="panel-header">
          <h2 className="panel-title">
            <Filter aria-hidden="true" />
            Filters
          </h2>
        </div>
        <div className="panel-body filter-stack">
          <FilterRow label="Usefulness" values={USEFULNESS} active={normalize(filters.usefulness_status)} param="usefulness_status" filters={filters} />
          <FilterRow label="Kind" values={EVIDENCE_KINDS} active={normalize(filters.evidence_kind)} param="evidence_kind" filters={filters} />
          <FilterRow label="Source" values={SOURCE_QUALITY} active={normalize(filters.source_quality)} param="source_quality" filters={filters} />
        </div>
      </section>

      <section className="panel inspection-panel">
        <div className="panel-header">
          <h2 className="panel-title">
            <FileSearch aria-hidden="true" />
            Evidence items
          </h2>
          <span className="muted">{items.length} rows</span>
        </div>
        <div className="inspection-list">
          {items.map((item) => (
            <EvidenceRow item={item} key={item.evidence_id} />
          ))}
          {!items.length ? <p className="muted empty-state">No evidence items match the current filters.</p> : null}
        </div>
      </section>
    </main>
  );
}

async function safeItems(filters: Awaited<EvidencePageProps["searchParams"]>) {
  try {
    return listPostgresEvidenceItems({
      usefulnessStatus: valueOrNull(filters.usefulness_status),
      evidenceKind: valueOrNull(filters.evidence_kind),
      sourceQuality: valueOrNull(filters.source_quality),
      targetCode: valueOrNull(filters.target),
      limit: 160
    });
  } catch {
    return [];
  }
}

async function safeStats() {
  try {
    return getPostgresEvidenceStats();
  } catch {
    return [];
  }
}

function EvidenceRow({ item }: { item: PostgresEvidenceListItem }) {
  return (
    <article className="inspection-row">
      <header>
        <div className="inspection-title">
          <span className="badge strong">{item.usefulness_status}</span>
          <span className="badge">{item.evidence_kind}</span>
          <span className="badge">{item.source_quality}</span>
          {item.duplicate_of ? <span className="badge danger">duplicate</span> : null}
        </div>
        <time className="mono muted">{item.created_at}</time>
      </header>

      <h3>{item.title || item.evidence_id}</h3>
      <p>{item.text_excerpt || "No excerpt captured."}</p>

      <footer className="inspection-links">
        {item.target_code ? (
          <Link className="table-link mono" href={`/targets/${encodeURIComponent(item.target_code)}`}>
            {item.target_code}
          </Link>
        ) : (
          <span className="muted">no target</span>
        )}
        {item.job_id ? (
          <Link className="table-link mono" href={`/jobs/${item.job_id}`}>
            {item.job_id}
          </Link>
        ) : null}
        {item.url ? (
          <a className="table-link" href={item.url} rel="noreferrer" target="_blank">
            <Link2 aria-hidden="true" />
            Source
          </a>
        ) : null}
        <span className="muted">source {item.source_id ?? "unknown"}</span>
        {item.confidence !== null ? <span className="muted">confidence {item.confidence.toFixed(2)}</span> : null}
        {item.filter_reasons.length ? <span className="muted">reasons {item.filter_reasons.join(", ")}</span> : null}
      </footer>
    </article>
  );
}

function StatsGrid({ stats }: { stats: PostgresAdminCount[] }) {
  const primary = stats.filter((row) => row.scope === "usefulness_status" || row.scope === "evidence_kind").slice(0, 8);
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
  param: "usefulness_status" | "evidence_kind" | "source_quality";
  filters: Awaited<EvidencePageProps["searchParams"]>;
}) {
  return (
    <div className="filter-row">
      <span>{label}</span>
      <div className="segmented">
        {values.map((value) => (
          <Link className={active === value ? "active" : ""} href={filterHref("/evidence", filters, param, value)} key={value}>
            {value}
          </Link>
        ))}
      </div>
    </div>
  );
}

function filterHref(
  pathname: string,
  filters: Awaited<EvidencePageProps["searchParams"]>,
  key: "usefulness_status" | "evidence_kind" | "source_quality",
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
