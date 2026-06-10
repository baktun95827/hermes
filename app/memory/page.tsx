import Link from "next/link";
import { GitCompareArrows, Layers3 } from "lucide-react";
import { getDatabaseUrl, listPostgresMemoryRecords } from "@/packages/signal-radar-core/src";

export const dynamic = "force-dynamic";

type MemoryPageProps = {
  searchParams: Promise<{ collection?: string }>;
};

const COLLECTIONS = [
  "all",
  "themes",
  "accounts",
  "information_units",
  "event_clusters",
  "entities",
  "events",
  "macro",
  "sources",
  "alert_candidates",
  "contradictions"
];

export default async function MemoryPage({ searchParams }: MemoryPageProps) {
  const { collection } = await searchParams;
  const databaseUrl = getDatabaseUrl();
  const records = databaseUrl ? await safeRecords(collection) : [];

  return (
    <main className="shell">
      <div className="page-head">
        <div>
          <h1 className="page-title">Memory records</h1>
          <p className="page-copy">Current Postgres memory state with append-only versions and JSON diffs.</p>
        </div>
      </div>

      {!databaseUrl ? <div className="notice">DATABASE_URL is not set. Memory records are unavailable.</div> : null}

      <section className="panel">
        <div className="panel-header">
          <h2 className="panel-title">
            <Layers3 aria-hidden="true" />
            Collections
          </h2>
          <div className="segmented scrollable">
            {COLLECTIONS.map((item) => (
              <Link
                className={collectionForLink(collection) === item ? "active" : ""}
                href={item === "all" ? "/memory" : `/memory?collection=${item}`}
                key={item}
              >
                {item}
              </Link>
            ))}
          </div>
        </div>
        <div className="memory-list">
          {records.map((record) => (
            <Link className="memory-row" href={`/memory/${record.memory_id}`} key={record.memory_id}>
              <div>
                <span className="badge">{record.collection}</span>
                <h2>{record.title || record.record_key}</h2>
                <p>{record.preview || "No preview payload."}</p>
              </div>
              <div className="memory-meta">
                <GitCompareArrows aria-hidden="true" />
                <span>v{record.current_version}</span>
                <code>{record.updated_at}</code>
              </div>
            </Link>
          ))}
          {!records.length ? <p className="muted empty-state">No memory records found.</p> : null}
        </div>
      </section>
    </main>
  );
}

async function safeRecords(collection?: string) {
  try {
    return listPostgresMemoryRecords({ collection: collectionForQuery(collection), limit: 120 });
  } catch {
    return [];
  }
}

function collectionForQuery(collection?: string): string | null {
  return collection && COLLECTIONS.includes(collection) && collection !== "all" ? collection : null;
}

function collectionForLink(collection?: string): string {
  return collectionForQuery(collection) ?? "all";
}
