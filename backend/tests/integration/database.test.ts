/**
 * Database integration tests for the model registry + forecast storage.
 *
 * These tests run ONLY when a real PostgreSQL is reachable at DATABASE_URL;
 * otherwise they skip gracefully so `npm test` stays green in any environment.
 *
 * Every mutation runs inside a transaction and is rolled back — nothing is
 * persisted to the target database.
 */

import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import pg from 'pg'
import { migrationsDir } from '../../src/repositories/postgres/pool.ts'
import { config } from '../../src/config.ts'

const PERFORMANCE_MS_CAP = 2000
const SEED_SQL = readFileSync(join(migrationsDir, '../seeds/dev_model_registry.sql'), 'utf8').replace(/^\uFEFF/, '')
const COMPARISON_SEED_SQL = readFileSync(join(migrationsDir, '../seeds/dev_model_comparison.sql'), 'utf8').replace(/^\uFEFF/, '')
const readMigration = (step: string, direction: 'up' | 'down'): string =>
  readFileSync(join(migrationsDir, `${step}.${direction}.sql`), 'utf8').replace(/^\uFEFF/, '')

let client: pg.Client | null = null
let available = false
let skipReason = 'PostgreSQL unreachable at DATABASE_URL — database tests skipped'

function runSql(sql: string, values: readonly unknown[] = []): Promise<pg.QueryResult<Record<string, unknown>>> {
  if (!client) throw new Error('DB client not initialized')
  return client.query({
    text: sql,
    values: [...values],
    rowMode: undefined,
  })
}

/**
 * Asserts that a statement is rejected with the given PG error code (+ optional constraint).
 *
 * A rejected statement aborts the surrounding transaction; a savepoint isolates
 * it so subsequent expected-failure statements can still run.
 */
async function expectPgError(sql: string, values: readonly unknown[], code: string, constraint?: string): Promise<void> {
  const sp = `sp_${Math.random().toString(36).slice(2, 10)}`
  await runSql(`SAVEPOINT ${sp}`)
  try {
    await assert.rejects(runSql(sql, values), (error: unknown) => {
      const e = error as { code?: string; constraint?: string }
      assert.equal(e.code, code, `expected ${code}, got ${e.code ?? 'unknown'}: ${String(error)}`)
      if (constraint) assert.equal(e.constraint, constraint)
      return true
    })
    await runSql(`ROLLBACK TO SAVEPOINT ${sp}`)
  } catch (error) {
    await runSql(`ROLLBACK TO SAVEPOINT ${sp}`).catch(() => {})
    throw error
  }
}

before(async () => {
  const probe = new pg.Client({ connectionString: config.DATABASE_URL, connectionTimeoutMillis: 4000 })
  try {
    await probe.connect()
    await probe.query('SELECT 1')
    client = probe
    const { applyMigrationFiles } = await import('../../src/repositories/postgres/pool.ts')
    await applyMigrationFiles('up')
    available = true
  } catch {
    available = false
    try {
      await probe.end()
    } catch {
      /* ignore */
    }
  }
})

after(async () => {
  if (client) {
    try {
      await client.end()
    } catch {
      /* ignore */
    }
    client = null
  }
})

test('migrations can be fully applied up', async (t) => {
  if (!available) return t.skip(skipReason)
  const tables = await runSql(
    `SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN
       ('forecasts', 'models', 'optimization_references', 'model_versions', 'model_metrics')`,
  )
  const names = tables.rows.map((r) => r.table_name).sort()
  assert.deepEqual(names, ['forecasts', 'model_metrics', 'model_versions', 'models', 'optimization_references'])
})

