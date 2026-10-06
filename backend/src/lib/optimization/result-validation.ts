/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Backend integrity audit for a stored optimization result.
 *
 * The optimization service / database is the source of truth: the API never
 * recalculates a result from values a client supplies. Instead this module
 * re-derives everything from STORED measurements and the deterministic inputs
 * the pipeline consumed, so a corrupted or tampered row is detected rather than
 * presented as an operational recommendation:
 *
 *   1. result_status                  the job completed and the recorded status is consistent
 *   2. candidate_source               the deterministic candidate set is reproducible
 *   3. bitstring_maps_to_variables    the bitstring maps onto the known variables
 *   4. selected_candidates_exist      every selected location id is a known candidate
 *   5. constraints_satisfied          the decoded solution satisfies the configured constraints
 *   6. objective_consistent           the stored objective matches the decoded solution
 *
 * A failed audit never deletes or hides the record — the result is preserved
 * for debugging/research — but the caller must not expose it as a valid
 * recommendation (`recommendation.eligible = false`).
 */

import type {
  CandidateLocation,
  OptimizationJob,
  ResultIntegrityCheckId,
  ResultIntegrityReport,
} from '../../types/optimization.ts'
import { computeObjective, validateConstraints } from './qubo.ts'

/** Objective recomputation tolerance — avoids float-formatting false positives. */
export const OBJECTIVE_TOLERANCE = 1e-3

interface CheckSpec {
  id: ResultIntegrityCheckId
  label: string
  passed: boolean
  detail: string
}

function report(checks: CheckSpec[]): ResultIntegrityReport {
  const failed = checks.filter((check) => !check.passed).map((check) => check.id)
  return {
    valid: failed.length === 0,
    checks,
    failed,
    summary:
      failed.length === 0
        ? 'All backend integrity checks passed — the result is internally consistent with the stored inputs and measurements.'
        : `Backend integrity audit failed: ${failed.join(', ')}. The stored result is preserved for debugging/research but must not be treated as an operational recommendation.`,
  }
}

/**
 * Audit a completed job's result against its stored inputs.
 *
 * `candidates` is the deterministic candidate set re-fetched from the same
 * reference the pipeline used; `sourceError` is set when that source could not
 * be reproduced (in which case the result can never be attested as valid).
 */
