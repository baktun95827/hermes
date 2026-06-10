import { NextResponse } from "next/server";
import { getJobPayload, validateJobId } from "@/services/signal-radar-worker/worker";

export const runtime = "nodejs";

type JobRouteProps = {
  params: Promise<{ jobId: string }>;
};

export async function GET(_: Request, { params }: JobRouteProps) {
  try {
    const { jobId } = await params;
    const safeJobId = validateJobId(jobId);
    const payload = await getJobPayload(safeJobId);
    if (!payload) return NextResponse.json({ error: "job not found", job_id: safeJobId }, { status: 404 });
    return NextResponse.json(payload);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 400 }
    );
  }
}