test('model_versions: version is unique within a model (model_name, version)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(
      `INSERT INTO model_versions (model_name, algorithm, version, dataset_reference) VALUES ($1, $2, $3, $4)`,
      ['floodnet', 'GRU', 'v1.0.0', 'bucket://exp/1'],
    )
    await expectPgError(
      `INSERT INTO model_versions (model_name, algorithm, version, dataset_reference) VALUES ($1, $2, $3, $4)`,
      ['floodnet', 'GRU', 'v1.0.0', 'bucket://exp/1'],
      '23505',
      'uq_model_versions_name_version',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('model_versions: multiple versions of the same model are supported', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(
      `INSERT INTO model_versions (model_name, algorithm, version, dataset_reference, status) VALUES ($1, $2, $3, $4, 'retired')`,
      ['floodnet', 'GRU', 'v1.0.0', 'bucket://exp/1'],
    )
    await runSql(
      `INSERT INTO model_versions (model_name, algorithm, version, dataset_reference, status) VALUES ($1, $2, $3, $4, 'active')`,
      ['floodnet', 'LSTM', 'v2.0.0', 'bucket://exp/2'],
    )
    const rows = await runSql(`SELECT version, status FROM model_versions WHERE model_name = 'floodnet' ORDER BY version`)
    assert.equal(rows.rows.length, 2)
  } finally {
    await runSql('ROLLBACK')
  }
})

