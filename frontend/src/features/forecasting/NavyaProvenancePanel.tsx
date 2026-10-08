/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: forecasting module | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { CircleHelp, FlaskConical, ShieldQuestion } from 'lucide-react'
import type { ReactNode } from 'react'
import { GlassCard } from '../../components/ui/GlassCard'
import { SectionHeader } from '../../components/ui/SectionHeader'
import { StateBanner } from '../../components/ui/StateBanner'
import {
  describeDatasetType,
  describeThreshold,
  integrationStatement,
  mandatoryForecastLabel,
  mandatoryMetricLabel,
  metricPresentation,
  openQuestions,
  summariseProvenance,
} from './contract'
import type { ForecastRecord } from './types'

type Tone = 'info' | 'warning' | 'critical'

const TONE_CLASSES: Record<Tone, string> = {
  info: 'border-forest-600 bg-forest-800/60 text-mist-300',
  warning: 'border-amber-500/40 bg-amber-500/10 text-amber-300',
  critical: 'border-critical-500/40 bg-critical-500/10 text-critical-300',
}

/**
 * A short explanatory note.
 *
 * Reused across the module so the note styling exists once. `role="note"` gives
 * assistive tech a landmark for it without stealing focus.
 */
export function HumanInputNote({
  children,
  tone = 'info',
}: {
  children: ReactNode
  tone?: Tone
}) {
  return (
    <p role="note" className={`rounded-lg border px-3 py-2 text-xs ${TONE_CLASSES[tone]}`}>
      {children}
    </p>
  )
}

function num(value: number | null, digits = 4): string {
  return value === null ? '—' : value.toFixed(digits)
}

interface Props {
  forecast: ForecastRecord
}

/**
 * Provenance and evaluation status.
 *
 * This panel is the reason the module exists. Everything else on the dashboard
 * shows a number; this panel is what the number is *allowed* to mean. It answers
 * four questions that a forecast screen otherwise leaves implicit:
 *
 * 1. **Where did this come from?** Dataset reference, type, licence, checksum,
 *    sampling interval, station, target, units, model and contract version.
 *    Unknown fields are shown as unknown.
 * 2. **What split were these scores measured on?** A train score, a validation
 *    score and a held-out test score are different claims, and the difference is
 *    the whole difference between "it fits" and "it generalises".
 * 3. **Is the threshold an official flood stage?** Only if the record says the
 *    policy is approved. The running contract cannot say that, so it is always
 *    pending, and the pending state is shown.
 * 4. **What does the optimizer get from this?** The verbatim integration
 *    statement, rendered rather than footnoted.
 *
 * No metric is displayed without its split and its label. If a label is required
 * and no data is present, the panel says the metric is absent instead of printing
 * a number next to a caveat.
 */
