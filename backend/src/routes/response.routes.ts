/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend/routes | License: Apache-2.0
 */

import { Router } from 'express'
import { success } from '../envelope.ts'
import { ResponseService } from '../services/response/response.service.ts'

export function responseRoutes(responseService = new ResponseService()): Router {
  const router = Router()

  /** GET /api/response/health */
  router.get('/health', (_req, res) => {
    res.json(success({ status: 'ok', service: 'response-planning' }))
  })

  /** GET /api/response/plans */
  router.get('/plans', (_req, res) => {
    res.json(success(responseService.getPlans()))
  })

  /** GET /api/response/active */
  router.get('/active', (_req, res) => {
    res.json(success(responseService.getActivePlan()))
  })

  /** GET /api/response/plan/:id */
  router.get('/plan/:id', (req, res) => {
    const plan = responseService.getPlan(req.params.id)
    if (!plan) {
      res.status(404).json({ success: false, error: { code: 'PLAN_NOT_FOUND', message: 'Response plan not found' } })
      return
    }
    res.json(success(plan))
  })

  /** POST /api/response/plan */
  router.post('/plan', (req, res) => {
    const created = responseService.createPlan(req.body || {})
    res.status(201).json(success(created))
  })

  /** GET /api/response/evacuation-zones */
  router.get('/evacuation-zones', (_req, res) => {
    const active = responseService.getActivePlan()
    res.json(success(active?.zones || []))
  })

  /** GET /api/response/resource-deployment */
  router.get('/resource-deployment', (_req, res) => {
    const active = responseService.getActivePlan()
    res.json(
      success({
        allocatedRescueBoats: active?.allocatedRescueBoats ?? 45,
        allocatedMedicalTeams: active?.allocatedMedicalTeams ?? 28,
        allocatedShelters: active?.allocatedShelters ?? 8,
        totalEvacuees: active?.totalEvacuees ?? 357000,
      }),
    )
  })

  return router
}