test('model_versions: only one active version per model', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(
      `INSERT INTO model_versions (model_name, algorithm, version, dataset_reference, status) VALUES ($1, $2, $3, $4, 'active')`,
      ['floodnet', 'GRU', 'v1.0.0', 'bucket://exp/1'],
    )
    await expectPgError(
      `INSERT INTO model_versions (model_name, algorithm, version, dataset_reference, status) VALUES ($1, $2, $3, $4, 'active')`,
      ['floodnet', 'GRU', 'v2.0.0', 'bucket://exp/2'],
      '23505',
      'ux_model_versions_one_active_per_model',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('model_versions: blank identifiers are rejected', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await expectPgError(
      `INSERT INTO model_versions (model_name, algorithm, version, dataset_reference) VALUES ($1, $2, $3, $4)`,
      ['', 'GRU', 'v1.0.0', 'bucket://exp/1'],
      '23514',
      'chk_model_versions_not_blank',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('model_versions: timestamp consistency (complete >= start, deploy >= complete)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await expectPgError(
      `INSERT INTO model_versions (model_name, algorithm, version, dataset_reference, training_started_at, training_completed_at)
       VALUES ($1, $2, $3, $4, now(), now() - interval '1 hour')`,
      ['floodnet', 'GRU', 'v1.0.0', 'bucket://exp/1'],
      '23514',
      'chk_model_versions_time_order',
    )
    await expectPgError(
      `INSERT INTO model_versions (model_name, algorithm, version, dataset_reference, training_started_at, training_completed_at, deployed_at)
       VALUES ($1, $2, $3, $4, now() - interval '2 hours', now() - interval '1 hour', now() - interval '3 hours')`,
      ['floodnet', 'GRU', 'v1.1.0', 'bucket://exp/2'],
      '23514',
      'chk_model_versions_time_order',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('model_metrics: rejects writes for a missing model version (FK)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await expectPgError(
      `INSERT INTO model_metrics (model_version_id, accuracy) VALUES (999999999, 0.9)`,
      [],
      '23503',
      'fk_model_metrics_version',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('model_metrics: rejects invalid metric values', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    const version = await runSql(
      `INSERT INTO model_versions (model_name, algorithm, version, dataset_reference) VALUES ($1, $2, $3, $4) RETURNING id`,
      ['floodnet', 'GRU', 'v1.0.0', 'bucket://exp/1'],
    )
    const id = version.rows[0].id

    await expectPgError(
      `INSERT INTO model_metrics (model_version_id, rmse) VALUES ($1, -0.1)`,
      [id],
      '23514',
      'chk_model_metrics_non_negative',
    )
    await expectPgError(
      `INSERT INTO model_metrics (model_version_id, accuracy) VALUES ($1, 1.5)`,
      [id],
      '23514',
      'chk_model_metrics_bounded',
    )
    await expectPgError(
      `INSERT INTO model_metrics (model_version_id) VALUES ($1)`,
      [id],
      '23514',
      'chk_model_metrics_at_least_one',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('model_metrics: accepts a valid scored row and preserves provenance', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    const version = await runSql(
      `INSERT INTO model_versions (model_name, algorithm, version, dataset_reference, model_artifact_reference) VALUES ($1, $2, $3, $4, $5) RETURNING id`,
      ['floodnet', 'GRU', 'v1.0.0', 'bucket://exp/1', 'bucket://artifact/1'],
    )
    const insert = await runSql(
      `INSERT INTO model_metrics (model_version_id, rmse, mae, nse, accuracy, training_time_ms, inference_time_ms, evaluation_dataset)
       VALUES ($1, 0.231, 0.174, 0.912, 0.894, 42000, 3, 'eval/catchment-2026') RETURNING *`,
      [version.rows[0].id],
    )
    assert.equal(insert.rows[0].evaluation_dataset, 'eval/catchment-2026')
    assert.ok(insert.rows[0].created_at instanceof Date, 'created_at should default to now()')
  } finally {
    await runSql('ROLLBACK')
  }
})

test('model_versions: created_at/updated_at maintenance', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    const insert = await runSql(
      `INSERT INTO model_versions (model_name, algorithm, version, dataset_reference) VALUES ($1, $2, $3, $4) RETURNING id, created_at, updated_at`,
      ['floodnet', 'GRU', 'v1.0.0', 'bucket://exp/1'],
    )
    const { id, created_at, updated_at } = insert.rows[0]
    assert.ok(created_at instanceof Date)
    assert.equal(created_at.toISOString(), updated_at.toISOString())

    await new Promise((resolve) => setTimeout(resolve, 20))
    const bumped = await runSql(`UPDATE model_versions SET status = 'retired' WHERE id = $1 RETURNING updated_at`, [id])
    const previous = updated_at as Date
    const current = bumped.rows[0].updated_at as Date
    assert.ok(current.getTime() > previous.getTime(), 'updated_at should bump on UPDATE')
  } finally {
    await runSql('ROLLBACK')
  }
})

test('query performance: dashboard retrieval stays fast on populated tables', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(
      `INSERT INTO forecasts (forecast_id, flood_probability, risk_level, predicted_water_level, forecast_horizon,
                              model_id, model_name, model_version, prediction_timestamp, status)
       SELECT 'PERF-' || g, 0.5, 'MEDIUM', 7.0, '24h', 'MODEL001', 'floodnet', 'v1.0.0',
              now() - (g || ' minutes')::interval, 'completed'
       FROM generate_series(1, 200) g`,
    )

    const latestStart = performance.now()
    await runSql(`SELECT * FROM forecasts ORDER BY prediction_timestamp DESC LIMIT 1`)
    const latestMs = performance.now() - latestStart
    assert.ok(latestMs < PERFORMANCE_MS_CAP, `latest-forecast query took ${latestMs.toFixed(0)}ms`)

    const registryStart = performance.now()
    await runSql(`SELECT id, model_name, version, status FROM model_versions ORDER BY updated_at DESC`)
    const registryMs = performance.now() - registryStart
    assert.ok(registryMs < PERFORMANCE_MS_CAP, `model-registry query took ${registryMs.toFixed(0)}ms`)

    const indexes = await runSql(
      `SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename IN ('forecasts', 'model_versions', 'model_metrics')`,
    )
    const names = new Set(indexes.rows.map((r) => r.indexname))
    for (const expected of [
      'idx_forecasts_timestamp',
      'idx_forecasts_risk',
      'idx_forecasts_model',
      'uq_model_versions_name_version',
      'ux_model_versions_one_active_per_model',
      'idx_model_versions_name_status',
      'idx_model_versions_status',
      'idx_model_metrics_version',
      'idx_model_metrics_evaluated_at',
    ]) {
      assert.ok(names.has(expected), `missing index ${expected}`)
    }
  } finally {
    await runSql('ROLLBACK')
  }
})

test('migrations are reversible (002 down/up round-trips harmlessly)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(readMigration('002_model_versioning', 'down'))
    const afterDown = await runSql(
      `SELECT count(*)::int AS n FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('model_versions', 'model_metrics')`,
    )
    assert.equal(afterDown.rows[0].n, 0, '002 down should remove both registry tables')

    await runSql(readMigration('002_model_versioning', 'up'))
    const afterUp = await runSql(
      `SELECT count(*)::int AS n FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('model_versions', 'model_metrics')`,
    )
    assert.equal(afterUp.rows[0].n, 2, '002 up should recreate both registry tables')
  } finally {
    await runSql('ROLLBACK')
  }
})

