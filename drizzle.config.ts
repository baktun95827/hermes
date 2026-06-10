import { defineConfig } from "drizzle-kit";

export default defineConfig({
  schema: "./db/schema.ts",
  out: "./drizzle",
  dialect: "postgresql",
  dbCredentials: {
    url: process.env.DATABASE_URL ?? "postgres://signal_radar:signal_radar@127.0.0.1:5432/signal_radar"
  },
  migrations: {
    schema: "drizzle",
    table: "__drizzle_migrations"
  },
  strict: false,
  verbose: true
});
