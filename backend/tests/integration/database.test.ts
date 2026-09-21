/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

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
  const probe = new pg.Client({ connectionString: config.DATABASE_URL, connectionTimeoutMillis: 12000 })
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

// ────────────────────────────────────────────────────────────────────────────
// 004_optimization_persistence — the Nanda optimization persistence layer.
// ────────────────────────────────────────────────────────────────────────────

const INSERT_COMPLETED_JOB = (id: string): string =>
  `INSERT INTO optimization_jobs (id, owner, status, problem_type, request, algorithm, execution_mode, backend)
   VALUES ('${id}', 'admin', 'completed', 'sensor_placement', '{}'::jsonb, 'qaoa', 'simulator', 'qflare_simulator_statevector')`

const INSERT_RESULT = (jobId: string): string =>
  `INSERT INTO optimization_results (id, optimization_job_id, bitstring, selected_locations, objective_value,
                                     constraint_violations, validation_status, runtime_ms,
                                     classical_objective, quantum_objective, approximation_quality)
   VALUES ('${jobId}-R1', '${jobId}', '101010', '["SIT-001","SIT-003","SIT-005"]'::jsonb, 0.3278,
           '[]'::jsonb, 'valid', 2, 0.3278, 0.3278, 1)`

test('004: optimization persistence tables, columns and indexes exist', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    const tables = await runSql(
      `SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'
         AND table_name IN ('optimization_results', 'optimization_job_audit', 'optimization_qubo_artifacts')`,
    )
    assert.equal(tables.rows.length, 3, '004 must create results, audit and artifact tables')

    const columns = await runSql(
      `SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'optimization_jobs'
         AND column_name IN ('forecast_reference','candidate_reference','input_reference','variables_count',
                             'constraints','objective_configuration','error_message','qubo_storage',
                             'qubo_artifact_reference','deleted_at','deleted_by','delete_reason')`,
    )
    assert.equal(columns.rows.length, 12, '004 must add all scalar configuration columns to optimization_jobs')

    const resultColumns = await runSql(
      `SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'optimization_results'
         AND column_name IN ('id','optimization_job_id','bitstring','selected_locations','objective_value',
                             'constraint_violations','validation_status','runtime_ms','classical_objective',
                             'quantum_objective','approximation_quality','created_at')`,
    )
    assert.equal(resultColumns.rows.length, 12, 'optimization_results must carry the full result record')

    const indexes = await runSql(
      `SELECT indexname FROM pg_indexes WHERE schemaname = 'public'
         AND indexname IN ('idx_optimization_jobs_status','idx_optimization_jobs_problem_type',
                           'idx_optimization_jobs_created_at','idx_optimization_results_job',
                           'idx_optimization_results_validation_status')`,
    )
    assert.equal(indexes.rows.length, 5, '004 must satisfy the required index set')
  } finally {
    await runSql('ROLLBACK')
  }
})

