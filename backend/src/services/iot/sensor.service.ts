/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend/iot | License: Apache-2.0
 */

export interface SensorReading {
  id: string
  sensorId: string
  timestamp: string
  latitude: number
  longitude: number
  waterLevel: number
  rainfall: number
  flowRate: number
  temperature: number
  battery: number
  status: 'ONLINE' | 'WARNING' | 'CRITICAL' | 'OFFLINE'
  riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
}

export interface SimulationSession {
  id: string
  scenario: 'NORMAL' | 'MODERATE_RAIN' | 'HEAVY_RAIN' | 'CRITICAL_FLOOD'
  status: 'RUNNING' | 'STOPPED'
  startedAt: string
  stoppedAt?: string
  generatedCount: number
}

export class SensorService {
  private readings: Map<string, SensorReading> = new Map()
  private history: SensorReading[] = []
  private activeSimulation: SimulationSession | null = null
  private simulationTimer: NodeJS.Timeout | null = null

  constructor() {
    this.seedDefaultSensors()
  }

  private seedDefaultSensors() {
    const defaults: SensorReading[] = [
      {
        id: 'READING-101',
        sensorId: 'SENSOR-KG-01',
        timestamp: new Date().toISOString(),
        latitude: 16.518,
        longitude: 80.619,
        waterLevel: 7.8,
        rainfall: 82.4,
        flowRate: 68.2,
        temperature: 28.5,
        battery: 92,
        status: 'WARNING',
        riskLevel: 'HIGH',
      },
      {
        id: 'READING-102',
        sensorId: 'SENSOR-SRI-02',
        timestamp: new Date().toISOString(),
        latitude: 16.083,
        longitude: 78.868,
        waterLevel: 5.4,
        rainfall: 44.0,
        flowRate: 42.1,
        temperature: 29.1,
        battery: 88,
        status: 'ONLINE',
        riskLevel: 'MEDIUM',
      },
      {
        id: 'READING-103',
        sensorId: 'SENSOR-POL-03',
        timestamp: new Date().toISOString(),
        latitude: 17.250,
        longitude: 81.650,
        waterLevel: 8.9,
        rainfall: 96.5,
        flowRate: 85.0,
        temperature: 27.2,
        battery: 76,
        status: 'CRITICAL',
        riskLevel: 'CRITICAL',
      },
      {
        id: 'READING-104',
        sensorId: 'SENSOR-RAJ-04',
        timestamp: new Date().toISOString(),
        latitude: 17.000,
        longitude: 81.783,
        waterLevel: 6.8,
        rainfall: 58.2,
        flowRate: 54.3,
        temperature: 29.8,
        battery: 95,
        status: 'ONLINE',
        riskLevel: 'MEDIUM',
      },
    ]

    for (const r of defaults) {
      this.readings.set(r.sensorId, r)
      this.history.push(r)
    }
  }

  ingest(payload: Partial<SensorReading> & { sensorId: string; waterLevel: number }): SensorReading {
    const prev = this.readings.get(payload.sensorId)
    const waterLevel = payload.waterLevel
    const rainfall = payload.rainfall ?? prev?.rainfall ?? 50.0

    let riskLevel: SensorReading['riskLevel'] = 'LOW'
    let status: SensorReading['status'] = 'ONLINE'

    if (waterLevel > 8.0 || rainfall > 90) {
      riskLevel = 'CRITICAL'
      status = 'CRITICAL'
    } else if (waterLevel > 7.0 || rainfall > 70) {
      riskLevel = 'HIGH'
      status = 'WARNING'
    } else if (waterLevel > 5.5 || rainfall > 40) {
      riskLevel = 'MEDIUM'
      status = 'ONLINE'
    }

    const reading: SensorReading = {
      id: `READING-${Date.now()}`,
      sensorId: payload.sensorId,
      timestamp: payload.timestamp || new Date().toISOString(),
      latitude: payload.latitude ?? prev?.latitude ?? 16.5,
      longitude: payload.longitude ?? prev?.longitude ?? 80.5,
      waterLevel,
      rainfall,
      flowRate: payload.flowRate ?? prev?.flowRate ?? 50.0,
      temperature: payload.temperature ?? prev?.temperature ?? 28.0,
      battery: payload.battery ?? prev?.battery ?? 90,
      status: payload.status ?? status,
      riskLevel: payload.riskLevel ?? riskLevel,
    }

    this.readings.set(reading.sensorId, reading)
    this.history.unshift(reading)
    if (this.history.length > 500) {
      this.history.pop()
    }
    return reading
  }

  getLatestReadings(): SensorReading[] {
    return Array.from(this.readings.values())
  }

  getDashboardSummary() {
    const list = this.getLatestReadings()
    const highestWater = list.reduce((m, r) => Math.max(m, r.waterLevel), 0)
    const avgRainfall = list.length > 0 ? list.reduce((s, r) => s + r.rainfall, 0) / list.length : 0
    const criticalCount = list.filter((r) => r.riskLevel === 'CRITICAL').length
    const highCount = list.filter((r) => r.riskLevel === 'HIGH').length
    const mediumCount = list.filter((r) => r.riskLevel === 'MEDIUM').length
    const lowCount = list.filter((r) => r.riskLevel === 'LOW').length

    return {
      totalSensors: list.length,
      highestWaterLevel: Math.round(highestWater * 10) / 10,
      averageRainfall: Math.round(avgRainfall * 10) / 10,
      activeAlertsCount: criticalCount + highCount,
      riskDistribution: {
        critical: criticalCount,
        high: highCount,
        medium: mediumCount,
        low: lowCount,
      },
      latestReadings: list,
    }
  }

  startSimulation(scenario: SimulationSession['scenario']) {
    this.stopSimulation()
    const session: SimulationSession = {
      id: `SIM-${Date.now()}`,
      scenario,
      status: 'RUNNING',
      startedAt: new Date().toISOString(),
      generatedCount: 0,
    }
    this.activeSimulation = session

    this.simulationTimer = setInterval(() => {
      if (!this.activeSimulation || this.activeSimulation.status !== 'RUNNING') return
      for (const [id, prev] of this.readings.entries()) {
        const delta = (Math.random() - 0.45) * 0.4
        const multiplier = scenario === 'CRITICAL_FLOOD' ? 1.5 : scenario === 'HEAVY_RAIN' ? 1.2 : 1.0
        const newWater = Math.max(2.0, Math.min(12.0, prev.waterLevel + (delta * multiplier)))
        const newRain = Math.max(10.0, Math.min(180.0, prev.rainfall + (delta * 5 * multiplier)))
        this.ingest({
          sensorId: id,
          waterLevel: Math.round(newWater * 10) / 10,
          rainfall: Math.round(newRain * 10) / 10,
          latitude: prev.latitude,
          longitude: prev.longitude,
        })
      }
      session.generatedCount += this.readings.size
    }, 4000)

    return session
  }

  stopSimulation() {
    if (this.simulationTimer) {
      clearInterval(this.simulationTimer)
      this.simulationTimer = null
    }
    if (this.activeSimulation) {
      this.activeSimulation.status = 'STOPPED'
      this.activeSimulation.stoppedAt = new Date().toISOString()
      const result = { ...this.activeSimulation }
      this.activeSimulation = null
      return result
    }
    return { status: 'STOPPED' }
  }

  getSimulationStatus() {
    return {
      isActive: this.activeSimulation?.status === 'RUNNING',
      activeSession: this.activeSimulation,
      totalGenerated: this.activeSimulation?.generatedCount ?? 0,
    }
  }
}
