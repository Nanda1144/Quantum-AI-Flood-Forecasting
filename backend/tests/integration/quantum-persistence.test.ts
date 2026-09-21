/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Quantum job persistence integration tests (migration 006).
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

// ────────────────────────────────────────────────────────────────────────────
// 006_quantum_job_persistence — the Nanda quantum job persistence layer.
// ────────────────────────────────────────────────────────────────────────────

const INSERT_COMPLETED_JOB = (id: string): string =>
  `INSERT INTO optimization_jobs (id, owner, status, problem_type, request, algorithm, execution_mode, backend)
   VALUES ('${id}', 'admin', 'completed', 'sensor_placement', '{}'::jsonb, 'qaoa', 'simulator', 'qflare_simulator_statevector')`

const INSERT_QUANTUM_JOB = (id: string, optimizationJobId: string): string =>
  `INSERT INTO quantum_jobs
     (id, optimization_job_id, algorithm, backend, execution_mode, qubits, shots, layers, status)
   VALUES ('${id}', '${optimizationJobId}', 'qaoa', 'qflare_simulator_statevector', 'simulator', 6, 1024, 2, 'completed')`

const INSERT_QUANTUM_RESULT = (quantumJobId: string): string =>
  `INSERT INTO quantum_results
     (id, quantum_job_id, bitstring, counts, objective_value, runtime_ms)
   VALUES ('${quantumJobId}-R1', '${quantumJobId}', '101010', '{"101010":728}'::jsonb, -1.42, 4)`

test('006: quantum persistence tables, columns and indexes exist', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    const tables = await runSql(
      `SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'
         AND table_name IN ('quantum_jobs', 'quantum_results')`,
    )
    assert.equal(tables.rows.length, 2, '006 must create quantum_jobs and quantum_results')

    const jobColumns = await runSql(
      `SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'quantum_jobs'
         AND column_name IN ('id','optimization_job_id','algorithm','backend','execution_mode','qubits',
                             'shots','layers','status','submitted_at','started_at','completed_at',
                             'error_code','error_message','created_at')`,
    )
    assert.equal(jobColumns.rows.length, 15, 'quantum_jobs must carry every spec column')

    const resultColumns = await runSql(
      `SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'quantum_results'
         AND column_name IN ('id','quantum_job_id','bitstring','counts','objective_value','runtime_ms',
                             'raw_metadata_reference','created_at')`,
    )
    assert.equal(resultColumns.rows.length, 8, 'quantum_results must carry every spec column')

    const indexes = await runSql(
      `SELECT indexname FROM pg_indexes WHERE schemaname = 'public'
         AND indexname IN ('idx_quantum_jobs_optimization_job','idx_quantum_jobs_status',
                           'idx_quantum_jobs_created_at','idx_quantum_results_quantum_job',
                           'idx_quantum_results_created_at')`,
    )
    assert.equal(indexes.rows.length, 5, '006 must satisfy the required index set (optimization_job_id, status, created_at, quantum_job_id)')
  } finally {
    await runSql('ROLLBACK')
  }
})