test('004: optimization_results rejects orphan rows (FK)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await expectPgError(
      `INSERT INTO optimization_results (id, optimization_job_id, objective_value, validation_status)
       VALUES ('QOP-DOES-NOT-EXIST-R1', 'QOP-DOES-NOT-EXIST', 1, 'valid')`,
      [],
      '23503',
      'fk_optimization_results_job',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('004: one result row per job (primary key + id format)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_COMPLETED_JOB('QOP-DBTEST-0002'))
    await runSql(INSERT_RESULT('QOP-DBTEST-0002'))
    await expectPgError(
      `INSERT INTO optimization_results (id, optimization_job_id, bitstring, objective_value, validation_status)
       VALUES ('QOP-DBTEST-0002-R1', 'QOP-DBTEST-0002', '000000', 0.1, 'valid')`,
      [],
      '23505',
      'optimization_results_pkey',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('004: repository saveResult upserts on the result primary key (ON CONFLICT id)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_COMPLETED_JOB('QOP-DBTEST-0007'))
    // First persist (as the orchestrator does at step 14).
    await runSql(INSERT_RESULT('QOP-DBTEST-0007'))
    // Re-persisting the same row must upsert via ON CONFLICT (id) — the exact
    // statement the postgres repository issues — not raise 42P10.
    await runSql(
      `INSERT INTO optimization_results (id, optimization_job_id, bitstring, selected_locations, objective_value,
                                         constraint_violations, validation_status, runtime_ms,
                                         classical_objective, quantum_objective, approximation_quality)
       VALUES ('QOP-DBTEST-0007-R1', 'QOP-DBTEST-0007', '111000', '["SIT-003"]'::jsonb, 0.45,
               '[]'::jsonb, 'valid', 3, 0.45, 0.45, 1)
       ON CONFLICT (id) DO UPDATE SET
         bitstring = EXCLUDED.bitstring,
         selected_locations = EXCLUDED.selected_locations,
         objective_value = EXCLUDED.objective_value,
         runtime_ms = EXCLUDED.runtime_ms,
         created_at = EXCLUDED.created_at`,
    )
    const row = await runSql(
      `SELECT bitstring, objective_value FROM optimization_results WHERE optimization_job_id = 'QOP-DBTEST-0007'`,
    )
    assert.equal(row.rows[0].bitstring, '111000')
    assert.equal(row.rows[0].objective_value, 0.45)
  } finally {
    await runSql('ROLLBACK')
  }
})

test('004: optimization_results enforces validation_status, quality bounds and id format', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_COMPLETED_JOB('QOP-DBTEST-0003'))
    await expectPgError(
      `INSERT INTO optimization_results (id, optimization_job_id, objective_value, validation_status)
       VALUES ('QOP-DBTEST-0003-R1', 'QOP-DBTEST-0003', 0.5, 'bogus')`,
      [],
      '23514',
      'chk_optimization_results_validation_status',
    )
    await expectPgError(
      `INSERT INTO optimization_results (id, optimization_job_id, objective_value, validation_status, approximation_quality)
       VALUES ('QOP-DBTEST-0003-R1', 'QOP-DBTEST-0003', 0.5, 'valid', 1.5)`,
      [],
      '23514',
      'chk_optimization_results_quality_bounded',
    )
    await expectPgError(
      `INSERT INTO optimization_results (id, optimization_job_id, objective_value, validation_status)
       VALUES ('NOT-A-MATCHING-ID', 'QOP-DBTEST-0003', 0.5, 'valid')`,
      [],
      '23514',
      'chk_optimization_results_id_matches',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('004: completed results are write-once — hard DELETE blocked, authorized bypass works', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_COMPLETED_JOB('QOP-DBTEST-0004'))
    await runSql(INSERT_RESULT('QOP-DBTEST-0004'))

    await expectPgError(
      `DELETE FROM optimization_results WHERE optimization_job_id = 'QOP-DBTEST-0004'`,
      [],
      'P0001',
    )
    await expectPgError(
      `DELETE FROM optimization_jobs WHERE id = 'QOP-DBTEST-0004'`,
      [],
      'P0001',
    )

    const stillThere = await runSql(`SELECT count(*)::int AS n FROM optimization_results WHERE optimization_job_id = 'QOP-DBTEST-0004'`)
    assert.equal(stillThere.rows[0].n, 1, 'blocked deletes must leave the result row intact')

    // Authorization/audit escape hatch (repository administrative cleanup):
    // with the GUC set the guarded hard delete is permitted.
    await runSql(`SET LOCAL "app.allow_optimization_delete" = 'true'`)
    await runSql(`DELETE FROM optimization_results WHERE optimization_job_id = 'QOP-DBTEST-0004'`)
    await runSql(`DELETE FROM optimization_jobs WHERE id = 'QOP-DBTEST-0004'`)
    const gone = await runSql(`SELECT count(*)::int AS n FROM optimization_jobs WHERE id = 'QOP-DBTEST-0004'`)
    assert.equal(gone.rows[0].n, 0)
  } finally {
    await runSql('ROLLBACK')
  }
})

test('004: non-completed jobs are not delete-guarded (queued/running remain removable)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(
      `INSERT INTO optimization_jobs (id, owner, status, problem_type, request, algorithm, execution_mode, backend)
       VALUES ('QOP-DBTEST-0005', 'admin', 'queued', 'sensor_placement', '{}'::jsonb, 'qaoa', 'simulator', 'qflare_simulator_statevector')`,
    )
    await runSql(`DELETE FROM optimization_jobs WHERE id = 'QOP-DBTEST-0005'`)
    const gone = await runSql(`SELECT count(*)::int AS n FROM optimization_jobs WHERE id = 'QOP-DBTEST-0005'`)
    assert.equal(gone.rows[0].n, 0)
  } finally {
    await runSql('ROLLBACK')
  }
})

