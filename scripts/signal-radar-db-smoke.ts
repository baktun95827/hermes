import {
  createPostgresPool,
  enqueueManualTextJob,
  getPostgresEvidenceStats,
  getPostgresQualityGateStats,
  getPostgresQueueReliabilityStats,
  getPostgresTargetReadModelV1,
  listPostgresEvidenceItems,
  listPostgresQualityGates,
  listPostgresQueueEntries,
  recoverExpiredPostgresJobLeases
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
    const readModel = await getPostgresTargetReadModelV1("SAMPLE", pool);
    assertTrue(readModel.schema_version === "target_read_model/v1", "target read model should expose v1 schema");
    assertTrue(readModel.overview.target?.symbol === "SAMPLE", "target read model should resolve target code");
    assertTrue(Array.isArray(readModel.fundamentals.records), "target read model should include fundamentals section");
    assertTrue(Array.isArray(readModel.segments.records), "target read model should include segments section");
    assertTrue(Array.isArray(readModel.concepts.records), "target read model should include concepts section");
    assertTrue(Array.isArray(readModel.timeline.latest_changes), "target read model should include timeline section");
    assertTrue(readModel.evidence.length >= 1, "target read model should include evidence");
    assertTrue(readModel.quality_gates.length >= 1, "target read model should include quality gates");
    const evidenceItems = await listPostgresEvidenceItems({ targetCode: "SAMPLE" }, pool);
    const qualityGates = await listPostgresQualityGates({ targetCode: "SAMPLE" }, pool);
    const evidenceStats = await getPostgresEvidenceStats(pool);
    const qualityStats = await getPostgresQualityGateStats(pool);
    assertTrue(evidenceItems.length >= 1, "evidence admin list should resolve target code");
    assertTrue(qualityGates.length >= 1, "quality admin list should resolve target code");
    assertTrue(evidenceStats.length >= 1, "evidence admin stats should be available");
    assertTrue(qualityStats.length >= 1, "quality admin stats should be available");
    await assertQueueReliability(pool);
    console.log(`ok db smoke ${queued.job_id}`);
  } finally {
    await pool.end();
  }
}

async function assertQueueReliability(pool: ReturnType<typeof createPostgresPool>): Promise<void> {
  const deadJobId = `lease_dead_${Date.now()}`;
  const failedJobId = `lease_failed_${Date.now()}`;
  await pool.query(
    `
    INSERT INTO signal_radar_jobs (job_id, kind, status, provider, model)
    VALUES
      ($1, 'manual_text', 'running', 'fixture', 'gpt-5.4'),
      ($2, 'manual_text', 'running', 'fixture', 'gpt-5.4')
    `,
    [deadJobId, failedJobId]
  );
  await pool.query(
    `
    INSERT INTO signal_radar_job_queue (
      job_id, queue_name, status, attempts, max_attempts, locked_by,
      locked_until, last_error, available_at
    )
    VALUES
      ($1, 'analysis', 'claimed', 1, 1, 'expired-worker', now() - interval '10 minutes', NULL, now()),
      ($2, 'analysis', 'claimed', 1, 3, 'expired-worker', now() - interval '10 minutes', 'previous failure', now())
    `,
    [deadJobId, failedJobId]
  );
  const recovered = await recoverExpiredPostgresJobLeases({ queueName: "analysis" }, pool);
  assertTrue(recovered.recovered_count >= 2, "lease recovery should release expired claimed rows");
  assertTrue(recovered.dead_count >= 1, "lease recovery should move exhausted attempts to dead");
  assertTrue(recovered.failed_count >= 1, "lease recovery should move retryable attempts to failed");
  const queueRows = await pool.query<{ job_id: string; status: string; available_in_future: boolean }>(
    `
    SELECT job_id, status, available_at > now() AS available_in_future
    FROM signal_radar_job_queue
    WHERE job_id IN ($1, $2)
    ORDER BY job_id
    `,
    [deadJobId, failedJobId]
  );
  const dead = queueRows.rows.find((item) => item.job_id === deadJobId);
  const failed = queueRows.rows.find((item) => item.job_id === failedJobId);
  assertTrue(dead?.status === "dead", "exhausted expired lease should become dead");
  assertTrue(failed?.status === "failed", "retryable expired lease should become failed");
  assertTrue(failed?.available_in_future, "retryable expired lease should use backoff");
  const queueEntries = await listPostgresQueueEntries({ status: "dead" }, pool);
  const reliability = await getPostgresQueueReliabilityStats({}, pool);
  assertTrue(queueEntries.some((entry) => entry.job_id === deadJobId), "queue admin list should include dead rows");
  assertTrue(reliability.failure_groups.length >= 1, "queue reliability stats should include failure groups");
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exit(1);
});
