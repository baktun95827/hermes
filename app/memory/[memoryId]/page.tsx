import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, GitCompareArrows } from "lucide-react";
import { getPostgresMemoryRecord } from "@/packages/signal-radar-core/src";

export const dynamic = "force-dynamic";

type MemoryDetailPageProps = {
  params: Promise<{ memoryId: string }>;
};

export default async function MemoryDetailPage({ params }: MemoryDetailPageProps) {
  const { memoryId } = await params;
  const record = await getPostgresMemoryRecord(memoryId).catch(() => null);
  if (!record) notFound();

  return (
    <main className="shell">
      <p>
        <Link className="button secondary" href="/memory">
          <ArrowLeft aria-hidden="true" />
          Back to memory
        </Link>
      </p>

      <section className="panel">
        <div className="panel-header">
          <div>
            <span className="badge">{record.collection}</span>
            <h1 className="page-title">{record.title || record.record_key}</h1>
            <p className="page-copy">
              <span className="mono">{record.record_key}</span> · current version {record.current_version} · updated{" "}
              {record.updated_at}
            </p>
          </div>
        </div>
      </section>

      <div className="artifact-grid detail-grid">
        <Artifact title="Current Payload" value={record.payload} />
        <section className="artifact-panel">
          <h2>
            <GitCompareArrows aria-hidden="true" />
            Version History
          </h2>
          <div className="version-list">
            {record.versions.map((version) => (
              <article className="version-card" key={version.version_id}>
                <header>
                  <strong>v{version.version_number}</strong>
                  <span className="badge">{version.operation}</span>
                  <code>{version.created_at}</code>
                </header>
                {version.job_id ? (
                  <Link className="table-link mono" href={`/jobs/${version.job_id}`}>
                    {version.job_id}
                  </Link>
                ) : null}
                <pre>{JSON.stringify(version.diff, null, 2)}</pre>
              </article>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}

function Artifact({ title, value }: { title: string; value: unknown }) {
  return (
    <section className="artifact-panel">
      <h2>{title}</h2>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </section>
  );
}
