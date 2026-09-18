import { Router } from 'express'
import { z } from 'zod'
import type { Container } from '../container.ts'
import { success } from '../envelope.ts'
import { authenticate } from '../middleware/authorize.ts'
import {
  compareModelsBodySchema,
  comparisonQuerySchema,
  listModelsQuerySchema,
  listPredictionsQuerySchema,
  modelDetailParamsSchema,
} from '../middleware/schemas.ts'
import { validate } from '../middleware/validate.ts'
import { config } from '../config.ts'

export function aiRoutes(c: Container): Router {
  const router = Router()

  router.use(authenticate(c.auth, config.AUTH_ENABLED))

  /** GET /api/ai/analytics — latest AI analytics summary for the dashboard. */
  router.get('/analytics', async (_req, res, next) => {
    try {
      const snapshot = await c.analytics.getSnapshot(config.FRESHNESS_STALE_MS)
      res.json(success(snapshot))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/ai/predictions — paginated, filterable recent predictions. */
  router.get('/predictions', validate({ query: listPredictionsQuerySchema }), async (req, res, next) => {
    try {
      const q = req.validated!.query as z.infer<typeof listPredictionsQuerySchema>
      const result = await c.predictions.query({
        page: q.page,
        limit: q.limit,
        from: q.from,
        to: q.to,
        risk: q.risk,
        modelId: q.model,
      })
      res.json(success(result))
    } catch (error) {
      next(error)
    }
  })

  /**
   * GET /api/ai/models/comparison — registry versions with their latest stored
   * evaluation, sorted/filtered server-side. Registered before the
   * `:id` routes so "comparison" never matches a numeric id.
   */
  router.get('/models/comparison', validate({ query: comparisonQuerySchema }), async (req, res, next) => {
    try {
      const q = req.validated!.query as z.infer<typeof comparisonQuerySchema>
      const result = await c.modelsComparison.compare({
        sort: q.sort,
        direction: q.direction,
        from: q.from,
        to: q.to,
        status: q.status,
      })
      res.json(success(result))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/ai/models — paginated, filterable model-version registry. */
  router.get('/models', validate({ query: listModelsQuerySchema }), async (req, res, next) => {
    try {
      const q = req.validated!.query as z.infer<typeof listModelsQuerySchema>
      res.json(
        success(
          await c.modelsRegistry.list({
            page: q.page,
            limit: q.limit,
            status: q.status,
            algorithm: q.algorithm,
            dataset: q.dataset,
          }),
        ),
      )
    } catch (error) {
      next(error)
    }
  })

  /**
   * POST /api/ai/models/compare — aggregate latest stored metrics for the
   * requested versions and apply the documented selection policy. Static path
   * registered before `/models/:id` so "compare" never matches :id.
   */
  router.post('/models/compare', validate({ body: compareModelsBodySchema }), async (req, res, next) => {
    try {
      const { model_ids } = req.validated!.body as z.infer<typeof compareModelsBodySchema>
      res.json(success(await c.modelsRegistry.compare(model_ids)))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/ai/models/:id — complete metadata for one registry version. */
  router.get('/models/:id', validate({ params: modelDetailParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof modelDetailParamsSchema>
      res.json(success(await c.modelsRegistry.getModel(id)))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/ai/models/:id/metrics — historical evaluation scores (newest first). */
  router.get('/models/:id/metrics', validate({ params: modelDetailParamsSchema }), async (req, res, next) => {
    try {
      const { id } = req.validated!.params as z.infer<typeof modelDetailParamsSchema>
      res.json(success(await c.modelsRegistry.getMetricHistory(id)))
    } catch (error) {
      next(error)
    }
  })

  /** GET /api/ai/status — AI availability, latency, freshness. */
  router.get('/status', async (_req, res, next) => {
    try {
      const health = await c.status.getHealth()
      res.json(success(health))
    } catch (error) {
      next(error)
    }
  })

  return router
}