/**
 * HTTP client for the AI FastAPI forecasting service.
 *
 * This client is the ONLY place the backend couples to Navya's service. It
 * depends on the payload contract (`../types/contract.ts`), never on Navya's
 * internal implementation — so she can swap XGBoost/LSTM/GRU freely.
 */

import { config } from '../config.ts'
import { EnvelopeError } from '../utils/errors.ts'
import type {
  AIHealthContract,
  AIServiceEnvelope,
  ForecastContract,
  ForecastPointContract,
  ModelInfoContract,
  PredictionRecordContract,
  RiskAnalyticsContract,
} from '../types/contract.ts'

export interface ForecastClient {
  health(): Promise<{ health: AIHealthContract; latencyMs: number }>
  getLatestForecast(horizonHours?: number): Promise<ForecastContract>
  getForecastSeries(hours?: number): Promise<ForecastPointContract[]>
  getRiskAnalytics(): Promise<RiskAnalyticsContract>
  getModels(): Promise<ModelInfoContract[]>
  getRecentPredictions(limit?: number): Promise<PredictionRecordContract[]>
}

class AIRequestError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'AIRequestError'
  }
}

/** Unwrap an envelope body and reject on contract violations. */
function unwrap<T>(body: AIServiceEnvelope<T>, path: string): T {
  if (!body || body.success !== true || body.data === undefined) {
    const code = body?.error?.code ?? 'AI_SERVICE_ERROR'
    const message = body?.error?.message ?? `AI service response for ${path} was invalid`
    throw new EnvelopeError(code, message)
  }
  return body.data
}

export class AIServiceClient implements ForecastClient {
  private readonly baseUrl = config.AI_SERVICE_URL.replace(/\/$/, '')
  private readonly timeoutMs = config.AI_REQUEST_TIMEOUT_MS

  private async request<T>(path: string, timeoutMs = this.timeoutMs): Promise<{ body: AIServiceEnvelope<T>; latencyMs: number }> {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    const started = performance.now()
    try {
      const response = await fetch(`${this.baseUrl}${path}`, {
        signal: controller.signal,
        headers: { Accept: 'application/json' },
      })
      const latencyMs = Math.round(performance.now() - started)
      if (!response.ok) {
        let body: AIServiceEnvelope<T> | null = null
        try {
          body = (await response.json()) as AIServiceEnvelope<T>
        } catch {
          /* non-JSON body */
        }
        throw new EnvelopeError(
          body?.error?.code ?? 'AI_SERVICE_ERROR',
          body?.error?.message ?? `AI service returned HTTP ${response.status} for ${path}`,
        )
      }
      return { body: (await response.json()) as AIServiceEnvelope<T>, latencyMs }
    } catch (error) {
      if (error instanceof EnvelopeError) throw error
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new AIRequestError(`AI service request to ${path} timed out`)
      }
      throw new AIRequestError(`AI service unreachable: ${error instanceof Error ? error.message : String(error)}`)
    } finally {
      clearTimeout(timer)
    }
  }

  async health(): Promise<{ health: AIHealthContract; latencyMs: number }> {
    let result: { body: AIServiceEnvelope<AIHealthContract>; latencyMs: number }
    try {
      result = await this.request<AIHealthContract>('/health', 2500)
    } catch (error) {
      if (isUnavailable(error)) throw new EnvelopeError('AI_SERVICE_UNAVAILABLE', 'AI service is currently unavailable')
      throw error
    }
    return { health: unwrap(result.body, '/health'), latencyMs: result.latencyMs }
  }

  async getLatestForecast(horizonHours = 24): Promise<ForecastContract> {
    try {
      const { body } = await this.request<ForecastContract>(
        `/api/ai/forecast/latest?horizon_hours=${encodeURIComponent(horizonHours)}`,
      )
      return unwrap(body, '/api/ai/forecast/latest')
    } catch (error) {
      throw mapUnavailable(error)
    }
  }

  async getForecastSeries(hours = 24): Promise<ForecastPointContract[]> {
    const { body } = await this.request<{ points: ForecastPointContract[] }>(
      `/api/ai/forecast/series?hours=${encodeURIComponent(hours)}`,
    )
    return unwrap(body, '/api/ai/forecast/series').points
  }

  async getRiskAnalytics(): Promise<RiskAnalyticsContract> {
    const { body } = await this.request<RiskAnalyticsContract>('/api/ai/risk-analytics')
    return unwrap(body, '/api/ai/risk-analytics')
  }

  async getModels(): Promise<ModelInfoContract[]> {
    const { body } = await this.request<ModelInfoContract[]>('/api/ai/models')
    return unwrap(body, '/api/ai/models')
  }

  async getRecentPredictions(limit = 6): Promise<PredictionRecordContract[]> {
    const { body } = await this.request<PredictionRecordContract[]>(
      `/api/ai/predictions?limit=${encodeURIComponent(limit)}`,
    )
    return unwrap(body, '/api/ai/predictions')
  }
}

function mapUnavailable(error: unknown): unknown {
  if (error instanceof AIRequestError || (error instanceof EnvelopeError && error.code === 'AI_SERVICE_ERROR')) {
    return new EnvelopeError('AI_SERVICE_UNAVAILABLE', 'AI service is currently unavailable')
  }
  return error
}

function isUnavailable(error: unknown): boolean {
  return error instanceof AIRequestError
}