test('004: audit + artifact tables cascade from their job', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_COMPLETED_JOB('QOP-DBTEST-0006'))
    await runSql(INSERT_RESULT('QOP-DBTEST-0006'))
    await runSql(
      `INSERT INTO optimization_job_audit (optimization_job_id, action, actor, reason)
       VALUES ('QOP-DBTEST-0006', 'soft_deleted', 'admin', 'approved cleanup')`,
    )
    await runSql(
      `INSERT INTO optimization_qubo_artifacts (optimization_job_id, variable_count, storage_reference, qubo)
       VALUES ('QOP-DBTEST-0006', 6, 'qflare://qubo/QOP-DBTEST-0006', '{"doc":{"variableCount":6}}'::jsonb)`,
    )
    await runSql(`SET LOCAL "app.allow_optimization_delete" = 'true'`)
    await runSql(`DELETE FROM optimization_jobs WHERE id = 'QOP-DBTEST-0006'`)
    const orphans = await runSql(
      `SELECT (SELECT count(*)::int FROM optimization_job_audit WHERE optimization_job_id = 'QOP-DBTEST-0006') AS audit,
              (SELECT count(*)::int FROM optimization_qubo_artifacts WHERE optimization_job_id = 'QOP-DBTEST-0006') AS artifacts`,
    )
    assert.equal(orphans.rows[0].audit, 0)
    assert.equal(orphans.rows[0].artifacts, 0)
  } finally {
    await runSql('ROLLBACK')
  }
})

test('migrations are reversible (004 down/up round-trips harmlessly)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(readMigration('004_optimization_persistence', 'down'))
    const afterDown = await runSql(
      `SELECT count(*)::int AS n FROM information_schema.tables WHERE table_schema = 'public'
         AND table_name IN ('optimization_results', 'optimization_job_audit', 'optimization_qubo_artifacts')`,
    )
    assert.equal(afterDown.rows[0].n, 0, '004 down should remove the persistence tables')

    await runSql(readMigration('004_optimization_persistence', 'up'))
    const afterUp = await runSql(
      `SELECT count(*)::int AS n FROM information_schema.tables WHERE table_schema = 'public'
         AND table_name IN ('optimization_results', 'optimization_job_audit', 'optimization_qubo_artifacts')`,
    )
    assert.equal(afterUp.rows[0].n, 3, '004 up should recreate the persistence tables')
  } finally {
    await runSql('ROLLBACK')
  }
})

// ────────────────────────────────────────────────────────────────────────────
// 005_optimization_qubo_metadata — the QUBO metadata audit layer.
//
// One row per job (qubo_id = <optimization_job_id>-Q1): small problems inline
// the full plain-JSON representation; larger problems are recorded by reference
// + sha-256 checksum + dimensions + location only — matrix cells are never
// embedded for artifact rows, and there is never a cell-per-row relational
// dump. No raw Python/Qiskit objects are persisted.
// ────────────────────────────────────────────────────────────────────────────

const METADATA_COLUMNS = [
  'qubo_id', 'optimization_job_id', 'storage_mode', 'variable_count',
  'matrix', 'linear_terms', 'quadratic_terms', 'penalty_configuration',
  'objective_expression', 'artifact_reference', 'checksum', 'matrix_dimensions',
  'storage_location', 'metadata', 'created_at',
]

const INSERT_QUEUED_JOB = (id: string): string =>
  `INSERT INTO optimization_jobs (id, owner, status, problem_type, request, algorithm, execution_mode, backend)
   VALUES ('${id}', 'admin', 'queued', 'sensor_placement', '{}'::jsonb, 'qaoa', 'simulator', 'qflare_simulator_statevector')`

const INSERT_INLINE_METADATA = (jobId: string, variableCount = 3): string =>
  `INSERT INTO optimization_qubo_metadata
     (qubo_id, optimization_job_id, storage_mode, variable_count,
      matrix, linear_terms, quadratic_terms, penalty_configuration, objective_expression)
   VALUES ('${jobId}-Q1', '${jobId}', 'inline', ${variableCount},
           '[[1,0,0,2],[0,1,0,2],[0,0,1,2]]'::jsonb,
           '[2,2,2]'::jsonb,
           '[[1,0,0],[0,1,0],[0,0,1]]'::jsonb,
           '{"penaltyScale":7,"offset":12}'::jsonb,
           '1.000 B1 + 1.000 B2 + 1.000 B3')`

const INSERT_ARTIFACT_METADATA = (jobId: string, variableCount = 24): string =>
  `INSERT INTO optimization_qubo_metadata
     (qubo_id, optimization_job_id, storage_mode, variable_count,
      artifact_reference, checksum, matrix_dimensions, storage_location, metadata)
   VALUES ('${jobId}-Q1', '${jobId}', 'artifact', ${variableCount},
           'qflare://qubo/${jobId}',
           'a' || repeat('b', 63),
           '{"variables":${variableCount},"rowCount":24,"columnCount":25}'::jsonb,
           'qflare://qubo/${jobId}',
           '{"problemType":"sensor_placement","algorithm":"qaoa","penaltyScale":7,"offset":12}'::jsonb)`

