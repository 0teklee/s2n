/**
 * S2N Scanner - Native Messaging protocol (versioned, validated)
 *
 * native_host.py emits one envelope shape: { status, action, data?, error?, protocolVersion? }.
 * This module turns that untyped envelope into a validated, action-discriminated
 * `DecodedNativeEvent` so callers never need `as unknown as X` casts.
 */

import { isSeverity, normalizeReferences } from '@/domain/scan'
import type { Finding, ProgressInfo, ScanSummary } from '@/domain/scan'

/** 현재 지원하는 프로토콜 버전. native_host.py가 다른 값을 보내면 protocol_error로 처리한다. */
export const NATIVE_PROTOCOL_VERSION = 1

export type DecodedNativeEvent =
    | { type: 'scan_started' }
    | { type: 'scan_progress'; progress: ProgressInfo }
    | { type: 'scan_finding'; finding: Finding }
    | { type: 'scan_completed'; targetUrl: string; summary: ScanSummary }
    | { type: 'scan_failed'; error: string }
    | { type: 'scan_stopped' }
    | { type: 'scan_error'; error: string }
    | { type: 'pong' }
    | { type: 'version'; data: Record<string, unknown> }
    | { type: 'protocol_error'; error: string }

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null
}

function decodeFinding(data: Record<string, unknown>): Finding | null {
    if (typeof data.id !== 'string' || data.id.length === 0) return null
    if (typeof data.title !== 'string') return null
    return {
        id: data.id,
        plugin: typeof data.plugin === 'string' ? data.plugin : 'unknown',
        severity: isSeverity(data.severity) ? data.severity : 'INFO',
        title: data.title,
        description: typeof data.description === 'string' ? data.description : '',
        url: typeof data.url === 'string' ? data.url : undefined,
        parameter: typeof data.parameter === 'string' ? data.parameter : undefined,
        method: typeof data.method === 'string' ? data.method : undefined,
        evidence: typeof data.evidence === 'string' ? data.evidence : undefined,
        cweId: typeof data.cweId === 'string' ? data.cweId : undefined,
        cvssScore: typeof data.cvssScore === 'number' ? data.cvssScore : undefined,
        references: normalizeReferences(data.references ?? data.reference),
        timestamp: typeof data.timestamp === 'string' ? data.timestamp : new Date().toISOString(),
    }
}

function decodeSummary(raw: unknown): ScanSummary | null {
    if (!isRecord(raw)) return null
    if (typeof raw.totalFindings !== 'number') return null
    return {
        totalFindings: raw.totalFindings,
        severityCounts: isRecord(raw.severityCounts) ? (raw.severityCounts as ScanSummary['severityCounts']) : ({} as ScanSummary['severityCounts']),
        pluginCounts: isRecord(raw.pluginCounts) ? (raw.pluginCounts as Record<string, number>) : {},
        totalUrlsScanned: typeof raw.totalUrlsScanned === 'number' ? raw.totalUrlsScanned : 0,
        durationSeconds: typeof raw.durationSeconds === 'number' ? raw.durationSeconds : 0,
    }
}

/**
 * Native host에서 온 원시 메시지를 검증된 discriminated union으로 변환한다.
 * 알 수 없는 프로토콜 버전이나 구조가 깨진 이벤트는 `protocol_error`로 취급되어야 하며,
 * 호출자는 마지막 유효 상태를 보존하고 세션을 닫아야 한다.
 */
export function decodeNativeEnvelope(raw: unknown): DecodedNativeEvent {
    if (!isRecord(raw)) return { type: 'protocol_error', error: 'Malformed native message (not an object)' }

    if ('protocolVersion' in raw && raw.protocolVersion !== undefined && raw.protocolVersion !== NATIVE_PROTOCOL_VERSION) {
        return { type: 'protocol_error', error: `Unsupported native protocol version: ${String(raw.protocolVersion)}` }
    }

    if (raw.status === 'error') {
        return { type: 'scan_error', error: typeof raw.error === 'string' ? raw.error : 'Unknown error from native host' }
    }
    if (raw.status !== 'ok') {
        return { type: 'protocol_error', error: `Unknown protocol status: ${String(raw.status)}` }
    }

    const action = raw.action
    const data = isRecord(raw.data) ? raw.data : {}

    switch (action) {
        case 'scan_started':
            return { type: 'scan_started' }

        case 'scan_progress': {
            if (typeof data.current !== 'number' || typeof data.total !== 'number') {
                return { type: 'protocol_error', error: 'Malformed scan_progress event' }
            }
            return {
                type: 'scan_progress',
                progress: {
                    current: data.current,
                    total: data.total,
                    percent: typeof data.percent === 'number' ? data.percent : 0,
                    message: typeof data.message === 'string' ? data.message : '',
                },
            }
        }

        case 'scan_finding': {
            const finding = decodeFinding(data)
            if (!finding) return { type: 'protocol_error', error: 'Malformed scan_finding event' }
            return { type: 'scan_finding', finding }
        }

        case 'scan_completed': {
            const summary = decodeSummary(data.summary)
            if (!summary) return { type: 'protocol_error', error: 'Malformed scan_completed event' }
            return { type: 'scan_completed', targetUrl: typeof data.targetUrl === 'string' ? data.targetUrl : '', summary }
        }

        case 'scan_failed':
            return { type: 'scan_failed', error: typeof data.error === 'string' ? data.error : 'Scan failed' }

        case 'scan_stopped':
            return { type: 'scan_stopped' }

        case 'pong':
            return { type: 'pong' }

        case 'version':
            return { type: 'version', data }

        default:
            return { type: 'protocol_error', error: `Unknown action from native host: ${String(action)}` }
    }
}
