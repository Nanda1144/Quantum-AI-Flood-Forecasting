/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  CoverageRequirement,
  ObjectiveWeights,
  OptimizationInputsResult,
  OptimizationProblemType,
  OptimizeRequest,
  OptimizationResult,
  PipelineStage,
  PipelineUpdate,
  QuantumBackend,
  RiskProfile,
  ExecutionMode,
  QuantumModalKind,
} from '../types/optimization'
import { PIPELINE_STAGES, PROBLEM_TYPES } from '../lib/quantum'
import { getOptimizationAdapter, type ProblemInputsRequest, type OptimizationAdapter } from '../services/optimization/adapter'

export interface QuantumConfig {
  problemType: OptimizationProblemType
  candidateCount: number
  maxSensors: number
  budgetK: number | null
  forecastReference: string
  riskProfile: RiskProfile
  executionMode: ExecutionMode
  hardwareEnabled: boolean
  backend: QuantumBackend
  shots: number
  layers: number
}

export type RunState = 'idle' | 'running' | 'done' | 'error' | 'aborted'

export interface InitialQuantumState {
  forecastReference?: string
  riskProfile?: RiskProfile
}

const DEFAULT_CONFIG: QuantumConfig = {
  problemType: 'sensor_placement',
  candidateCount: 24,
  maxSensors: 6,
  budgetK: null,
  forecastReference: '',
  riskProfile: 'MEDIUM',
  executionMode: 'simulator',
  hardwareEnabled: false,
  backend: 'aer_simulator_statevector',
  shots: 4096,
  layers: 3,
}

export const DEFAULT_WEIGHTS: ObjectiveWeights = {
  risk: 0.5,
  populationCoverage: 0.5,
  infrastructureCoverage: 0.5,
  communication: 0.5,
  cost: 0.5,
  redundancy: 0.5,
}

