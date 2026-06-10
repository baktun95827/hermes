import { Pool, type PoolClient, type PoolConfig, type QueryResult, type QueryResultRow } from "pg";

export type PostgresQueryable = {
  query<T extends QueryResultRow = QueryResultRow>(text: string, values?: unknown[]): Promise<QueryResult<T>>;
};

declare global {
  var __signalRadarPostgresPool: Pool | undefined;
}

export function getDatabaseUrl(): string | null {
  return process.env.DATABASE_URL?.trim() || null;
}

export function requireDatabaseUrl(): string {
  const databaseUrl = getDatabaseUrl();
  if (!databaseUrl) throw new Error("DATABASE_URL is required for Postgres-backed Signal Radar runtime");
  return databaseUrl;
}

export function createPostgresPool(databaseUrl = requireDatabaseUrl(), config: PoolConfig = {}): Pool {
  return new Pool({
    connectionString: databaseUrl,
    max: Number(process.env.XRADAR_PG_POOL_MAX ?? 10),
    idleTimeoutMillis: Number(process.env.XRADAR_PG_IDLE_TIMEOUT_MS ?? 30_000),
    ...config
  });
}

export function getSharedPostgresPool(): Pool {
  if (!globalThis.__signalRadarPostgresPool) {
    globalThis.__signalRadarPostgresPool = createPostgresPool();
  }
  return globalThis.__signalRadarPostgresPool;
}

export async function withPostgresTransaction<T>(
  poolOrClient: Pool | PoolClient,
  callback: (client: PoolClient) => Promise<T>
): Promise<T> {
  const isPool = poolOrClient instanceof Pool;
  const client = isPool ? await poolOrClient.connect() : poolOrClient;
  try {
    await client.query("BEGIN");
    const result = await callback(client);
    await client.query("COMMIT");
    return result;
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    if (isPool) client.release();
  }
}

export function jsonb(value: unknown): string {
  return JSON.stringify(value ?? null);
}
