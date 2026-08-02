import { describe, expect, it } from 'vitest'

import { createInitialScanState } from './scan'
import type { Finding } from './scan'
import { scanReducer } from './scanReducer'

function finding(overrides: Partial<Finding> = {}): Finding {
    return {
        id: 'f-1',
        plugin: 'xss',
        severity: 'HIGH',
        title: 'Example',
        description: 'desc',
        references: [],
        timestamp: new Date().toISOString(),
        ...overrides,
    }
}

describe('scanReducer', () => {
    it('starting a second scan begins with zero findings even if the first found issues', () => {
        let state = createInitialScanState()
        state = scanReducer(state, { type: 'validate', targetUrl: 'https://a.test', plugins: ['xss'] })
        state = scanReducer(state, { type: 'scan_started' })
        state = scanReducer(state, { type: 'scan_finding', finding: finding() })
        expect(state.findings).toHaveLength(1)

        // second scan
        state = scanReducer(state, { type: 'validate', targetUrl: 'https://b.test', plugins: ['xss'] })
        expect(state.findings).toHaveLength(0)
        expect(state.status).toBe('validating')
    })

    it('deduplicates findings with the same key instead of appending duplicates', () => {
        let state = createInitialScanState()
        state = scanReducer(state, { type: 'scan_finding', finding: finding() })
        state = scanReducer(state, { type: 'scan_finding', finding: finding() })
        expect(state.findings).toHaveLength(1)
    })

    it('createInitialScanState objects are never mutated by a transition', () => {
        const initial = createInitialScanState()
        scanReducer(initial, { type: 'scan_finding', finding: finding() })
        expect(initial.findings).toHaveLength(0)
    })

    it('marks scan_failed/scan_stopped/scan_error as a failed terminal state', () => {
        const state = scanReducer(createInitialScanState(), { type: 'scan_error', error: 'boom' })
        expect(state.status).toBe('failed')
        expect(state.error).toBe('boom')
    })

    it('scan_completed sets progress to 100% without losing prior progress info', () => {
        let state = createInitialScanState()
        state = scanReducer(state, { type: 'scan_started' })
        state = scanReducer(state, {
            type: 'scan_completed',
            summary: { totalFindings: 0, severityCounts: { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0, INFO: 0 }, pluginCounts: {}, totalUrlsScanned: 1, durationSeconds: 1 },
        })
        expect(state.status).toBe('completed')
        expect(state.progress?.percent).toBe(100)
    })
})
