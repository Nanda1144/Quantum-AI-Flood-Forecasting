/** PostgreSQL connection pool (lazy — the app boots even without a DB up). */

import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import pg from 'pg'
import { config } from '../../config.ts'
import type { ForecastRepository, ModelRepository, OptimizationRepository } from '../repositories.ts'

const { Pool } = pg

let pool: pg.Pool | null = null

/** Canonical schema lives in the database module — applied here at boot. */
export const migrationsDir = fileURLToPath(new URL('../../../../database/migrations/', import.meta.url))

export function getPool(): pg.Pool {
  if (!pool) {
    pool = new Pool({ connectionString: config.DATABASE_URL })
  }
  return pool
}

/** Sorted migration step names for a direction, e.g. "001_core_tables". */
export function listMigrations(direction: 'up' | 'down'): string[] {
  const suffix = `.${direction}.sql`
  return readdirSync(migrationsDir)
    .filter((file) => file.endsWith(suffix) && !file.startsWith('.'))
    .map((file) => file.slice(0, -suffix.length))
    .sort()
}

/** Runs a single migration file inside a transaction. */
export async function applyMigration(step: string, direction: 'up' | 'down'): Promise<void> {
  const sql = readFileSync(join(migrationsDir, `${step}.${direction}.sql`), 'utf8').replace(/^\uFEFF/, '')
  await getPool().query(`BEGIN; ${sql} COMMIT;`)
}

/** Applies every migration file for the given direction, in order. */
export async function applyMigrationFiles(direction: 'up' | 'down' = 'up'): Promise<void> {
  for (const step of listMigrations(direction)) {
    await applyMigration(step, direction)
  }
}

/** Best-effort idempotent schema bootstrap, mirroring migrations/*.up.sql. */
export async function ensureSchema(): Promise<void> {
  await applyMigrationFiles('up')
}

export type { ForecastRepository, ModelRepository, OptimizationRepository }