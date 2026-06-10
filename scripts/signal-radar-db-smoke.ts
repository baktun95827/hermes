import {
  createPostgresPool,
  enqueueManualTextJob,
  getPostgresTargetReadProjection
} from "../packages/signal-radar-core/src";
import { runPostgresWorkerLoop } from "../services/signal-radar-worker/worker";

function assertTrue(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(message);
}

async function main(): Promise<void> {
  if (!process.env.DATABASE_URL) throw new Error("DATABASE_URL is required");
  const pool = createPostgresPool();
  try {
    const queued = await enqueueManualTextJob(
      {
        text: "DB smoke: SampleCo fundamentals are being discussed, but the source still needs verification.",
        title: "DB smoke SampleCo",
        userLabel: "db_smoke",
        targetCode: "SAMPLE",
        inputChannel: "db-smoke",
        requiresVerification: true,
        provider: "fixture",
        model: "gpt-5.4"
      },
      pool
    );
    await runPostgresWorkerLoop({
      workerId: "db-smoke",
      batchLimit: 1,
      providerName: "fixture",
      model: "gpt-5.4"
    });

    const rows = await pool.query<{
      job_status: string;
      queue_status: string;
      artifact_count: string;
      memory_update_count: string;
      memory_version_count: string;
      source_count: string;
      evidence_count: string;
      quality_gate_count: string;
      target_count: string;
    }>(
      `
      SELECT
        (SELECT status FROM signal_radar_jobs WHERE job_id = $1) AS job_status,
        (SELECT status FROM signal_radar_job_queue WHERE job_id = $1) AS queue_status,
        (SELECT count(*)::text FROM signal_radar_analysis_artifacts WHERE job_id = $1) AS artifact_count,
        (SELECT count(*)::text FROM signal_radar_memory_updates WHERE job_id = $1) AS memory_update_count,
        (SELECT count(*)::text FROM signal_radar_memory_versions WHERE job_id = $1) AS memory_version_count,
        (SELECT count(*)::text FROM signal_radar_sources) AS source_count,
        (SELECT count(*)::text FROM signal_radar_evidence_items WHERE job_id = $1) AS evidence_count,
        (SELECT count(*)::text FROM signal_radar_quality_gates WHERE job_id = $1) AS quality_gate_count,
        (SELECT count(*)::text FROM signal_radar_targets WHERE symbol = 'SAMPLE') AS target_count
      `,
      [queued.job_id]
    );
    const row = rows.rows[0];
    assertTrue(row.job_status === "done", "DB smoke job should finish");
    assertTrue(row.queue_status === "done", "DB smoke queue row should finish");
    assertTrue(Number(row.artifact_count) >= 1, "DB smoke should write analysis artifact");
    assertTrue(Number(row.memory_update_count) >= 1, "DB smoke should write memory update");
    assertTrue(Number(row.memory_version_count) >= 1, "DB smoke should write memory version");
    assertTrue(Number(row.source_count) >= 1, "DB smoke should write source ledger rows");
    assertTrue(Number(row.evidence_count) >= 1, "DB smoke should write evidence snapshots");
    assertTrue(Number(row.quality_gate_count) >= 2, "DB smoke should write evidence and memory quality gates");
    assertTrue(Number(row.target_count) === 1, "DB smoke should upsert target code");
    const projection = await getPostgresTargetReadProjection("SAMPLE", pool);
    assertTrue(projection.target?.symbol === "SAMPLE", "target projection should resolve target code");
    assertTrue(projection.evidence.length >= 1, "target projection should include evidence");
    assertTrue(projection.quality_gates.length >= 1, "target projection should include quality gates");
    console.log(`ok db smoke ${queued.job_id}`);
  } finally {
    await pool.end();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exit(1);
});
