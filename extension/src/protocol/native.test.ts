import { describe, expect, it } from 'vitest'

import { decodeNativeEnvelope, NATIVE_PROTOCOL_VERSION } from './native'

describe('decodeNativeEnvelope', () => {
    it('turns a top-level native error into scan_error with the real message preserved', () => {
        const event = decodeNativeEnvelope({ status: 'error', action: 'scan_failed', error: 'boom' })
        expect(event).toEqual({ type: 'scan_error', error: 'boom' })
    })

    it('rejects an unsupported protocol version as a protocol_error', () => {
        const event = decodeNativeEnvelope({ status: 'ok', action: 'pong', protocolVersion: NATIVE_PROTOCOL_VERSION + 1 })
        expect(event.type).toBe('protocol_error')
    })

    it('rejects a malformed scan_completed summary instead of creating a corrupt state', () => {
        const event = decodeNativeEnvelope({ status: 'ok', action: 'scan_completed', data: { targetUrl: 'https://a.test', summary: { totalFindings: 'oops' } } })
        expect(event.type).toBe('protocol_error')
    })

    it('decodes a scan_finding event and normalizes legacy singular reference into references[]', () => {
        const event = decodeNativeEnvelope({
            status: 'ok',
            action: 'scan_finding',
            data: { id: 'f-1', title: 'XSS', severity: 'HIGH', reference: 'https://owasp.org' },
        })
        expect(event.type).toBe('scan_finding')
        if (event.type === 'scan_finding') {
            expect(event.finding.references).toEqual(['https://owasp.org'])
        }
    })

    it('falls back to INFO for an unknown/malformed severity rather than crashing', () => {
        const event = decodeNativeEnvelope({ status: 'ok', action: 'scan_finding', data: { id: 'f-1', title: 'X', severity: 'NOT_A_SEVERITY' } })
        expect(event.type).toBe('scan_finding')
        if (event.type === 'scan_finding') {
            expect(event.finding.severity).toBe('INFO')
        }
    })

    it('rejects an unknown action', () => {
        const event = decodeNativeEnvelope({ status: 'ok', action: 'mystery_action' })
        expect(event.type).toBe('protocol_error')
    })
})
