/**
 * S2N Scanner - Pure scan state reducer
 *
 * No chrome/React imports. All finding dedup is derived from `state.findings`
 * rather than an external mutable Set, so this function has no hidden state.
 */

import { createInitialScanState, getFindingKey } from './scan'
import type { Finding, ProgressInfo, ScanState, ScanSummary } from './scan'

export type ScanEvent =
    | { type: 'validate'; targetUrl: string; plugins: string[] }
    | { type: 'scan_started' }
    | { type: 'scan_progress'; progress: ProgressInfo }
    | { type: 'scan_finding'; finding: Finding }
    | { type: 'scan_completed'; summary: ScanSummary }
    | { type: 'scan_failed'; error: string }
    | { type: 'scan_stopped'; error?: string }
    | { type: 'scan_error'; error: string }
    | { type: 'not_installed'; error: string }
    | { type: 'reset' }

export function scanReducer(state: ScanState, event: ScanEvent): ScanState {
    switch (event.type) {
        case 'reset':
            return createInitialScanState()

        case 'validate':
            return {
                ...createInitialScanState(),
                status: 'validating',
                targetUrl: event.targetUrl,
                selectedPlugins: event.plugins,
            }

        case 'scan_started':
            return {
                ...state,
                status: 'scanning',
                error: null,
                progress: { current: 0, total: 100, percent: 0, message: 'Initializing scan...' },
            }

        case 'scan_progress':
            return { ...state, progress: event.progress }

        case 'scan_finding': {
            const key = getFindingKey(event.finding)
            if (state.findings.some((f) => getFindingKey(f) === key)) return state
            return { ...state, findings: [...state.findings, event.finding] }
        }

        case 'scan_completed':
            return {
                ...state,
                status: 'completed',
                summary: event.summary,
                progress: state.progress
                    ? { ...state.progress, percent: 100, message: 'Scan completed' }
                    : state.progress,
            }

        case 'scan_failed':
        case 'scan_stopped':
        case 'scan_error':
            return { ...state, status: 'failed', error: event.error ?? 'Scan stopped' }

        case 'not_installed':
            return { ...state, status: 'not_installed', error: event.error }

        default:
            return state
    }
}
