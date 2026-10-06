/**
 * Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
 * Module: frontend | Owner: Nanda | License: Apache-2.0
 *
 * PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction - Nanda & Navya). It is honest by construction, per the platform README: no fabricated data, no invented metrics, every surrogate or fallback is clearly labelled, and no quantum speedup is ever claimed.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
}

/**
 * Renders a contained fallback instead of crashing the whole SPA when a child
 * throws. A "Reload" button restores the view without a full app refresh.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Surface to the console for diagnostics; the UI already shows a fallback.
    // eslint-disable-next-line no-console
    console.error('[ErrorBoundary] Caught an error:', error, info.componentStack)
  }

  private handleReload = (): void => {
    this.setState({ error: null })
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen items-center justify-center px-4 py-16" role="alert">
          <div className="glass-card w-full max-w-md p-6 text-center">
            <p className="text-sm font-semibold uppercase tracking-wider text-critical-400">
              Something went wrong
            </p>
            <h2 className="mt-2 text-xl font-bold text-mist-50">The dashboard crashed</h2>
            <p className="mt-2 text-sm text-mist-300">
              An unexpected error interrupted rendering. Reload to try again.
            </p>
            <p className="mt-2 truncate font-mono text-[11px] text-mist-500">
              {this.state.error.message}
            </p>
            <div className="mt-5 flex justify-center gap-3">
              <button
                type="button"
                onClick={this.handleReload}
                className="rounded-lg border border-emerald-500/50 bg-emerald-500/15 px-4 py-2 text-sm font-semibold text-emerald-300 transition-colors hover:bg-emerald-500/20"
              >
                Reload
              </button>
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="rounded-lg border border-forest-600 bg-forest-800 px-4 py-2 text-sm font-medium text-mist-100 transition-colors hover:border-emerald-500/60"
              >
                Full refresh
              </button>
            </div>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}