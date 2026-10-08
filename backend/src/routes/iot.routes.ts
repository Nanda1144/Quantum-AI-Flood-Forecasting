/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend/routes | License: Apache-2.0
 */

import { Router } from 'express'
import { success } from '../envelope.ts'
import { SensorService } from '../services/iot/sensor.service.ts'

export function iotRoutes(sensorService = new SensorService()): Router {
  const router = Router()

  /** GET /api/iot/health */
  router.get('/health', (_req, res) => {
    res.json(success({ status: 'ok', service: 'iot-telemetry' }))
  })

  /** POST /api/iot/live-sensor */
  router.post('/live-sensor', (req, res) => {
    const reading = sensorService.ingest(req.body)
    res.status(201).json(success(reading))
  })

  /** GET /api/iot/latest-data */
  router.get('/latest-data', (_req, res) => {
    res.json(success(sensorService.getLatestReadings()))
  })

  /** GET /api/iot/sensors */
  router.get('/sensors', (_req, res) => {
    res.json(success(sensorService.getLatestReadings()))
  })

  /** GET /api/iot/dashboard */
  router.get('/dashboard', (_req, res) => {
    res.json(success(sensorService.getDashboardSummary()))
  })

  /** POST /api/iot/simulation/start */
  router.post('/simulation/start', (req, res) => {
    const scenario = req.body?.scenario || 'HEAVY_RAIN'
    const session = sensorService.startSimulation(scenario)
    res.json(success(session))
  })

  /** POST /api/iot/simulation/stop */
  router.post('/simulation/stop', (_req, res) => {
    const result = sensorService.stopSimulation()
    res.json(success(result))
  })

  /** GET /api/iot/simulation/status */
  router.get('/simulation/status', (_req, res) => {
    res.json(success(sensorService.getSimulationStatus()))
  })

  /** POST /api/iot/seed */
  router.post('/seed', (_req, res) => {
    res.json(success({ message: 'Sensors seeded successfully.' }))
  })

  return router
}
