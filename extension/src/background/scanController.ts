/**
 * S2N Scanner - Scan session controller
 *
 * Owns the single active scan session: state, native port identity, and
 * dedup/broadcast/persistence side effects. `background.ts` is a thin
 * chrome.runtime.onMessage router that delegates here.
 */

import { connectNative, disconnectNative, isNotInstalledError } from '@/lib/nativeMessaging'
import { saveScanHistory } from '@/lib/storage'
import { AVAILABLE_PLUGINS, createInitialScanState } from '@/domain/scan'
import type { ScanHistoryItem, ScanState } from '@/domain/scan'
import { scanReducer } from '@/domain/scanReducer'
import { decodeNativeEnvelope } from '@/protocol/native'

type Listener = (state: ScanState) => void

const KNOWN_PLUGIN_IDS = new Set(AVAILABLE_PLUGINS.map((p) => p.id))

export interface CommandResult {
    success: boolean
    error?: string
}

class ScanController {
    private state: ScanState = createInitialScanState()
    private port: chrome.runtime.Port | null = null
    /** 세션 식별자 — 이전 세션의 지연 도착 이벤트/disconnect를 무시하기 위함 */
    private sessionId = 0
    private listeners = new Set<Listener>()

    getState(): ScanState {
        return this.state
    }

    subscribe(fn: Listener): () => void {
        this.listeners.add(fn)
        return () => this.listeners.delete(fn)
    }

    private emit() {
        for (const fn of this.listeners) fn(this.state)
    }

    private setState(next: ScanState) {
        this.state = next
        this.emit()
    }

    private validateStartRequest(targetUrl: string, plugins: string[]): string | null {
        if (typeof targetUrl !== 'string' || !/^https?:\/\//i.test(targetUrl)) {
            return 'Invalid target URL — must start with http:// or https://'
        }
        if (!Array.isArray(plugins) || plugins.length === 0) {
            return 'No plugins selected'
        }
        const unknown = plugins.filter((p) => !KNOWN_PLUGIN_IDS.has(p))
        if (unknown.length > 0) {
            return `Unknown plugins: ${unknown.join(', ')}`
        }
        return null
    }

    /** not_installed 감지는 idle 상태에서만 의미가 있다 (스캔 중 상태를 덮어쓰지 않음). */
    markNotInstalledIfIdle(error: string) {
        if (this.state.status === 'idle') {
            this.setState(scanReducer(this.state, { type: 'not_installed', error }))
        }
    }

    startScan(targetUrl: string, plugins: string[], acceptRisk: boolean): CommandResult {
        if (this.state.status === 'scanning') {
            return { success: false, error: 'Scan already in progress' }
        }

        const validationError = this.validateStartRequest(targetUrl, plugins)
        if (validationError) {
            return { success: false, error: validationError }
        }

        this.sessionId += 1
        const session = this.sessionId

        this.setState(scanReducer(this.state, { type: 'validate', targetUrl, plugins }))

        if (this.port) disconnectNative(this.port)
        const port = connectNative({
            onMessage: (raw) => this.handleNativeMessage(session, raw),
            onDisconnect: (error) => this.handleNativeDisconnect(session, error),
        })
        this.port = port

        port.postMessage({
            action: 'start_scan',
            data: { target_url: targetUrl, plugins, accept_risk: Boolean(acceptRisk) },
        })

        return { success: true }
    }

    stopScan(): CommandResult {
        // 세션 무효화 — 이미 전송된 stop_scan 응답 이후 도착하는 이벤트는 전부 무시된다.
        this.sessionId += 1
        if (this.port) {
            try {
                this.port.postMessage({ action: 'stop_scan' })
            } catch {
                // 포트가 이미 끊어진 경우 — 무시
            }
            disconnectNative(this.port)
            this.port = null
        }
        this.setState(scanReducer(this.state, { type: 'reset' }))
        return { success: true }
    }

    private handleNativeMessage(session: number, raw: unknown) {
        if (session !== this.sessionId) return // stale session — 무시

        const event = decodeNativeEnvelope(raw)

        if (event.type === 'protocol_error') {
            console.error('[ScanController] protocol error:', event.error)
            this.setState(scanReducer(this.state, { type: 'scan_failed', error: event.error }))
            this.closeSession(session)
            return
        }

        if (event.type === 'pong' || event.type === 'version') return

        if (event.type === 'scan_completed') {
            this.setState(scanReducer(this.state, { type: 'scan_completed', summary: event.summary }))
            const historyItem: ScanHistoryItem = {
                scanId: `scan_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
                targetUrl: event.targetUrl || this.state.targetUrl,
                timestamp: new Date().toISOString(),
                status: this.state.status,
                summary: event.summary,
                findings: this.state.findings,
            }
            saveScanHistory(historyItem).catch((err) => {
                console.error('[ScanController] Failed to save scan history:', err)
            })
            this.closeSession(session)
            return
        }

        this.setState(scanReducer(this.state, event))

        if (event.type === 'scan_failed' || event.type === 'scan_stopped' || event.type === 'scan_error') {
            this.closeSession(session)
        }
    }

    private handleNativeDisconnect(session: number, error?: string) {
        if (session !== this.sessionId) return // stale session — 무시

        console.warn('[ScanController] Native port disconnected:', error)
        if (this.state.status === 'scanning' || this.state.status === 'validating') {
            const nextStatus = isNotInstalledError(error) ? 'not_installed' : 'failed'
            this.setState({
                ...this.state,
                status: nextStatus,
                error: error || 'Lost connection to native host during scan.',
            })
        }
        this.port = null
    }

    private closeSession(session: number) {
        if (session !== this.sessionId) return
        if (this.port) {
            disconnectNative(this.port)
            this.port = null
        }
    }
}

export const scanController = new ScanController()
