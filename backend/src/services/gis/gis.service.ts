/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend/gis | License: Apache-2.0
 */

import fs from 'node:fs'
import path from 'node:path'

export interface GISSensor {
  id: string
  name: string
  basin: string
  latitude: number
  longitude: number
  sensorType: string
  status: string
  waterLevel?: number
  rainfall?: number
}

export interface GISCandidate {
  id: string
  name: string
  basin: string
  latitude: number
  longitude: number
  floodRisk: number
  populationRisk: number
  damProximity: number
  roadAccess: number
  priorityScore: number
  priorityLevel: string
}

export interface GISInfrastructure {
  dams: Array<{ name: string; river: string; basin: string; latitude: number; longitude: number; status: string }>
  hospitals: Array<{ id: string; name: string; basin: string; latitude: number; longitude: number; capacity: number; status: string }>
  shelters: Array<{ id: string; name: string; basin: string; latitude: number; longitude: number; capacity: number; status: string }>
}

export class GISService {
  private baseDir: string

  constructor(baseDir?: string) {
    // Resolve project root gis/data directory
    this.baseDir = baseDir ?? path.resolve(process.cwd(), '..', 'gis', 'data')
    if (!fs.existsSync(this.baseDir)) {
      this.baseDir = path.resolve(process.cwd(), 'gis', 'data')
    }
  }

  private parseCSV(filePath: string): Array<Record<string, string>> {
    if (!fs.existsSync(filePath)) return []
    const raw = fs.readFileSync(filePath, 'utf-8')
    const lines = raw.split(/\r?\n/).filter((l) => l.trim().length > 0)
    if (lines.length < 2) return []
    const headers = lines[0].split(',').map((h) => h.trim())
    return lines.slice(1).map((line) => {
      const parts = line.split(',').map((p) => p.trim())
      const record: Record<string, string> = {}
      headers.forEach((h, idx) => {
        record[h] = parts[idx] ?? ''
      })
      return record
    })
  }

  getSensors(): GISSensor[] {
    const records = this.parseCSV(path.join(this.baseDir, 'sensors.csv'))
    if (records.length === 0) {
      return [
        { id: 'S001', name: 'Krishna Water Level Sensor', basin: 'Krishna', latitude: 16.20, longitude: 80.00, sensorType: 'Water Level', status: 'Active', waterLevel: 7.8, rainfall: 82.4 },
        { id: 'S002', name: 'Srisailam Dam Sensor', basin: 'Krishna', latitude: 16.08, longitude: 78.87, sensorType: 'Dam Monitoring', status: 'Active', waterLevel: 6.2, rainfall: 45.1 },
        { id: 'S003', name: 'Godavari Water Level Sensor', basin: 'Godavari', latitude: 17.30, longitude: 81.80, sensorType: 'Water Level', status: 'Active', waterLevel: 8.5, rainfall: 94.0 },
        { id: 'S004', name: 'Polavaram Dam Sensor', basin: 'Godavari', latitude: 17.25, longitude: 81.65, sensorType: 'Dam Monitoring', status: 'Active', waterLevel: 5.9, rainfall: 38.6 },
      ]
    }
    return records.map((r, i) => ({
      id: r.id || `S00${i + 1}`,
      name: r.name || `Sensor ${i + 1}`,
      basin: r.basin || 'Krishna',
      latitude: parseFloat(r.latitude) || 16.2,
      longitude: parseFloat(r.longitude) || 80.0,
      sensorType: r.sensor_type || 'Water Level',
      status: r.status || 'Active',
      waterLevel: 5.0 + (i * 1.2),
      rainfall: 40.0 + (i * 15.0),
    }))
  }