export function useQuantumOptimization(initial?: InitialQuantumState) {
  const [config, setConfig] = useState<QuantumConfig>(() => ({
    ...DEFAULT_CONFIG,
    forecastReference: initial?.forecastReference ?? DEFAULT_CONFIG.forecastReference,
    riskProfile: initial?.riskProfile ?? DEFAULT_CONFIG.riskProfile,
  }))
  const [weights, setWeights] = useState<ObjectiveWeights>({ ...DEFAULT_WEIGHTS })
  const [normalizeWeights, setNormalizeWeights] = useState(true)
  const [coverageRequirements, setCoverageRequirements] = useState<CoverageRequirement[]>([])

  const [adapter, setAdapter] = useState<OptimizationAdapter | null>(null)
  const [adapterMode, setAdapterMode] = useState<'mock' | 'http' | null>(null)
  const [inputs, setInputs] = useState<OptimizationInputsResult | null>(null)
  const [inputsLoading, setInputsLoading] = useState(false)

  const [runState, setRunState] = useState<RunState>('idle')
  const [runError, setRunError] = useState<string | null>(null)
  const [stages, setStages] = useState<PipelineStage[]>(() =>
    PIPELINE_STAGES.map((stage) => ({ ...stage, status: 'pending', meta: {} })),
  )
  const [result, setResult] = useState<OptimizationResult | null>(null)
  const [activeModal, setActiveModal] = useState<QuantumModalKind | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const requestIdRef = useRef(0)

  useEffect(() => {
    let cancelled = false
    getOptimizationAdapter().then((instance) => {
      if (!cancelled) {
        setAdapter(instance)
        setAdapterMode(instance.mode)
      }
    })
    return () => {
      cancelled = true
    }
  }, [])

  const refreshInputs = useCallback(
    async (req: ProblemInputsRequest) => {
      const instance = await getOptimizationAdapter()
      setInputsLoading(true)
      try {
        const loaded = await instance.getInputs(req)
        setInputs(loaded)
        setConfig((prev) => {
          const next = {
            ...prev,
            maxSensors: Math.min(prev.maxSensors, loaded.constraints.maxSensors),
          }
          return next.maxSensors === prev.maxSensors ? prev : next
        })
      } catch {
        setInputs(null)
      } finally {
        setInputsLoading(false)
      }
    },
    [],
  )

  useEffect(() => {
    refreshInputs({
      candidateCount: config.candidateCount,
      forecastReference: config.forecastReference,
      riskProfile: config.riskProfile,
    })
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [config.candidateCount, config.forecastReference])

  const updateConfig = useCallback((patch: Partial<QuantumConfig>) => {
    setConfig((prev) => ({ ...prev, ...patch }))
  }, [])

  const updateWeights = useCallback((key: keyof ObjectiveWeights, value: number) => {
    setWeights((prev) => ({ ...prev, [key]: Math.max(0, Math.min(1, value)) }))
  }, [])

  const resetWeights = useCallback(() => setWeights({ ...DEFAULT_WEIGHTS }), [])
  const toggleNormalize = useCallback((value: boolean) => setNormalizeWeights(value), [])
  const addCoverageRequirement = useCallback((req: CoverageRequirement) => {
    setCoverageRequirements((prev) => [...prev, req])
  }, [])
  const removeCoverageRequirement = useCallback((origin: string) => {
    setCoverageRequirements((prev) => prev.filter((req) => req.origin !== origin))
  }, [])

  const startRun = useCallback(async () => {
    const instance = adapter ?? (await getOptimizationAdapter())
    const request: OptimizeRequest = {
      problemType: config.problemType,
      candidateCount: config.candidateCount,
      maxSensors: config.maxSensors,
      budgetK: config.budgetK,
      forecastReference: config.forecastReference,
      riskProfile: config.riskProfile,
      executionMode: config.hardwareEnabled ? 'hardware' : 'simulator',
      hardwareEnabled: config.hardwareEnabled,
      backend: config.backend,
      shots: config.shots,
      layers: config.layers,
      weights,
      normalizeWeights,
      coverageRequirements,
    }

    const requestId = ++requestIdRef.current
    const controller = new AbortController()
    abortRef.current?.abort()
    abortRef.current = controller

    setRunState('running')
    setRunError(null)
    setResult(null)
    setStages(() => PIPELINE_STAGES.map((stage) => ({ ...stage, status: 'pending', meta: {} })))

    const handleUpdate = (update: PipelineUpdate) => {
      if (requestId !== requestIdRef.current) return
      setStages((prev) =>
        prev.map((stage) => (stage.id === update.stageId ? { ...stage, status: update.status, error: update.error } : stage)),
      )
    }

    try {
      const completed = await instance.run(request, handleUpdate, controller.signal)
      if (requestId !== requestIdRef.current) return
      setResult(completed)
      setRunState('done')
    } catch (error) {
      if (requestId !== requestIdRef.current) return
      if (error instanceof DOMException && error.name === 'AbortError') {
        setRunState('aborted')
        setRunError('Run aborted by operator.')
        return
      }
      const message = error instanceof Error ? error.message : 'Quantum run failed.'
      setRunState('error')
      setRunError(message)
    }
  }, [adapter, config, weights, normalizeWeights, coverageRequirements])

  const cancelRun = useCallback(() => {
    requestIdRef.current += 1
    abortRef.current?.abort()
    setRunState('aborted')
    setRunError('Run aborted by operator.')
  }, [])

  const newRun = useCallback(() => {
    requestIdRef.current += 1
    abortRef.current?.abort()
    setRunState('idle')
    setRunError(null)
    setResult(null)
    setStages(() => PIPELINE_STAGES.map((stage) => ({ ...stage, status: 'pending', meta: {} })))
  }, [])

  const openModal = useCallback((kind: QuantumModalKind) => setActiveModal(kind), [])
  const closeModal = useCallback(() => setActiveModal(null), [])

  const problem = useMemo(() => PROBLEM_TYPES[config.problemType], [config.problemType])

  return {
    config,
    updateConfig,
    weights,
    updateWeights,
    resetWeights,
    normalizeWeights,
    toggleNormalize,
    coverageRequirements,
    addCoverageRequirement,
    removeCoverageRequirement,
    inputs,
    inputsLoading,
    adapterMode,
    runState,
    runError,
    stages,
    result,
    activeModal,
    startRun,
    cancelRun,
    newRun,
    openModal,
    closeModal,
    problem,
  }
}

export type QuantumOptimizationHook = ReturnType<typeof useQuantumOptimization>