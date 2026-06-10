import Link from "next/link";
import { Clock, Database, ListFilter } from "lucide-react";
import { getDatabaseUrl, getPostgresQueueStats, listRecentPostgresJobs } from "@/packages/signal-radar-core/src";
import { StatusPill } from "@/components/status-pill";

export const dynamic = "force-dynamic";

type JobsPageProps = {
  searchParams: Promise<{ status?: string }>;
};

export default async function JobsPage({ searchParams }: JobsPageProps) {
  const { status } = await searchParams;
  const databaseUrl = getDatabaseUrl();
  const jobs = databaseUrl ? await safeJobs(status) : [];
  const queueStats = databaseUrl ? await safeQueueStats() : [];

  return (
    <main className="shell">
      <div className="page-head">
        <div>
          <h1 className="page-title">Job operations</h1>
          <p className="page-copy">Postgres-backed ingestion, queue, provider run, and memory-write status.</p>
        </div>
      </div>

      {!databaseUrl ? <div className="notice">DATABASE_URL is not set. Start Postgres and run migrations first.</div> : null}

      <section className="stats-grid">
        <div className="metric">
          <Database aria-hidden="true" />
          <span>Database</span>
          <strong>{databaseUrl ? "connected" : "missing"}</strong>
        </div>
        {queueStats.map((row) => (
          <div className="metric" key={row.status}>
            <Clock aria-hidden="true" />
            <span>{row.status}</span>
            <strong>{row.count}</strong>
          </div>
        ))}
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2 className="panel-title">
            <ListFilter aria-hidden="true" />
            Recent jobs
          </h2>
          <div className="segmented">
            {["all", "queued", "running", "done", "failed"].map((item) => (
              <Link
                className={statusForLink(status) === item ? "active" : ""}
                href={item === "all" ? "/jobs" : `/jobs?status=${item}`}
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
                <th>Status</th>
                <th>Provider</th>
                <th>Updated</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.job_id}>
                  <td>
                    <Link className="mono table-link" href={`/jobs/${job.job_id}`}>
                      {job.job_id}
                    </Link>
                  </td>
                  <td>
                    <StatusPill status={job.status} />
                  </td>
                  <td className="mono">{job.provider ?? "pending"}</td>
                  <td>{job.updated_at}</td>
                  <td className="muted">{job.error ?? ""}</td>
                </tr>
              ))}
              {!jobs.length ? (
                <tr>
                  <td className="muted" colSpan={5}>
                    No jobs found.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

async function safeJobs(status?: string) {
  try {
    return listRecentPostgresJobs(80, { status: statusForQuery(status) });
  } catch {
    return [];
  }
}

async function safeQueueStats() {
  try {
    return getPostgresQueueStats();
  } catch {
    return [];
  }
}

function statusForQuery(status?: string): string | null {
  return ["queued", "running", "done", "failed"].includes(status ?? "") ? status ?? null : null;
}

function statusForLink(status?: string): string {
  return statusForQuery(status) ?? "all";
}