export function ProvenancePanel({ forecast }: Props) {
  const label = mandatoryForecastLabel(forecast)
  const metricLabel = mandatoryMetricLabel(forecast)
  const { presentable, reasons } = metricPresentation(forecast)
  const questions = openQuestions(forecast.provenance)
  const isSynthetic = forecast.provenance.datasetType === 'synthetic'

  return (
    <GlassCard className="space-y-4">
      <SectionHeader
        icon={isSynthetic ? FlaskConical : ShieldQuestion}
        title="Provenance &amp; evaluation status"
        description="What these numbers are, and what they may be used for."
      />

      {label !== null && (
        <StateBanner
          kind={isSynthetic ? 'demo' : 'unavailable'}
          title={isSynthetic ? 'Synthetic / demo data' : 'Provenance not recorded'}
          message={label}
        />
      )}

      <section aria-label="Data provenance">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-500">
          Data provenance
        </h3>
        <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
          <Row label="Dataset" value={forecast.provenance.datasetReference} fallback="not recorded" />
          <Row label="Type" value={describeDatasetType(forecast.provenance.datasetType)} />
          <Row label="Licence" value={forecast.provenance.datasetLicense} fallback="not recorded" />
          <Row
            label="Checksum"
            value={shorten(forecast.provenance.datasetChecksum)}
            fallback="not recorded"
          />
          <Row label="Sampling" value={forecast.provenance.samplingInterval} fallback="not recorded" />
          <Row label="Station" value={forecast.provenance.stationReference} fallback="not recorded" />
          <Row label="Target units" value={forecast.provenance.targetUnits} fallback="not recorded" />
          <Row label="Residual sigma" value={num(forecast.residualSigma)} fallback="unmeasurable" />
          <Row label="Features" value={String(forecast.provenance.featureList.length)} />
        </dl>
        <p className="mt-2 text-[11px] text-mist-600">
          <code className="break-all">{summariseProvenance(forecast)}</code>
        </p>
      </section>

      <section aria-label="Evaluation status" className="border-t border-forest-600/60 pt-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-500">
          Evaluation status
        </h3>

        {forecast.metrics === null ? (
          <HumanInputNote tone="warning">
            Metrics were not measured for this forecast, so no values are shown. Nothing is
            displayed in their place.
          </HumanInputNote>
        ) : (
          <>
            <dl className="mt-2 grid grid-cols-3 gap-x-6 gap-y-2 text-xs sm:grid-cols-6">
              <Row label="MAE" value={num(forecast.metrics.mae)} />
              <Row label="RMSE" value={num(forecast.metrics.rmse)} />
              <Row label="R²" value={num(forecast.metrics.r2)} />
              <Row label="NSE" value={num(forecast.metrics.nse)} />
              <Row label="Peak |err|" value={num(forecast.metrics.peakAbsoluteError)} />
              <Row label="Bias" value={num(forecast.metrics.bias)} />
            </dl>
            <p className="mt-1 text-[11px] text-mist-600">
              Measured on {forecast.metrics.nSamples} samples
              {forecast.metricProvenance === null
                ? ' — split not recorded.'
                : ` — split: ${forecast.metricProvenance.split}.`}
            </p>
          </>
        )}

        {/*
          The note carries the HEADLINE only. The detailed reasons are rendered
          once, in the list below. Rendering `metricLabel` here used to repeat
          every reason verbatim in both places — the same sentence twice on one
          screen reads as a rendering bug, which is exactly the wrong impression
          for a panel whose job is to be trusted.
        */}
        {isSynthetic && metricLabel !== null ? (
          <HumanInputNote tone="warning">{metricLabel}</HumanInputNote>
        ) : presentable ? (
          <HumanInputNote>
            Measured on the held-out test split, which was scored exactly once and did not influence
            model selection.
          </HumanInputNote>
        ) : metricLabel !== null ? (
          <HumanInputNote tone="critical">NOT A HELD-OUT RESULT</HumanInputNote>
        ) : null}

        {!presentable && reasons.length > 0 && (
          <ul className="mt-2 list-disc space-y-1 pl-5 text-[11px] text-mist-400">
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Threshold policy" className="border-t border-forest-600/60 pt-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-500">
          Threshold policy
        </h3>
        <HumanInputNote tone={forecast.thresholdPolicy === 'approved' ? 'info' : 'warning'}>
          {describeThreshold(forecast)}
        </HumanInputNote>
        {forecast.thresholdPolicy !== 'approved' && (
          <p className="mt-1 text-[11px] text-mist-600">
            No official flood-stage thresholds exist in this repository. The risk bands LOW / MEDIUM /
            HIGH / CRITICAL therefore have no approved policy behind them.
          </p>
        )}
      </section>

      {questions.length > 0 && (
        <section aria-label="Unresolved inputs" className="border-t border-forest-600/60 pt-3">
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-500">
            Unresolved inputs
          </h3>
          <ul className="mt-2 space-y-1 text-[11px] text-mist-400">
            {questions.map((question) => (
              <li key={question} className="flex items-start gap-1.5">
                <CircleHelp size={12} className="mt-0.5 shrink-0" aria-hidden="true" />
                {question}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-label="Optimization handoff" className="border-t border-forest-600/60 pt-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-mist-500">
          Optimization handoff
        </h3>
        <HumanInputNote>{integrationStatement()}</HumanInputNote>
        <p className="mt-1 text-[11px] text-mist-600">
          The contract is pinned in <code>types.ts</code> as <code>INTEGRATION_STATEMENT</code>.
        </p>
      </section>
    </GlassCard>
  )
}

/** A label/value pair. `null` renders the fallback rather than "null". */
function Row({
  label,
  value,
  fallback = 'not recorded',
}: {
  label: string
  value: string | null
  fallback?: string
}) {
  const text = value === null || value === '' ? fallback : value
  return (
    <div>
      <dt className="text-[10px] font-semibold uppercase tracking-[0.14em] text-mist-600">{label}</dt>
      <dd className={`mt-0.5 break-words font-medium ${text === fallback ? 'text-mist-500' : 'text-mist-200'}`}>
        {text}
      </dd>
    </div>
  )
}

/**
 * Shorten a checksum for display.
 *
 * A 64-character hash in a definition list pushes every other row off the
 * screen. The prefix is enough to identify the file, and the full value stays in
 * the record. Returns `null` for a missing checksum so `Row` applies its own
 * fallback rather than this function inventing a placeholder.
 */
function shorten(checksum: string | null): string | null {
  if (checksum === null) return null
  return checksum.length <= 16 ? checksum : `${checksum.slice(0, 16)}…`
}