  getCandidates(): GISCandidate[] {
    const records = this.parseCSV(path.join(this.baseDir, 'candidate_sensors.csv'))
    if (records.length === 0) {
      return [
        { id: 'C001', name: 'Krishna Candidate 1', basin: 'Krishna', latitude: 16.25, longitude: 80.05, floodRisk: 90, populationRisk: 80, damProximity: 70, roadAccess: 85, priorityScore: 82.75, priorityLevel: 'High' },
        { id: 'C002', name: 'Krishna Candidate 2', basin: 'Krishna', latitude: 16.15, longitude: 79.95, floodRisk: 75, populationRisk: 70, damProximity: 90, roadAccess: 80, priorityScore: 77.5, priorityLevel: 'Medium' },
        { id: 'C003', name: 'Godavari Candidate 1', basin: 'Godavari', latitude: 17.35, longitude: 81.75, floodRisk: 90, populationRisk: 85, damProximity: 75, roadAccess: 80, priorityScore: 84.25, priorityLevel: 'High' },
        { id: 'C004', name: 'Godavari Candidate 2', basin: 'Godavari', latitude: 17.20, longitude: 81.70, floodRisk: 80, populationRisk: 75, damProximity: 90, roadAccess: 85, priorityScore: 81.5, priorityLevel: 'High' },
      ]
    }
    return records.map((r, i) => {
      const fRisk = parseFloat(r.flood_risk) || 75
      const pRisk = parseFloat(r.population_risk) || 70
      const dProx = parseFloat(r.dam_proximity) || 60
      const rAcc = parseFloat(r.road_access) || 70
      const score = Math.round((fRisk * 0.4 + pRisk * 0.25 + dProx * 0.2 + rAcc * 0.15) * 100) / 100
      return {
        id: r.id || `C00${i + 1}`,
        name: r.name || `Candidate Site ${i + 1}`,
        basin: r.basin || 'Krishna',
        latitude: parseFloat(r.latitude) || 16.2,
        longitude: parseFloat(r.longitude) || 80.0,
        floodRisk: fRisk,
        populationRisk: pRisk,
        damProximity: dProx,
        roadAccess: rAcc,
        priorityScore: score,
        priorityLevel: score >= 80 ? 'High' : score >= 60 ? 'Medium' : 'Low',
      }
    })
  }

  getInfrastructure(): GISInfrastructure {
    const damsRaw = this.parseCSV(path.join(this.baseDir, 'dams.csv'))
    const hospitalsRaw = this.parseCSV(path.join(this.baseDir, 'hospitals.csv'))
    const sheltersRaw = this.parseCSV(path.join(this.baseDir, 'shelters.csv'))

    return {
      dams: damsRaw.map((d) => ({
        name: d.name,
        river: d.river,
        basin: d.basin,
        latitude: parseFloat(d.latitude) || 16.0,
        longitude: parseFloat(d.longitude) || 79.0,
        status: d.status || 'Operational',
      })),
      hospitals: hospitalsRaw.map((h) => ({
        id: h.id,
        name: h.name,
        basin: h.basin,
        latitude: parseFloat(h.latitude) || 16.3,
        longitude: parseFloat(h.longitude) || 80.4,
        capacity: parseInt(h.capacity, 10) || 300,
        status: h.status || 'Available',
      })),
      shelters: sheltersRaw.map((s) => ({
        id: s.id,
        name: s.name,
        basin: s.basin,
        latitude: parseFloat(s.latitude) || 16.3,
        longitude: parseFloat(s.longitude) || 80.4,
        capacity: parseInt(s.capacity, 10) || 500,
        status: s.status || 'Open',
      })),
    }
  }

  getRivers() {
    return [
      { name: 'Krishna River', basin: 'Krishna', lengthKm: 1400, dischargeCusecs: 185000, floodStageMeters: 12.5, currentLevelMeters: 9.8, status: 'WATCH' },
      { name: 'Godavari River', basin: 'Godavari', lengthKm: 1465, dischargeCusecs: 240000, floodStageMeters: 14.0, currentLevelMeters: 12.2, status: 'WARNING' },
      { name: 'Tungabhadra River', basin: 'Krishna', lengthKm: 531, dischargeCusecs: 85000, floodStageMeters: 9.0, currentLevelMeters: 6.5, status: 'NORMAL' },
    ]
  }

  getFloodZones() {
    return [
      { id: 'FZ-01', name: 'Krishna Delta Lowlands', basin: 'Krishna', severity: 'HIGH', affectedPopulation: 142000, inundationRisk: 0.88 },
      { id: 'FZ-02', name: 'Godavari Estuary East', basin: 'Godavari', severity: 'CRITICAL', affectedPopulation: 215000, inundationRisk: 0.94 },
      { id: 'FZ-03', name: 'Srisailam Downstream Belt', basin: 'Krishna', severity: 'MEDIUM', affectedPopulation: 64000, inundationRisk: 0.62 },
      { id: 'FZ-04', name: 'Polavaram Basin Backwater', basin: 'Godavari', severity: 'HIGH', affectedPopulation: 118000, inundationRisk: 0.81 },
    ]
  }
}
