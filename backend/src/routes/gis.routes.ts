/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend/routes | License: Apache-2.0
 */

import { Router } from 'express'
import { success } from '../envelope.ts'
import { GISService } from '../services/gis/gis.service.ts'

export function gisRoutes(gisService = new GISService()): Router {
  const router = Router()

  /** GET /api/gis/health */
  router.get('/health', (_req, res) => {
    res.json(success({ status: 'ok', service: 'gis' }))
  })

  /** GET /api/gis/sensors */
  router.get('/sensors', (_req, res) => {
    res.json(success(gisService.getSensors()))
  })

  /** GET /api/gis/candidate-locations */
  router.get('/candidate-locations', (_req, res) => {
    res.json(success(gisService.getCandidates()))
  })

  /** GET /api/gis/infrastructure */
  router.get('/infrastructure', (_req, res) => {
    res.json(success(gisService.getInfrastructure()))
  })

  /** GET /api/gis/rivers */
  router.get('/rivers', (_req, res) => {
    res.json(success(gisService.getRivers()))
  })

  /** GET /api/gis/flood-zones */
  router.get('/flood-zones', (_req, res) => {
    res.json(success(gisService.getFloodZones()))
  })

  /** GET /api/gis/basins */
  router.get('/basins', (_req, res) => {
    res.json(
      success([
        { name: 'Krishna Basin', areaSqKm: 258948, majorRivers: ['Krishna', 'Tungabhadra', 'Bhima'], monitoringSensors: 14 },
        { name: 'Godavari Basin', areaSqKm: 312812, majorRivers: ['Godavari', 'Pranhita', 'Indravati'], monitoringSensors: 18 },
      ]),
    )
  })

  return router
}