test('005: optimization_qubo_metadata stores the audit columns and required indexes', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    const table = await runSql(
      `SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'
         AND table_name = 'optimization_qubo_metadata'`,
    )
    assert.equal(table.rows.length, 1, '005 must create optimization_qubo_metadata')

    const columns = await runSql(
      `SELECT column_name FROM information_schema.columns WHERE table_schema = 'public'
         AND table_name = 'optimization_qubo_metadata' AND column_name = ANY($1::text[])`,
      [METADATA_COLUMNS],
    )
    assert.deepEqual(
      columns.rows.map((r) => r.column_name).sort(),
      [...METADATA_COLUMNS].sort(),
      'the metadata table must carry every audit column',
    )

    const indexes = await runSql(
      `SELECT indexname FROM pg_indexes WHERE schemaname = 'public'
         AND indexname IN ('idx_optimization_qubo_metadata_job', 'idx_optimization_qubo_metadata_created_at')`,
    )
    assert.equal(indexes.rows.length, 2, '005 must index optimization_job_id and created_at')
  } finally {
    await runSql('ROLLBACK')
  }
})

test('005: rejects orphan metadata rows (FK to optimization_jobs)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    // A full inline representation so the row clears every CHECK and only the
    // missing FK parent can reject it.
    await expectPgError(
      `INSERT INTO optimization_qubo_metadata
         (qubo_id, optimization_job_id, storage_mode, variable_count,
          matrix, linear_terms, quadratic_terms, penalty_configuration, objective_expression)
       VALUES ('QOP-DOES-NOT-EXIST-Q1', 'QOP-DOES-NOT-EXIST', 'inline', 2,
               '[[1,0,2]]'::jsonb, '[2]'::jsonb, '[[1]]'::jsonb,
               '{"penaltyScale":7,"offset":12}'::jsonb, 'x')`,
      [],
      '23503',
      'fk_optimization_qubo_metadata_job',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('005: inline rows must inline the full plain-JSON representation; artifact rows must reference', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_QUEUED_JOB('QOP-META-0001'))

    // An inline row missing any representation column is not a reproducible
    // record and must be rejected.
    await expectPgError(
      `INSERT INTO optimization_qubo_metadata
         (qubo_id, optimization_job_id, storage_mode, variable_count, linear_terms)
       VALUES ('QOP-META-0001-Q1', 'QOP-META-0001', 'inline', 3, '[2,2,2]'::jsonb)`,
      [],
      '23514',
      'chk_optimization_qubo_metadata_inline',
    )

    // An artifact row missing the checksum would defeat verification — rejected.
    await expectPgError(
      `INSERT INTO optimization_qubo_metadata
         (qubo_id, optimization_job_id, storage_mode, variable_count,
          artifact_reference, matrix_dimensions, storage_location, metadata)
       VALUES ('QOP-META-0001-Q1', 'QOP-META-0001', 'artifact', 24,
               'qflare://qubo/QOP-META-0001', '{"variables":24}'::jsonb,
               'qflare://qubo/QOP-META-0001', '{}'::jsonb)`,
      [],
      '23514',
      'chk_optimization_qubo_metadata_artifact',
    )

    // An unknown storage mode is never accepted.
    await expectPgError(
      `INSERT INTO optimization_qubo_metadata
         (qubo_id, optimization_job_id, storage_mode, variable_count, objective_expression)
       VALUES ('QOP-META-0001-Q1', 'QOP-META-0001', 'bogus', 3, 'nope')`,
      [],
      '23514',
      'chk_optimization_qubo_metadata_storage_mode',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('005: valid inline and artifact rows persist, artifact rows never embed the matrix', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_QUEUED_JOB('QOP-META-0002'))
    await runSql(INSERT_INLINE_METADATA('QOP-META-0002'))

    const inlineBack = await runSql(
      `SELECT storage_mode, variable_count, matrix, linear_terms, quadratic_terms,
              penalty_configuration, objective_expression, created_at
       FROM optimization_qubo_metadata WHERE optimization_job_id = 'QOP-META-0002'`,
    )
    const inline = inlineBack.rows[0]
    assert.equal(inline.storage_mode, 'inline')
    assert.equal(inline.variable_count, 3)
    assert.deepEqual(inline.matrix, [[1, 0, 0, 2], [0, 1, 0, 2], [0, 0, 1, 2]])
    assert.deepEqual(inline.linear_terms, [2, 2, 2])
    assert.deepEqual(inline.quadratic_terms, [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    assert.deepEqual(inline.penalty_configuration, { penaltyScale: 7, offset: 12 })
    assert.ok(String(inline.objective_expression).includes('B1'))
    assert.ok(inline.created_at instanceof Date, 'created_at should default to now()')

    await runSql(INSERT_QUEUED_JOB('QOP-META-0003'))
    await runSql(INSERT_ARTIFACT_METADATA('QOP-META-0003'))

    const artifactBack = await runSql(
      `SELECT storage_mode, variable_count, matrix, linear_terms, quadratic_terms,
              artifact_reference, checksum, matrix_dimensions, storage_location, metadata
       FROM optimization_qubo_metadata WHERE optimization_job_id = 'QOP-META-0003'`,
    )
    const artifact = artifactBack.rows[0]
    assert.equal(artifact.storage_mode, 'artifact')
    assert.equal(artifact.variable_count, 24)
    assert.equal(artifact.matrix, null, 'artifact rows must never embed the matrix cells')
    assert.equal(artifact.linear_terms, null)
    assert.equal(artifact.quadratic_terms, null)
    assert.equal(artifact.artifact_reference, 'qflare://qubo/QOP-META-0003')
    assert.equal(artifact.checksum, `a${'b'.repeat(63)}`)
    assert.deepEqual(artifact.matrix_dimensions, { variables: 24, rowCount: 24, columnCount: 25 })
    assert.equal(artifact.storage_location, 'qflare://qubo/QOP-META-0003')
    assert.equal(artifact.metadata.problemType, 'sensor_placement')
  } finally {
    await runSql('ROLLBACK')
  }
})

test('005: one metadata row per job (primary key + id format)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_QUEUED_JOB('QOP-META-0004'))
    // A full valid inline row first, so a duplicate hits the primary key,
    // not the inline-completeness check.
    await runSql(INSERT_INLINE_METADATA('QOP-META-0004'))
    await expectPgError(
      `INSERT INTO optimization_qubo_metadata
         (qubo_id, optimization_job_id, storage_mode, variable_count,
          matrix, linear_terms, quadratic_terms, penalty_configuration, objective_expression)
       VALUES ('QOP-META-0004-Q1', 'QOP-META-0004', 'inline', 3,
               '[[1,0,0,2]]'::jsonb, '[2]'::jsonb, '[[1]]'::jsonb,
               '{"penaltyScale":7,"offset":12}'::jsonb, 'dup')`,
      [],
      '23505',
      'optimization_qubo_metadata_pkey',
    )
    await expectPgError(
      `INSERT INTO optimization_qubo_metadata
         (qubo_id, optimization_job_id, storage_mode, variable_count, objective_expression)
       VALUES ('NOT-THE-KEYED-ID', 'QOP-META-0004', 'inline', 3, 'nope')`,
      [],
      '23514',
      'chk_optimization_qubo_metadata_id_matches',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('005: the repository upsert statement is idempotent (ON CONFLICT qubo_id)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_QUEUED_JOB('QOP-META-0005'))
    // First persist, then re-persist the same row via the exact repository
    // statement — must upsert on the primary key, not raise 42P10.
    await runSql(INSERT_INLINE_METADATA('QOP-META-0005'))
    await runSql(
      `INSERT INTO optimization_qubo_metadata (
         qubo_id, optimization_job_id, storage_mode, variable_count,
         matrix, linear_terms, quadratic_terms, penalty_configuration, objective_expression)
       VALUES ('QOP-META-0005-Q1', 'QOP-META-0005', 'inline', 4,
               '[[1,0,0,0,2]]'::jsonb, '[2,2,2,2]'::jsonb,
               '[[1]]'::jsonb, '{"penaltyScale":9,"offset":18}'::jsonb, 'resaved')
       ON CONFLICT (qubo_id) DO UPDATE SET
         variable_count = EXCLUDED.variable_count,
         matrix = EXCLUDED.matrix,
         linear_terms = EXCLUDED.linear_terms,
         quadratic_terms = EXCLUDED.quadratic_terms,
         penalty_configuration = EXCLUDED.penalty_configuration,
         objective_expression = EXCLUDED.objective_expression`,
    )
    const row = await runSql(
      `SELECT variable_count, objective_expression FROM optimization_qubo_metadata
        WHERE optimization_job_id = 'QOP-META-0005'`,
    )
    assert.equal(row.rows[0].variable_count, 4)
    assert.equal(row.rows[0].objective_expression, 'resaved')
  } finally {
    await runSql('ROLLBACK')
  }
})

test('005: metadata rows cascade from their job', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_QUEUED_JOB('QOP-META-0006'))
    await runSql(INSERT_INLINE_METADATA('QOP-META-0006'))
    await runSql(`DELETE FROM optimization_jobs WHERE id = 'QOP-META-0006'`)
    const orphans = await runSql(
      `SELECT count(*)::int AS n FROM optimization_qubo_metadata WHERE optimization_job_id = 'QOP-META-0006'`,
    )
    assert.equal(orphans.rows[0].n, 0, 'metadata must cascade with the job')
  } finally {
    await runSql('ROLLBACK')
  }
})

