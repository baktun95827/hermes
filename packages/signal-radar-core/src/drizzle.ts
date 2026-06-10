import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import type { Pool, PoolClient } from "pg";
import * as schema from "../../../db/schema";
import { getSharedPostgresPool } from "./postgres";

export type SignalRadarDrizzleDb = NodePgDatabase<typeof schema>;

export function createSignalRadarDrizzle(
  poolOrClient: Pool | PoolClient = getSharedPostgresPool()
): SignalRadarDrizzleDb {
  return drizzle(poolOrClient, { schema });
}

export { schema as signalRadarSchema };
