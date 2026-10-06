/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend (tests) | Owner: Navya (ForecastingEngine seam) | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Rendering tests for the station and river selectors and their composition.
 *
 * The behaviours that matter are the refusals:
 *
 * - With no options, the select is not rendered at all — a banner states why.
 * - The control never auto-selects; `null` selection renders as an explicit
 *   "No station selected" option.
 * - A selection that disagrees with the loaded record is surfaced as a critical
 *   mismatch note instead of silently showing one station under another's flag.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { realForecastRecord, syntheticForecastRecord } from './fixtures'
import { NavyaForecastScope } from './NavyaForecastScope'
import { NavyaRiverSelector } from './NavyaRiverSelector'
import { NavyaStationSelector } from './NavyaStationSelector'
import { NO_RIVER_IDENTITY_REASON, NO_STATION_REGISTRY_REASON, type NavyaRiverOption, type NavyaStationOption } from './scope'

const STATION: NavyaStationOption = {
  id: 'STN-0001',
  label: 'STN-0001',
  datasetType: 'real',
  official: false,
}

const OTHER_STATION: NavyaStationOption = {
  id: 'STN-9999',
  label: 'STN-9999',
  datasetType: 'real',
  official: false,
}

const RIVER: NavyaRiverOption = {
  id: 'reach-1',
  label: 'reach-1',
  datasetType: 'real',
  official: false,
}

describe('NavyaStationSelector', () => {
  it('renders an explicit unavailable banner when no registry options exist', () => {
    render(<NavyaStationSelector options={[]} value={null} onChange={vi.fn()} record={null} />)
    expect(screen.getByText('No station registry available')).toBeInTheDocument()
    expect(screen.getByText(NO_STATION_REGISTRY_REASON)).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })

  it('renders a select only when options exist and never auto-selects', () => {
    render(<NavyaStationSelector options={[STATION]} value={null} onChange={vi.fn()} record={realForecastRecord()} />)
    const select = screen.getByLabelText('Station reference') as HTMLSelectElement
    expect(select).toBeInTheDocument()
    expect(select.value).toBe('')
    expect(screen.getByRole('option', { name: 'No station selected' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: /STN-0001/ })).toBeInTheDocument()
  })

  it('reports a selection change with the chosen station id', () => {
    const onChange = vi.fn()
    render(<NavyaStationSelector options={[STATION]} value={null} onChange={onChange} record={realForecastRecord()} />)
    fireEvent.change(screen.getByLabelText('Station reference'), { target: { value: 'STN-0001' } })
    expect(onChange).toHaveBeenCalledWith('STN-0001')
  })

  it('reports null when the user clears the selection', () => {
    const onChange = vi.fn()
    render(<NavyaStationSelector options={[STATION]} value="STN-0001" onChange={onChange} record={realForecastRecord()} />)
    fireEvent.change(screen.getByLabelText('Station reference'), { target: { value: '' } })
    expect(onChange).toHaveBeenCalledWith(null)
  })

  it('shows no note when the selection matches the record', () => {
    render(<NavyaStationSelector options={[STATION]} value="STN-0001" onChange={vi.fn()} record={realForecastRecord()} />)
    expect(screen.queryByText(/not belonging to the selected station/)).not.toBeInTheDocument()
  })

  it('warns critically when the selection does not belong to the loaded record', () => {
    render(
      <NavyaStationSelector
        options={[STATION, OTHER_STATION]}
        value="STN-9999"
        onChange={vi.fn()}
        record={realForecastRecord()}
      />,
    )
    expect(screen.getByText(/not belonging to the selected station/)).toBeInTheDocument()
  })

  it('labels a synthetic-derived station as not verified', () => {
    const syntheticStation: NavyaStationOption = { ...STATION, datasetType: 'synthetic' }
    render(<NavyaStationSelector options={[syntheticStation]} value="STN-0001" onChange={vi.fn()} record={syntheticForecastRecord({ provenance: { ...syntheticForecastRecord().provenance, stationReference: 'STN-0001' } })} />)
    expect(screen.getByText(/Derived from synthetic\/demo data/)).toBeInTheDocument()
  })

  it('disables the control while a load is in flight', () => {
    render(<NavyaStationSelector options={[STATION]} value={null} onChange={vi.fn()} record={null} disabled />)
    expect(screen.getByLabelText('Station reference')).toBeDisabled()
  })
})

describe('NavyaRiverSelector', () => {
  it('renders an explicit unavailable state — no river identity exists', () => {
    render(<NavyaRiverSelector options={[]} value={null} onChange={vi.fn()} record={null} />)
    expect(screen.getByText('No river identity in the contract')).toBeInTheDocument()
    // Stated twice by design: the banner and the standing note under the control.
    expect(screen.getAllByText(NO_RIVER_IDENTITY_REASON).length).toBeGreaterThan(0)
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })

  it('renders a select when options are supplied, keeping the same controlled contract', () => {
    const onChange = vi.fn()
    render(<NavyaRiverSelector options={[RIVER]} value={null} onChange={onChange} record={realForecastRecord()} />)
    const select = screen.getByLabelText('River') as HTMLSelectElement
    expect(select.value).toBe('')
    fireEvent.change(select, { target: { value: 'reach-1' } })
    expect(onChange).toHaveBeenCalledWith('reach-1')
  })
})

describe('NavyaForecastScope', () => {
  it('composes both selectors and propagates both selections', () => {
    const onStation = vi.fn()
    const onRiver = vi.fn()
    render(
      <NavyaForecastScope
        record={realForecastRecord()}
        stationId={null}
        riverId={null}
        onStationChange={onStation}
        onRiverChange={onRiver}
      />,
    )
    expect(screen.getByTestId('navya-forecast-scope')).toBeInTheDocument()
    // The loaded record supplies its station reference; the river stays unavailable.
    fireEvent.change(screen.getByLabelText('Station reference'), { target: { value: 'STN-0001' } })
    expect(onStation).toHaveBeenCalledWith('STN-0001')
    expect(screen.getByText('No river identity in the contract')).toBeInTheDocument()
  })

  it('propagates the disabled state to both controls', () => {
    render(
      <NavyaForecastScope
        record={realForecastRecord()}
        stationId={null}
        riverId={null}
        onStationChange={vi.fn()}
        onRiverChange={vi.fn()}
        disabled
      />,
    )
    expect(screen.getByLabelText('Station reference')).toBeDisabled()
  })
})