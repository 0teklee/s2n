import { describe, expect, it } from 'vitest'

import { createInitialScanState } from './scan'

describe('createInitialScanState', () => {
    it('returns independent mutable collections for every scan', () => {
        const first = createInitialScanState()
        const second = createInitialScanState()

        first.findings.push({
            id: 'finding-1',
            plugin: 'xss',
            severity: 'HIGH',
            title: 'Example',
            description: 'Example finding',
            references: [],
            timestamp: new Date().toISOString(),
        })
        first.selectedPlugins.push('xss')

        expect(second.findings).toEqual([])
        expect(second.selectedPlugins).toEqual([])
    })
})
