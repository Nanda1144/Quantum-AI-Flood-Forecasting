/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import type { ForecastRepository } from '../repositories/repositories.ts'
import type { ForecastClient } from '../clients/ai-service.client.ts'
import type { SystemHealth } from '../types/domain.ts'

export class StatusService {
  constructor(
    private readonly forecastRepo: ForecastRepository,
    private readonly aiClient: ForecastClient,
  ) {}

  async getHealth(): Promise<SystemHealth> {
    const latest = await this.forecastRepo.getLatest()
    const { available, latencyMs } = await this.aiClientProbe()

    const status: SystemHealth['status'] = available
      ? 'online'
      : latest
        ? 'degraded'
        : 'unavailable'

    return {
      status,
      apiLatencyMs: latencyMs,
      lastSuccessfulPrediction: latest?.predictionTimestamp ?? null,
      dataFreshness: latest?.createdAt ? this.formatFreshness(latest.createdAt) : null,
    }
  }

  private async aiClientProbe(): Promise<{ available: boolean; latencyMs: number | null }> {
    try {
      const result = await this.aiClient.health()
      return { available: result.health.status === 'online', latencyMs: result.latencyMs }
    } catch {
      return { available: false, latencyMs: null }
    }
  }

  private formatFreshness(createdAt: string): string {
    const seconds = Math.max(0, Math.floor((Date.now() - new Date(createdAt).getTime()) / 1000))
    if (seconds < 60) return `${seconds}s`
    return `${Math.floor(seconds / 60)}m`
  }
}