import Link from "next/link";
import { readdir } from "node:fs/promises";
import path from "node:path";
import { FileText, ListChecks, Radar } from "lucide-react";
import { ManualIngestForm } from "@/components/manual-ingest-form";
import { StatusPill } from "@/components/status-pill";
import { DEFAULT_JOBS_DIR, readJsonFile, type JobStatus } from "@/packages/signal-radar-core/src";

export default async function HomePage() {
  const jobs = await recentJobs();
  return (
    <main className="shell">
      <div className="page-head">
        <div>
          <h1 className="page-title">Manual signal ingest</h1>
          <p className="page-copy">
            Paste a research note, dispatch a TypeScript worker job, and inspect summary,
            strict memory update output, audit records, and logs from one surface.
          </p>
        </div>
      </div>

      <div className="workspace-grid">
        <section className="panel">
          <div className="panel-header">
            <h2 className="panel-title">
              <Radar aria-hidden="true" />
              New analysis
            </h2>
          </div>
          <div className="panel-body">
            <ManualIngestForm />
          </div>
        </section>

        <aside className="panel">
          <div className="panel-header">
            <h2 className="panel-title">
              <ListChecks aria-hidden="true" />
              Recent jobs
            </h2>
          </div>
          <div className="panel-body">
            {jobs.length ? (
              <div className="job-list">
                {jobs.map((job) => (
                  <Link className="job-card" href={`/jobs/${job.job_id}`} key={job.job_id}>
                    <code>{job.job_id}</code>
                    <StatusPill status={job.status} />
                    <span className="muted">{job.updated_at}</span>
                  </Link>
                ))}
              </div>
            ) : (
              <div className="stack">
                <FileText aria-hidden="true" />
                <p className="muted">No jobs yet. Submit the first note to create a durable job directory.</p>
              </div>
            )}
          </div>
        </aside>
      </div>
    </main>
  );
}

async function recentJobs(): Promise<JobStatus[]> {
  try {
    const entries = await readdir(DEFAULT_JOBS_DIR, { withFileTypes: true });
    const jobs: JobStatus[] = [];
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const status = await readJsonFile<JobStatus | null>(
        path.join(DEFAULT_JOBS_DIR, entry.name, "status.json"),
        null
      );
      if (status?.job_id) jobs.push(status);
    }
    return jobs
      .sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)))
      .slice(0, 8);
  } catch {
    return [];
  }
}
