import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { createPostgresPool } from "../packages/signal-radar-core/src/postgres";

async function main(): Promise<void> {
  const databaseUrl = process.env.DATABASE_URL;
  if (!databaseUrl) throw new Error("DATABASE_URL is required");

  const migrationsDir = path.join(process.cwd(), "db", "migrations");
  const files = (await readdir(migrationsDir))
    .filter((file) => file.endsWith(".sql"))
    .sort();

  const pool = createPostgresPool(databaseUrl);
  try {
    await pool.query(`
      CREATE TABLE IF NOT EXISTS signal_radar_schema_migrations (
        version text PRIMARY KEY,
        applied_at timestamptz NOT NULL DEFAULT now()
      )
    `);

    for (const file of files) {
      const version = file.replace(/\.sql$/, "");
      const already = await pool.query(
        "SELECT 1 FROM signal_radar_schema_migrations WHERE version = $1",
        [version]
      );
      if (already.rowCount) {
        console.log(`skip ${version}`);
        continue;
      }

      const sql = await readFile(path.join(migrationsDir, file), "utf8");
      await pool.query("BEGIN");
      try {
        await pool.query(sql);
        await pool.query(
          "INSERT INTO signal_radar_schema_migrations (version) VALUES ($1)",
          [version]
        );
        await pool.query("COMMIT");
        console.log(`applied ${version}`);
      } catch (error) {
        await pool.query("ROLLBACK");
        throw error;
      }
    }
  } finally {
    await pool.end();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exit(1);
});
