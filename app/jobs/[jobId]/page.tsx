import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { JobDetail } from "@/components/job-detail";
import { getPostgresJobPayload } from "@/packages/signal-radar-core/src";
import { validateJobId } from "@/services/signal-radar-worker/worker";

type JobPageProps = {
  params: Promise<{ jobId: string }>;
};

export default async function JobPage({ params }: JobPageProps) {
  const { jobId } = await params;
  let safeJobId = "";
  try {
    safeJobId = validateJobId(jobId);
  } catch {
    notFound();
  }
  const payload = await getPostgresJobPayload(safeJobId);
  if (!payload) notFound();

  return (
    <main className="shell">
      <p>
        <Link className="button secondary" href="/">
          <ArrowLeft aria-hidden="true" />
          Back to ingest
        </Link>
      </p>
      <JobDetail initialPayload={payload as never} />
    </main>
  );
}