// ────────────────────────────────────────────────────────────────────────────
// 007_optimization_benchmark_reference — the classical benchmark snapshot.
//
// Extends optimization_results (no dedicated table): every other benchmark
// field (objectives, quantum runtime, constraint violations, problem size,
// exact experiment config, created_at) already persists in the results model.
// The snapshot must be WRITE-ONCE and each row must reference its job.

test('007: benchmark reference columns, checks, FK and index exist and round-trip', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_COMPLETED_JOB('QOP-DBTEST-0007'))
    await runSql(INSERT_RESULT('QOP-DBTEST-0007'))

    const columns = await runSql(
      `SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'optimization_results'
         AND column_name IN ('classical_solver','classical_runtime_ms','approximation_ratio','approximation_basis',
                             'approximation_invalid_reason','random_seed')`,
    )
    assert.equal(columns.rows.length, 6, '007 must add all six benchmark reference columns')

    // Every benchmark value lives on the result row, which is 1:1 with and
    // FK-bound to its optimization job.
    const fk = await runSql(
      `SELECT constraint_name FROM information_schema.table_constraints WHERE table_schema = 'public'
         AND table_name = 'optimization_results' AND constraint_name = 'fk_optimization_results_job'
         AND constraint_type = 'FOREIGN KEY'`,
    )
    assert.equal(fk.rows.length, 1, 'each result/benchmark row must reference its optimization job')

    const index = await runSql(
      `SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'optimization_results'
         AND indexname = 'idx_optimization_results_created_at'`,
    )
    assert.equal(index.rows.length, 1, '007 must index created_at for the newest-first ledger')

    // Boolean columns round-trip an exhaustive exact-optimum snapshot.
    await runSql(
      `UPDATE optimization_results SET classical_solver = 'exhaustive', classical_runtime_ms = 1.5,
         approximation_ratio = 1.0, approximation_basis = 'exact_optimal',
         approximation_invalid_reason = NULL, random_seed = 305419896
       WHERE optimization_job_id = 'QOP-DBTEST-0007'`,
    )
    const hit = await runSql(
      `SELECT classical_solver, classical_runtime_ms, approximation_ratio, approximation_basis,
              approximation_invalid_reason, random_seed
         FROM optimization_results WHERE optimization_job_id = 'QOP-DBTEST-0007'`,
    )
    assert.equal(hit.rows[0].classical_solver, 'exhaustive')
    assert.equal(hit.rows[0].classical_runtime_ms, 1.5)
    assert.equal(hit.rows[0].approximation_ratio, 1)
    assert.equal(hit.rows[0].approximation_basis, 'exact_optimal')
    assert.equal(hit.rows[0].approximation_invalid_reason, null)
    assert.equal(Number(hit.rows[0].random_seed), 305419896)

    // Checks reject unknown solver / basis / reason and negative ratios.
    await expectPgError(
      `UPDATE optimization_results SET classical_solver = 'genetic' WHERE optimization_job_id = 'QOP-DBTEST-0007'`,
      [],
      '23514',
      'chk_optimization_results_classical_solver',
    )
    await expectPgError(
      `UPDATE optimization_results SET approximation_basis = 'heuristic' WHERE optimization_job_id = 'QOP-DBTEST-0007'`,
      [],
      '23514',
      'chk_optimization_results_approximation_basis',
    )
    await expectPgError(
      `UPDATE optimization_results SET approximation_ratio = -0.5 WHERE optimization_job_id = 'QOP-DBTEST-0007'`,
      [],
      '23514',
      'chk_optimization_results_approximation_ratio_non_negative',
    )
    await expectPgError(
      `UPDATE optimization_results SET approximation_invalid_reason = 'UNKNOWN_CODE' WHERE optimization_job_id = 'QOP-DBTEST-0007'`,
      [],
      '23514',
      'chk_optimization_results_approximation_invalid_reason',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('007: a NULL ratio is only allowed with a known invalid-reason code (honest absence)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_COMPLETED_JOB('QOP-DBTEST-0008'))
    await runSql(INSERT_RESULT('QOP-DBTEST-0008'))

    // All four codes are accepted with a NULL ratio...
    for (const code of ['MISSING_CLASSICAL_REFERENCE', 'MISSING_QUANTUM_OBJECTIVE', 'OBJECTIVE_NOT_POSITIVE', 'QUANTUM_OBJECTIVE_NEGATIVE']) {
      await runSql(
        `UPDATE optimization_results SET approximation_ratio = NULL, approximation_invalid_reason = '${code}'
         WHERE optimization_job_id = 'QOP-DBTEST-0008'`,
      )
    }
    const stored = await runSql(
      `SELECT approximation_invalid_reason FROM optimization_results WHERE optimization_job_id = 'QOP-DBTEST-0008'`,
    )
    assert.equal(stored.rows[0].approximation_invalid_reason, 'QUANTUM_OBJECTIVE_NEGATIVE')

    // ...but an unknown reason is rejected (the column-set pair is honest).
    await expectPgError(
      `UPDATE optimization_results SET approximation_ratio = NULL, approximation_invalid_reason = 'NOT_A_CODE'
       WHERE optimization_job_id = 'QOP-DBTEST-0008'`,
      [],
      '23514',
      'chk_optimization_results_approximation_invalid_reason',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('migrations are reversible (007 down/up round-trips harmlessly)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(readMigration('007_optimization_benchmark_reference', 'down'))
    const afterDown = await runSql(
      `SELECT count(*)::int AS n FROM information_schema.columns WHERE table_schema = 'public'
         AND table_name = 'optimization_results'
         AND column_name IN ('approximation_ratio','random_seed','classical_solver')`,
    )
    assert.equal(afterDown.rows[0].n, 0, '007 down should remove the benchmark reference columns')

    await runSql(readMigration('007_optimization_benchmark_reference', 'up'))
    const afterUp = await runSql(
      `SELECT count(*)::int AS n FROM information_schema.columns WHERE table_schema = 'public'
         AND table_name = 'optimization_results'
         AND column_name IN ('approximation_ratio','random_seed','classical_solver')`,
    )
    assert.equal(afterUp.rows[0].n, 3, '007 up should recreate the benchmark reference columns')
  } finally {
    await runSql('ROLLBACK')
  }
})

// ────────────────────────────────────────────────────────────────────────────
// 008_optimization_result_validation — the final-result validation contract.
//
// optimization_jobs + optimization_results are the source of truth. Every
// stored result must stay FK-bound to its job, and an invalid result must
// remain distinguishable from a validated one (valid | invalid | pending).

test('008: validation columns, statuses, checks, FK and required indexes exist', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_COMPLETED_JOB('QOP-VAL-0001'))
    await runSql(INSERT_RESULT('QOP-VAL-0001'))

    const columns = await runSql(
      `SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'optimization_results'
         AND column_name IN ('validation_timestamp','validation_details','explanation_metadata')`,
    )
    assert.equal(columns.rows.length, 3, '008 must add the validation/explanation columns')

    // The job/result pair is the source of truth: each result FKs to its job.
    const fk = await runSql(
      `SELECT constraint_name FROM information_schema.table_constraints WHERE table_schema = 'public'
         AND table_name = 'optimization_results' AND constraint_name = 'fk_optimization_results_job'
         AND constraint_type = 'FOREIGN KEY'`,
    )
    assert.equal(fk.rows.length, 1, 'each result must reference its optimization job')

    const indexes = await runSql(
      `SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'optimization_results'
         AND indexname IN ('idx_optimization_results_job','idx_optimization_results_validation_status',
                           'idx_optimization_results_created_at')`,
    )
    assert.equal(indexes.rows.length, 3, '008 must guarantee the job/status/created_at indexes')

    // All three states are accepted...
    for (const status of ['valid', 'invalid', 'pending_validation']) {
      await runSql(
        `UPDATE optimization_results SET validation_status = '${status}' WHERE optimization_job_id = 'QOP-VAL-0001'`,
      )
    }
    // ...but an unknown state is not.
    await expectPgError(
      `UPDATE optimization_results SET validation_status = 'maybe' WHERE optimization_job_id = 'QOP-VAL-0001'`,
      [],
      '23514',
      'chk_optimization_results_validation_status',
    )

    // Details/metadata must be JSON objects (or honestly absent).
    await expectPgError(
      `UPDATE optimization_results SET validation_details = '"not-an-object"'::jsonb WHERE optimization_job_id = 'QOP-VAL-0001'`,
      [],
      '23514',
      'chk_optimization_results_validation_details',
    )
    await expectPgError(
      `UPDATE optimization_results SET explanation_metadata = '[]'::jsonb WHERE optimization_job_id = 'QOP-VAL-0001'`,
      [],
      '23514',
      'chk_optimization_results_explanation_metadata',
    )

    // A recorded verdict detail must carry the time it was recorded.
    await expectPgError(
      `UPDATE optimization_results
          SET validation_status = 'valid', validation_details = '{"status":"valid"}'::jsonb,
              validation_timestamp = NULL
        WHERE optimization_job_id = 'QOP-VAL-0001'`,
      [],
      '23514',
      'chk_optimization_results_validation_timestamp',
    )

    // The full validation + explanation payload round-trips.
    await runSql(
      `UPDATE optimization_results
          SET validation_status = 'valid',
              validation_timestamp = '2026-01-02T03:04:05Z',
              validation_details = '{"status":"valid","summary":"ok","violationCount":0,"violations":[]}'::jsonb,
              explanation_metadata = '{"objectiveBreakdown":[],"coverage":null,"quantumAdvantageClaimed":false}'::jsonb
        WHERE optimization_job_id = 'QOP-VAL-0001'`,
    )
    const hit = await runSql(
      `SELECT validation_status, validation_timestamp, validation_details, explanation_metadata
         FROM optimization_results WHERE optimization_job_id = 'QOP-VAL-0001'`,
    )
    assert.equal(hit.rows[0].validation_status, 'valid')
    assert.equal((hit.rows[0].validation_details as { summary: string }).summary, 'ok')
    assert.equal((hit.rows[0].explanation_metadata as { quantumAdvantageClaimed: boolean }).quantumAdvantageClaimed, false)
  } finally {
    await runSql('ROLLBACK')
  }
})

