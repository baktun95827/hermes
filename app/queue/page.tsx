import Link from "next/link";
import type { ReactNode } from "react";
import { AlertTriangle, Clock, ListRestart } from "lucide-react";
import {
  getDatabaseUrl,
  getPostgresQueueReliabilityStats,
  listPostgresQueueEntries,
  type PostgresQueueEntry,
  type QueueFailureGroup,
  type QueueReliabilityStats
} from "@/packages/signal-radar-core/src";

export const dynamic = "force-dynamic";

type QueuePageProps = {
  searchParams: Promise<{ status?: string }>;
};

const STATUSES = ["all", "queued", "claimed", "failed", "dead", "done", "canceled"];

export default async function QueuePage({ searchParams }: QueuePageProps) {
  const { status } = await searchParams;
  const databaseUrl = getDatabaseUrl();
  const [entries, stats] = databaseUrl ? await Promise.all([safeEntries(status), safeStats()]) : [[], emptyStats()];

  return (
    <main className="shell">
      <div className="page-head">
        <div>
          <h1 className="page-title">Queue reliability</h1>
          <p className="page-copy">
            Dead letters, failed retries, stale worker leases, and backoff state for the Postgres analysis queue.
          </p>
        </div>
      </div>

      {!databaseUrl ? <div className="notice">DATABASE_URL is not set. Queue reliability state is unavailable.</div> : null}

      <section className="stats-grid compact">
        <Metric label="stale claimed" value={stats.stale_claimed} icon={<Clock aria-hidden="true" />} />
        {stats.by_status.map((row) => (
          <Metric label={row.status} value={row.count} icon={<ListRestart aria-hidden="true" />} key={row.status} />
        ))}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2 className="panel-title">
            <ListRestart aria-hidden="true" />
            Queue rows
          </h2>
          <div className="segmented">
            {STATUSES.map((item) => (
              <Link
                className={statusForLink(status) === item ? "active" : ""}
                href={item === "all" ? "/queue" : `/queue?status=${item}`}
                key={item}
              >
                {item}
              </Link>
            ))}
          </div>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Job</th>
                <th>Queue</th>
                <th>Attempts</th>
                <th>Available</th>
                <th>Lease</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <QueueRow entry={entry} key={entry.queue_id} />
              ))}
              {!entries.length ? (
                <tr>
                  <td className="muted" colSpan={6}>
                    No queue rows match the current filter.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel inspection-panel">
        <div className="panel-header">
          <h2 className="panel-title">
            <AlertTriangle aria-hidden="true" />
            Failure groups
          </h2>
        </div>
        <div className="inspection-list">
          {stats.failure_groups.map((group) => (
            <FailureGroup group={group} key={`${group.status}:${group.last_error}`} />
          ))}
          {!stats.failure_groups.length ? <p className="muted empty-state">No failed or dead queue rows.</p> : null}
        </div>
      </section>
    </main>
  );
}

function QueueRow({ entry }: { entry: PostgresQueueEntry }) {
  return (
    <tr>
      <td>
        <Link className="mono table-link" href={`/jobs/${entry.job_id}`}>
          {entry.job_id}
        </Link>
        {entry.target_code ? (
          <div>
            <Link className="mono table-link" href={`/targets/${entry.target_code}`}>
              {entry.target_code}
            </Link>
          </div>
        ) : null}
      </td>
      <td>
        <span className={`status-pill status-${entry.queue_status}`}>{entry.queue_status}</span>
        <div className="muted">job {entry.job_status}</div>
      </td>
      <td className="mono">
        {entry.attempts}/{entry.max_attempts}
      </td>
      <td className="mono">{entry.available_at}</td>
      <td>
        <div className="mono">{entry.locked_by ?? "unlocked"}</div>
        <div className="muted mono">{entry.locked_until ?? ""}</div>
      </td>
      <td className="muted">{entry.last_error ?? ""}</td>
    </tr>
  );
}

function FailureGroup({ group }: { group: QueueFailureGroup }) {
  return (
    <article className="inspection-row">
      <header>
        <div className="inspection-title">
          <span className={`status-pill status-${group.status}`}>{group.status}</span>
          <span className="badge strong">{group.count}</span>
        </div>
        <time className="mono muted">{group.latest_at}</time>
      </header>
      <h3>{group.last_error}</h3>
    </article>
  );
}

function Metric({ icon, label, value }: { icon: ReactNode; label: string; value: number }) {
  return (
    <div className="metric compact">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

async function safeEntries(status?: string) {
  try {
    return listPostgresQueueEntries({ status: statusForQuery(status), limit: 160 });
  } catch {
    return [];
  }
}

async function safeStats() {
  try {
    return getPostgresQueueReliabilityStats();
  } catch {
    return emptyStats();
  }
}

function statusForQuery(status?: string): string | null {
  return status && STATUSES.includes(status) && status !== "all" ? status : null;
}

function statusForLink(status?: string): string {
  return statusForQuery(status) ?? "all";
}

function emptyStats(): QueueReliabilityStats {
  return {
    by_status: [],
    stale_claimed: 0,
    failure_groups: []
  };
}