export function auditOptimizationResult(
  job: OptimizationJob,
  candidates: CandidateLocation[] | null,
  sourceError?: string,
): ResultIntegrityReport {
  const result = job.result
  const checks: CheckSpec[] = []

  // 1. result_status — the job must be completed and carry a RECORDED verdict
  //    ('valid' | 'invalid'). A 'pending_validation' result has no verdict yet,
  //    so it is well-formed but cannot be attested: it fails this check and is
  //    never exposed as a recommendation.
  const recordedVerdict = result?.validationStatus === 'valid' || result?.validationStatus === 'invalid'
  const statusOk =
    job.status === 'completed' &&
    result !== null &&
    recordedVerdict &&
    (job.validationStatus === null || job.validationStatus === result.validationStatus)
  checks.push({
    id: 'result_status',
    label: 'Result status',
    passed: statusOk,
    detail: statusOk
      ? `Job is completed and the recorded validation status ('${result?.validationStatus}') is well-formed and consistent with the job record.`
      : `Expected a completed job with a recorded 'valid' | 'invalid' verdict; got job status '${job.status}', job validation '${job.validationStatus ?? 'null'}', result validation '${result?.validationStatus ?? 'null'}'.`,
  })

  // 2. candidate_source — without a reproducible input set nothing below can be
  //    attested honestly, so the audit fails closed.
  if (!candidates) {
    checks.push({
      id: 'candidate_source',
      label: 'Candidate source',
      passed: false,
      detail: sourceError
        ? `Candidate source could not be reproduced: ${sourceError}`
        : 'Candidate source could not be reproduced.',
    })
  } else {
    checks.push({
      id: 'candidate_source',
      label: 'Candidate source',
      passed: true,
      detail: `Reproduced ${candidates.length} candidate site(s) from the stored reference.`,
    })
  }

  const bitstring = result?.bitstring ?? ''

  // 3. bitstring_maps_to_variables — well-formed and the right length.
  const expectedVariables = job.variablesCount ?? result?.qubits ?? candidates?.length ?? null
  const bitstringOk =
    candidates !== null &&
    typeof bitstring === 'string' &&
    bitstring.length > 0 &&
    expectedVariables !== null &&
    bitstring.length === expectedVariables &&
    bitstring.length === candidates.length &&
    /^[01]+$/.test(bitstring)
  checks.push({
    id: 'bitstring_maps_to_variables',
    label: 'Bitstring maps to variables',
    passed: bitstringOk,
    detail: bitstringOk
      ? `Bitstring has ${bitstring.length} bits and maps one-to-one onto the ${candidates!.length} known candidate variables.`
      : `Bitstring '${bitstring || '(empty)'}' does not map onto ${expectedVariables ?? 'unknown'} known variables (${candidates?.length ?? 'unreproduced'} candidates).`,
  })

  // 4. selected_candidates_exist — decode + cross-check the selected ids.
  const decodedSelected = candidates && bitstringOk ? candidates.filter((_, index) => bitstring[index] === '1') : []
  const knownIds = new Set((candidates ?? []).map((site) => site.id))
  const selectedIds = (result?.selectedLocations ?? []).map((site) => site.id)
  const decodedIds = decodedSelected.map((site) => site.id)
  const unknownIds = selectedIds.filter((id) => !knownIds.has(id))
  const selectionMatches =
    candidates !== null &&
    bitstringOk &&
    unknownIds.length === 0 &&
    selectedIds.length === decodedIds.length &&
    selectedIds.every((id, index) => id === decodedIds[index])
  checks.push({
    id: 'selected_candidates_exist',
    label: 'Selected candidates exist',
    passed: selectionMatches,
    detail: selectionMatches
      ? `All ${selectedIds.length} selected location id(s) exist in the candidate set and match the decoded bitstring.`
      : unknownIds.length > 0
        ? `Selected location id(s) not present in the candidate set: ${unknownIds.join(', ')}.`
        : `Selected locations ${JSON.stringify(selectedIds)} do not match the decoded bitstring ${JSON.stringify(decodedIds)}.`,
  })

  // 5. constraints_satisfied — re-validate from stored config, then compare with
  //    what the row claims (an emptied violation list over a real violation is
  //    exactly the corruption this catches).
  const requirements = job.constraints?.coverageRequirements ?? job.request.coverageRequirements
  const revalidated = candidates && bitstringOk ? validateConstraints(decodedSelected, job.request, requirements) : null
  const storedViolations = result?.constraintViolations ?? []
  const constraintsOk =
    revalidated !== null &&
    revalidated.violations.length === 0 &&
    storedViolations.length === 0 &&
    result?.validationStatus === 'valid'
  checks.push({
    id: 'constraints_satisfied',
    label: 'Constraints satisfied',
    passed: constraintsOk,
    detail: constraintsOk
      ? 'The decoded solution satisfies the configured constraints and the stored violation list is empty.'
      : revalidated === null
        ? 'Constraints could not be re-validated because the solution did not decode over the candidate set.'
        : revalidated.violations.length > 0
          ? `Re-validation found violations not reflected as valid: ${revalidated.violations.map((v) => v.message).join(' ')}`
          : `The stored result claims ${storedViolations.length} violation(s) with validation status '${result?.validationStatus ?? 'null'}'.`,
  })

  // 6. objective_consistent — recompute from the decoded solution.
  const recomputed = candidates && bitstringOk ? computeObjective(job.request, candidates, decodedSelected) : null
  const storedObjective = result?.objectiveValue ?? null
  const objectiveOk =
    recomputed !== null &&
    storedObjective !== null &&
    Number.isFinite(storedObjective) &&
    Math.abs(recomputed.objectiveValue - storedObjective) <= OBJECTIVE_TOLERANCE
  checks.push({
    id: 'objective_consistent',
    label: 'Objective consistent',
    passed: objectiveOk,
    detail: objectiveOk
      ? `Stored objective ${storedObjective} matches the recomputed objective ${recomputed!.objectiveValue.toFixed(4)} (tolerance ${OBJECTIVE_TOLERANCE}).`
      : recomputed === null || storedObjective === null
        ? 'Objective could not be recomputed from the stored solution.'
        : `Stored objective ${storedObjective} does not match the recomputed objective ${recomputed.objectiveValue.toFixed(4)} (tolerance ${OBJECTIVE_TOLERANCE}).`,
  })

  return report(checks)
}
