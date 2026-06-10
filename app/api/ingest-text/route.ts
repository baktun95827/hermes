import { NextResponse } from "next/server";
import path from "node:path";
import { createManualJob, runJob } from "@/services/signal-radar-worker/worker";

export const runtime = "nodejs";

export async function POST(request: Request) {
  try {
    const payload = (await request.json()) as Record<string, unknown>;
    const jobDir = await createManualJob({
      text: String(payload.text ?? ""),
      title: cleanOptional(payload.title),
      url: cleanOptional(payload.url),
      userLabel: cleanOptional(payload.user_label) ?? "user_note",
      inputChannel: "web",
      contentType: cleanOptional(payload.content_type) ?? "note",
      requiresVerification: Boolean(payload.requires_verification)
    });
    const jobId = path.basename(jobDir);
    setTimeout(() => {
      runJob({
        jobDir,
        providerName: process.env.XRADAR_ANALYZER_PROVIDER ?? "fixture",
        model: process.env.XRADAR_CODEX_MODEL ?? "gpt-5.4"
      }).catch((error) => {
        console.error(error);
      });
    }, 0);

    return NextResponse.json(
      {
        job_id: jobId,
        status_url: `/api/jobs/${jobId}`,
        html_url: `/jobs/${jobId}`,
        provider: process.env.XRADAR_ANALYZER_PROVIDER ?? "fixture",
        model: process.env.XRADAR_CODEX_MODEL ?? "gpt-5.4"
      },
      { status: 202 }
    );
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 400 }
    );
  }
}

function cleanOptional(value: unknown): string | null {
  const text = String(value ?? "").trim();
  return text || null;
}
