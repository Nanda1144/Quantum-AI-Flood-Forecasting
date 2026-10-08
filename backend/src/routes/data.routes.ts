/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend/routes | License: Apache-2.0
 */

import { Router } from 'express'
import { AppError, ErrorCodes, success } from '../envelope.ts'
import { DataService } from '../services/data/data.service.ts'

export function dataRoutes(dataService = new DataService()): Router {
  const router = Router()

  /** GET /api/data/health */
  router.get('/health', (_req, res) => {
    res.json(success({ status: 'ok', service: 'data-management' }))
  })

  /** GET /api/data/datasets */
  router.get('/datasets', (_req, res) => {
    res.json(success(dataService.getDatasets()))
  })

  /** GET /api/data/datasets/:id */
  router.get('/datasets/:id', (req, res, next) => {
    const id = parseInt(req.params.id, 10)
    const item = dataService.getDataset(id)
    if (!item) {
      next(new AppError(404, ErrorCodes.BAD_REQUEST, `Dataset ${id} not found`))
      return
    }
    res.json(success(item))
  })

  /** GET /api/data/datasets/:id/preview */
  router.get('/datasets/:id/preview', (req, res, next) => {
    const id = parseInt(req.params.id, 10)
    const preview = dataService.preview(id)
    if (!preview) {
      next(new AppError(404, ErrorCodes.BAD_REQUEST, `Dataset ${id} not found`))
      return
    }
    res.json(success(preview))
  })

  /** POST /api/data/validate/:id */
  router.post('/validate/:id', (req, res, next) => {
    const id = parseInt(req.params.id, 10)
    const q = dataService.validate(id)
    if (!q) {
      next(new AppError(404, ErrorCodes.BAD_REQUEST, `Dataset ${id} not found`))
      return
    }
    res.json(success(q))
  })

  /** GET /api/data/quality/:id */
  router.get('/quality/:id', (req, res, next) => {
    const id = parseInt(req.params.id, 10)
    const q = dataService.getQuality(id)
    if (!q) {
      next(new AppError(404, ErrorCodes.BAD_REQUEST, `Dataset ${id} quality record not found`))
      return
    }
    res.json(success(q))
  })

  /** POST /api/data/preprocess/:id */
  router.post('/preprocess/:id', (req, res, next) => {
    const id = parseInt(req.params.id, 10)
    const result = dataService.preprocess(id)
    if (!result) {
      next(new AppError(404, ErrorCodes.BAD_REQUEST, `Dataset ${id} not found`))
      return
    }
    res.json(success(result))
  })

  /** GET /api/data/import-history */
  router.get('/import-history', (_req, res) => {
    res.json(success(dataService.getImportHistory()))
  })

  return router
}