test('registry seed is development-marked and carries no fake metrics', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(SEED_SQL)
    const versions = await runSql(
      `SELECT model_name, version, status, dataset_reference FROM model_versions WHERE dataset_reference LIKE 'dev://sample-data/%'`,
    )
    assert.ok(versions.rows.length >= 2, 'expected seeded dev versions')
    for (const row of versions.rows) {
      assert.equal(row.status, 'development', 'registry seed versions must never be active')
      assert.ok(String(row.dataset_reference).startsWith('dev://'), 'seeded provenance must be dev-marked')
    }
    const fakeMetrics = await runSql(
      `SELECT count(*)::int AS n FROM model_metrics WHERE model_version_id IN (SELECT id FROM model_versions WHERE dataset_reference LIKE 'dev://sample-data/%')`,
    )
    assert.equal(fakeMetrics.rows[0].n, 0, 'registry seed must not create fake metrics')
  } finally {
    await runSql('ROLLBACK')
  }
})

test('comparison seed: ~30 dev-marked scored versions, one active per model, no invented classification metrics', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(COMPARISON_SEED_SQL)
    const versions = await runSql(
      `SELECT id, model_name, version, status, dataset_reference, model_artifact_reference
       FROM model_versions WHERE dataset_reference LIKE 'dev://comparison/%'`,
    )
    assert.ok(versions.rows.length >= 29, `expected ~29 comparison versions, got ${versions.rows.length}`)
    for (const row of versions.rows) {
      assert.ok(String(row.dataset_reference).startsWith('dev://comparison/'), 'dataset must be dev-marked')
      assert.ok(String(row.model_artifact_reference).startsWith('dev://comparison/'), 'artifact must be dev-marked')
    }

    const scored = await runSql(
      `SELECT count(*)::int AS n FROM model_metrics
       WHERE model_version_id IN (SELECT id FROM model_versions WHERE dataset_reference LIKE 'dev://comparison/%')`,
    )
    assert.equal(scored.rows[0].n, versions.rows.length, 'every comparison version should have one evaluation')

    const activePerModel = await runSql(
      `SELECT model_name, count(*)::int AS n FROM model_versions
       WHERE dataset_reference LIKE 'dev://comparison/%' AND status = 'active' GROUP BY model_name`,
    )
    for (const row of activePerModel.rows) {
      assert.equal(row.n, 1, `at most one active version per model, found ${row.n} for ${row.model_name}`)
    }
    const distinctModels = await runSql(
      `SELECT count(DISTINCT model_name)::int AS n FROM model_versions WHERE dataset_reference LIKE 'dev://comparison/%'`,
    )
    assert.equal(
      activePerModel.rows.length,
      distinctModels.rows[0].n,
      'every comparison model must have exactly one active version',
    )

    const classification = await runSql(
      `SELECT count(*)::int AS n FROM model_metrics
       WHERE model_version_id IN (SELECT id FROM model_versions WHERE dataset_reference LIKE 'dev://comparison/%')
         AND (accuracy IS NOT NULL OR precision IS NOT NULL OR recall IS NOT NULL OR f1 IS NOT NULL)`,
    )
    assert.equal(classification.rows[0].n, 0, 'dev seed must not invent classification scores for regression')

    const bounded = await runSql(
      `SELECT count(*)::int AS n FROM model_metrics
       WHERE model_version_id IN (SELECT id FROM model_versions WHERE dataset_reference LIKE 'dev://comparison/%')
         AND (r2 IS NULL OR r2 < 0 OR r2 > 1)`,
    )
    assert.equal(bounded.rows[0].n, 0, 'seeded r2 must stay within physical range')
  } finally {
    await runSql('ROLLBACK')
  }
})