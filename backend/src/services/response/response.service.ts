/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: backend/response | License: Apache-2.0
 */

export interface EvacuationZone {
  zoneId: string
  zoneName: string
  basin: string
  riskLevel: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  estimatedPopulation: number
  evacuationPriority: 1 | 2 | 3 | 4
  designatedShelter: string
  safeRouteStatus: 'OPEN' | 'CONGESTED' | 'BLOCKED'
  assignedRescueBoats: number
  assignedMedicalTeams: number
}

export interface ResponsePlan {
  planId: string
  version: number
  generatedAt: string
  triggerSource: 'QUANTUM_OPTIMIZATION' | 'AI_FORECAST' | 'OPERATOR_OVERRIDE'
  overallRisk: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  totalEvacuees: number
  allocatedRescueBoats: number
  allocatedMedicalTeams: number
  allocatedShelters: number
  zones: EvacuationZone[]
  status: 'ACTIVE' | 'DRAFT' | 'SUPERSEDED'
}

export class ResponseService {
  private plans: Map<string, ResponsePlan> = new Map()

  constructor() {
    this.seedDefaultPlan()
  }

  private seedDefaultPlan() {
    const defaultPlan: ResponsePlan = {
      planId: 'PLAN-KG-2026-V1',
      version: 1,
      generatedAt: new Date().toISOString(),
      triggerSource: 'QUANTUM_OPTIMIZATION',
      overallRisk: 'HIGH',
      totalEvacuees: 357000,
      allocatedRescueBoats: 45,
      allocatedMedicalTeams: 28,
      allocatedShelters: 8,
      status: 'ACTIVE',
      zones: [
        {
          zoneId: 'ZONE-K-01',
          zoneName: 'Krishna Delta Lowlands (Vijayawada East)',
          basin: 'Krishna',
          riskLevel: 'HIGH',
          estimatedPopulation: 142000,
          evacuationPriority: 1,
          designatedShelter: 'Krishna Relief Shelter (Capacity: 1,000)',
          safeRouteStatus: 'OPEN',
          assignedRescueBoats: 20,
          assignedMedicalTeams: 12,
        },
        {
          zoneId: 'ZONE-G-02',
          zoneName: 'Godavari Estuary East (Rajahmundry Lowlands)',
          basin: 'Godavari',
          riskLevel: 'CRITICAL',
          estimatedPopulation: 215000,
          evacuationPriority: 1,
          designatedShelter: 'Godavari Relief Shelter (Capacity: 1,200)',
          safeRouteStatus: 'CONGESTED',
          assignedRescueBoats: 25,
          assignedMedicalTeams: 16,
        },
        {
          zoneId: 'ZONE-K-03',
          zoneName: 'Srisailam Downstream Catchment',
          basin: 'Krishna',
          riskLevel: 'MEDIUM',
          estimatedPopulation: 64000,
          evacuationPriority: 3,
          designatedShelter: 'Srisailam Relief Center (Capacity: 500)',
          safeRouteStatus: 'OPEN',
          assignedRescueBoats: 8,
          assignedMedicalTeams: 4,
        },
      ],
    }
    this.plans.set(defaultPlan.planId, defaultPlan)
  }

  getPlans(): ResponsePlan[] {
    return Array.from(this.plans.values())
  }

  getActivePlan(): ResponsePlan | null {
    const list = this.getPlans()
    return list.find((p) => p.status === 'ACTIVE') || list[0] || null
  }

  getPlan(id: string): ResponsePlan | null {
    return this.plans.get(id) ?? null
  }

  createPlan(params: {
    quantumOptimizationId?: string
    riskLevel?: ResponsePlan['overallRisk']
    evacueeCount?: number
  }): ResponsePlan {
    const existing = this.getActivePlan()
    const nextVersion = existing ? existing.version + 1 : 1
    if (existing) {
      existing.status = 'SUPERSEDED'
    }

    const plan: ResponsePlan = {
      planId: `PLAN-KG-2026-V${nextVersion}`,
      version: nextVersion,
      generatedAt: new Date().toISOString(),
      triggerSource: params.quantumOptimizationId ? 'QUANTUM_OPTIMIZATION' : 'AI_FORECAST',
      overallRisk: params.riskLevel || 'HIGH',
      totalEvacuees: params.evacueeCount || 385000,
      allocatedRescueBoats: 52,
      allocatedMedicalTeams: 34,
      allocatedShelters: 12,
      status: 'ACTIVE',
      zones: [
        {
          zoneId: 'ZONE-K-01',
          zoneName: 'Krishna Delta Lowlands',
          basin: 'Krishna',
          riskLevel: 'HIGH',
          estimatedPopulation: 145000,
          evacuationPriority: 1,
          designatedShelter: 'Krishna Relief Shelter',
          safeRouteStatus: 'OPEN',
          assignedRescueBoats: 24,
          assignedMedicalTeams: 15,
        },
        {
          zoneId: 'ZONE-G-02',
          zoneName: 'Godavari Estuary East',
          basin: 'Godavari',
          riskLevel: 'CRITICAL',
          estimatedPopulation: 240000,
          evacuationPriority: 1,
          designatedShelter: 'Godavari Relief Shelter',
          safeRouteStatus: 'OPEN',
          assignedRescueBoats: 28,
          assignedMedicalTeams: 19,
        },
      ],
    }

    this.plans.set(plan.planId, plan)
    return plan
  }
}
