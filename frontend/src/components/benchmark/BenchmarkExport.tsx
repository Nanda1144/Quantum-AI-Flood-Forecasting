/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

/**
 * Export actions for the selected experiment: a JSON experiment report (the
 * signed-style document with configuration, metrics, interpretation and the
 * full result) and a CSV of the metric table. Both are built client-side from
 * the already-loaded gateway data; the report always records
 * `quantumAdvantageClaimed: false` and carries the disclaimer so an exported
 * result is never mistaken for a speedup claim.
 */

import { FileJson2, FileSpreadsheet } from 'lucide-react'
import type { BenchmarkDocument } from '../../types/benchmark'
import { buildBenchmarkCsv, buildBenchmarkReport, downloadFile } from '../../lib/benchmark'

interface BenchmarkExportProps {
  document: BenchmarkDocument
}

export function BenchmarkExport({ document }: BenchmarkExportProps) {
  const exportReport = () => {
    const report = buildBenchmarkReport(document)
    downloadFile(`qflare-benchmark-${document.jobId}.json`, JSON.stringify(report, null, 2), 'application/json')
  }

  const exportCsv = () => {
    downloadFile(`qflare-benchmark-${document.jobId}.csv`, buildBenchmarkCsv(document), 'text/csv')
  }

  return (
    <section className="glass-card p-4" aria-label="Export experiment document">
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-auto text-xs font-semibold text-mist-300">Export this experiment</span>
        <button
          type="button"
          onClick={exportReport}
          className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-xs font-semibold text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300"
        >
          <FileJson2 size={14} aria-hidden="true" />
          Report (JSON)
        </button>
        <button
          type="button"
          onClick={exportCsv}
          className="inline-flex items-center gap-2 rounded-lg border border-forest-600 bg-forest-800/70 px-3 py-2 text-xs font-semibold text-mist-100 transition-colors hover:border-emerald-500/60 hover:text-emerald-300"
        >
          <FileSpreadsheet size={14} aria-hidden="true" />
          Table (CSV)
        </button>
      </div>
      <p className="mt-2 text-[11px] text-mist-600">
        Files are generated client-side from the gateway data already shown. The report records no quantum advantage claim.
      </p>
    </section>
  )
}