test('006: quantum_jobs rejects orphan rows (FK to optimization_jobs)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await expectPgError(
      `INSERT INTO quantum_jobs
         (id, optimization_job_id, algorithm, backend, execution_mode, shots, layers, status)
       VALUES ('QJ-ORPHAN-000001', 'QOP-DOES-NOT-EXIST', 'qaoa', 'qflare_simulator_statevector', 'simulator', 1024, 2, 'queued')`,
      [],
      '23503',
      'fk_quantum_jobs_optimization_job',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('006: quantum_results rejects orphan rows (FK to quantum_jobs)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await expectPgError(
      `INSERT INTO quantum_results (id, quantum_job_id, bitstring, counts)
       VALUES ('QJ-ORPHAN-000999-R1', 'QJ-ORPHAN-000999', '101010', '{"101010":1}'::jsonb)`,
      [],
      '23503',
      'fk_quantum_results_job',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('006: quantum_jobs rejects unknown execution modes and statuses', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_COMPLETED_JOB('QOP-QJT-0001'))
    await expectPgError(
      `INSERT INTO quantum_jobs
         (id, optimization_job_id, algorithm, backend, execution_mode, shots, layers, status)
       VALUES ('QJ-QJT-000001', 'QOP-QJT-0001', 'qaoa', 'bogus', 'fpga', 1024, 2, 'queued')`,
      [],
      '23514',
      'chk_quantum_jobs_execution_mode',
    )
    await expectPgError(
      `INSERT INTO quantum_jobs
         (id, optimization_job_id, algorithm, backend, execution_mode, shots, layers, status)
       VALUES ('QJ-QJT-000002', 'QOP-QJT-0001', 'qaoa', 'qflare_simulator_statevector', 'simulator', 1024, 2, 'exploded')`,
      [],
      '23514',
      'chk_quantum_jobs_status',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('006: quantum_jobs enforces submitted/started/completed timestamp order', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_COMPLETED_JOB('QOP-QJT-0002'))
    await expectPgError(
      `INSERT INTO quantum_jobs
         (id, optimization_job_id, algorithm, backend, execution_mode, shots, layers, status,
          submitted_at, started_at, completed_at)
       VALUES ('QJ-QJT-000003', 'QOP-QJT-0002', 'qaoa', 'qflare_simulator_statevector', 'simulator', 1024, 2, 'completed',
               '2026-09-16T09:00:00Z', '2026-09-16T09:00:00Z', '2026-09-16T08:59:00Z')`,
      [],
      '23514',
      'chk_quantum_jobs_timestamps',
    )
    await expectPgError(
      `INSERT INTO quantum_jobs
         (id, optimization_job_id, algorithm, backend, execution_mode, shots, layers, status,
          submitted_at, started_at)
       VALUES ('QJ-QJT-000009', 'QOP-QJT-0002', 'qaoa', 'qflare_simulator_statevector', 'simulator', 1024, 2, 'running',
               '2026-09-16T09:05:00Z', '2026-09-16T09:04:00Z')`,
      [],
      '23514',
      'chk_quantum_jobs_timestamps',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('006: quantum_results id must match <quantum_job_id>-R1', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_COMPLETED_JOB('QOP-QJT-0003'))
    await runSql(INSERT_QUANTUM_JOB('QJ-QJT-000004', 'QOP-QJT-0003'))
    await expectPgError(
      `INSERT INTO quantum_results (id, quantum_job_id, bitstring, counts)
       VALUES ('WRONG-FORMAT', 'QJ-QJT-000004', '101010', '{"101010":1}'::jsonb)`,
      [],
      '23514',
      'chk_quantum_results_id_matches',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('006: one result row per quantum job (primary key)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_COMPLETED_JOB('QOP-QJT-0004'))
    await runSql(INSERT_QUANTUM_JOB('QJ-QJT-000005', 'QOP-QJT-0004'))
    await runSql(INSERT_QUANTUM_RESULT('QJ-QJT-000005'))
    await expectPgError(
      `INSERT INTO quantum_results (id, quantum_job_id, bitstring, counts)
       VALUES ('QJ-QJT-000005-R1', 'QJ-QJT-000005', '000000', '{"000000":1}'::jsonb)`,
      [],
      '23505',
      'quantum_results_pkey',
    )
  } finally {
    await runSql('ROLLBACK')
  }
})

test('006: a completed quantum job round-trips outcome + plain-JSON counts + objective', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_COMPLETED_JOB('QOP-QJT-0005'))
    await runSql(INSERT_QUANTUM_JOB('QJ-QJT-000006', 'QOP-QJT-0005'))
    await runSql(INSERT_QUANTUM_RESULT('QJ-QJT-000006'))

    const row = await runSql(
      `SELECT j.id, j.optimization_job_id, j.status, r.bitstring, r.counts, r.objective_value, r.runtime_ms, r.created_at
         FROM quantum_jobs j JOIN quantum_results r ON r.quantum_job_id = j.id
        WHERE j.id = 'QJ-QJT-000006'`,
    )
    const hit = row.rows[0]
    assert.equal(hit.id, 'QJ-QJT-000006')
    assert.equal(hit.optimization_job_id, 'QOP-QJT-0005')
    assert.equal(hit.status, 'completed')
    assert.equal(hit.bitstring, '101010')
    assert.deepEqual(hit.counts, { '101010': 728 })
    assert.equal(hit.objective_value, -1.42)
    assert.equal(hit.runtime_ms, 4)
    assert.ok(hit.created_at instanceof Date, 'created_at should default to now()')
  } finally {
    await runSql('ROLLBACK')
  }
})

test('006: both cascades apply — result with its job, jobs with their pipeline job', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(INSERT_COMPLETED_JOB('QOP-QJT-0006'))
    await runSql(INSERT_QUANTUM_JOB('QJ-QJT-000007', 'QOP-QJT-0006'))
    await runSql(INSERT_QUANTUM_RESULT('QJ-QJT-000007'))

    // Deleting the optimization job must cascade to quantum_jobs and through
    // to quantum_results. Completed optimization jobs are delete-guarded (004),
    // so the authorized/audited GUC is required — as the repository does.
    await runSql(`SET LOCAL "app.allow_optimization_delete" = 'true'`)
    await runSql(`DELETE FROM optimization_jobs WHERE id = 'QOP-QJT-0006'`)
    const orphans = await runSql(
      `SELECT (SELECT count(*)::int FROM quantum_jobs WHERE optimization_job_id = 'QOP-QJT-0006') AS jobs,
              (SELECT count(*)::int FROM quantum_results WHERE quantum_job_id = 'QJ-QJT-000007') AS results`,
    )
    assert.equal(orphans.rows[0].jobs, 0, 'quantum_jobs must cascade with the optimization job')
    assert.equal(orphans.rows[0].results, 0, 'quantum_results must cascade with their quantum job')
  } finally {
    await runSql('ROLLBACK')
  }
})

test('migrations are reversible (006 down/up round-trips harmlessly)', async (t) => {
  if (!available) return t.skip(skipReason)
  await runSql('BEGIN')
  try {
    await runSql(readMigration('006_quantum_job_persistence', 'down'))
    const afterDown = await runSql(
      `SELECT count(*)::int AS n FROM information_schema.tables WHERE table_schema = 'public'
         AND table_name IN ('quantum_jobs', 'quantum_results')`,
    )
    assert.equal(afterDown.rows[0].n, 0, '006 down should remove both quantum tables')

    await runSql(readMigration('006_quantum_job_persistence', 'up'))
    const afterUp = await runSql(
      `SELECT count(*)::int AS n FROM information_schema.tables WHERE table_schema = 'public'
         AND table_name IN ('quantum_jobs', 'quantum_results')`,
    )
    assert.equal(afterUp.rows[0].n, 2, '006 up should recreate both quantum tables')
  } finally {
    await runSql('ROLLBACK')
  }
})