test('008: an invalid result stays distinguishable from a validated one', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    const states: Array<[string, string]> = [
      ['QOP-VAL-0010', 'valid'],
      ['QOP-VAL-0011', 'invalid'],
      ['QOP-VAL-0012', 'pending_validation'],
    ]
    for (const [jobId, status] of states) {
      await runSql(INSERT_COMPLETED_JOB(jobId))
      await runSql(INSERT_RESULT(jobId))
      await runSql(`UPDATE optimization_results SET validation_status = '${status}' WHERE optimization_job_id = '${jobId}'`)
    }

    const rows = await runSql(
      `SELECT optimization_job_id, validation_status FROM optimization_results
        WHERE optimization_job_id IN ('QOP-VAL-0010','QOP-VAL-0011','QOP-VAL-0012')
        ORDER BY optimization_job_id`,
    )
    assert.deepEqual(
      rows.rows.map((row) => row.validation_status),
      ['valid', 'invalid', 'pending_validation'],
      'the three validation states must remain distinct in storage',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('008: optimization_results still rejects orphan rows (FK) and duplicates', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await expectPgError(
      `INSERT INTO optimization_results (id, optimization_job_id, objective_value, validation_status)
       VALUES ('QOP-VAL-ORPHAN-R1', 'QOP-VAL-ORPHAN', 1, 'pending_validation')`,
      [],
      '23503',
      'fk_optimization_results_job',
    )

    await runSql(INSERT_COMPLETED_JOB('QOP-VAL-0020'))
    await runSql(INSERT_RESULT('QOP-VAL-0020'))
    await expectPgError(
      `INSERT INTO optimization_results (id, optimization_job_id, objective_value, validation_status)
       VALUES ('QOP-VAL-0020-R1', 'QOP-VAL-0020', 0.1, 'valid')`,
      [],
      '23505',
      'optimization_results_pkey',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('migrations are reversible (008 down/up round-trips harmlessly)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(readMigration('008_optimization_result_validation', 'down'))
    const afterDown = await runSql(
      `SELECT count(*)::int AS n FROM information_schema.columns WHERE table_schema = 'public'
         AND table_name = 'optimization_results'
         AND column_name IN ('validation_timestamp','validation_details','explanation_metadata')`,
    )
    assert.equal(afterDown.rows[0].n, 0, '008 down should remove the validation/explanation columns')

    await runSql(readMigration('008_optimization_result_validation', 'up'))
    const afterUp = await runSql(
      `SELECT count(*)::int AS n FROM information_schema.columns WHERE table_schema = 'public'
         AND table_name = 'optimization_results'
         AND column_name IN ('validation_timestamp','validation_details','explanation_metadata')`,
    )
    assert.equal(afterUp.rows[0].n, 3, '008 up should recreate the validation/explanation columns')
  } finally {
    await runSql('ROLLBACK')
  }
})

test('migrations are reversible (005 down/up round-trips harmlessly)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(readMigration('005_optimization_qubo_metadata', 'down'))
    const afterDown = await runSql(
      `SELECT count(*)::int AS n FROM information_schema.tables WHERE table_schema = 'public'
         AND table_name = 'optimization_qubo_metadata'`,
    )
    assert.equal(afterDown.rows[0].n, 0, '005 down should remove the metadata table')

    await runSql(readMigration('005_optimization_qubo_metadata', 'up'))
    const afterUp = await runSql(
      `SELECT count(*)::int AS n FROM information_schema.tables WHERE table_schema = 'public'
         AND table_name = 'optimization_qubo_metadata'`,
    )
    assert.equal(afterUp.rows[0].n, 1, '005 up should recreate the metadata table')
  } finally {
    await runSql('ROLLBACK')
  }
})