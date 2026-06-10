import { NextResponse } from "next/server";
import { enqueueManualTextJob } from "@/packages/signal-radar-core/src";

export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    const payload = (await request.json()) as Record<string, unknown>;
    const job = await enqueueManualTextJob({
      text: String(payload.text ?? ""),
      title: cleanOptional(payload.title),
      url: cleanOptional(payload.url),
      userLabel: cleanOptional(payload.user_label) ?? "user_note",
      inputChannel: "web",
      contentType: cleanOptional(payload.content_type) ?? "note",
      requiresVerification: Boolean(payload.requires_verification),
      provider: process.env.XRADAR_ANALYZER_PROVIDER ?? "fixture",
      model: process.env.XRADAR_CODEX_MODEL ?? "gpt-5.4"
    });

    return NextResponse.json(
      {
        job_id: job.job_id,
        queue_id: job.queue_id,
        status_url: `/api/jobs/${job.job_id}`,
        html_url: `/jobs/${job.job_id}`,
        provider: job.provider,
        model: job.model
      },
      { status: 202 }
    );
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: error instanceof Error && error.message.includes("DATABASE_URL") ? 503 : 400 }
    );
  }
}

function cleanOptional(value: unknown): string | null {
  const text = String(value ?? "").trim();
  return text || null;
}
