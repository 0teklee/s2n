/**
 * S2N Scanner - Background Service Worker
 */

import { sendNativeMessage, connectNative, disconnectNative, isNotInstalledError } from '@/lib/nativeMessaging'
import { INITIAL_SCAN_STATE } from '@/types/scan'
import type { ScanState, Finding, ProgressInfo, ScanSummary } from '@/types/scan'
import { saveScanHistory } from '@/lib/storage'

let currentScanState: ScanState = { ...INITIAL_SCAN_STATE }
let nativePort: chrome.runtime.Port | null = null

// finding id 추적용 Set — 스캔 시작 시 초기화
let seenFindingIds = new Set<string>()

// SW 재시작 시 기존 findings가 있다면 Set 복구 (상태 유지 대비)
if (currentScanState.findings.length > 0) {
    currentScanState.findings.forEach(f => {
        const key = f.id ?? `${f.title}__${f.url ?? ''}__${f.severity}__${f.parameter ?? ''}`
        seenFindingIds.add(key)
    })
}

function broadcastStateUpdate() {
    chrome.runtime.sendMessage({
        type: 'state_update',
        state: currentScanState,
    }).catch(() => { })
}

function handleNativeMessage(response: any) {
    if (response.status === 'error') {
        console.error('[Background] Native host error:', response.error)
        currentScanState.status = 'failed'
        currentScanState.error = response.error || 'Unknown error from native host'
        broadcastStateUpdate()
        return
    }

    const { action, data } = response

    switch (action) {
        case 'scan_started':
            currentScanState.status = 'scanning'
            currentScanState.error = null
            currentScanState.progress = { current: 0, total: 100, percent: 0, message: 'Initializing scan...' }
            broadcastStateUpdate()
            break

        case 'scan_progress':
            currentScanState.progress = data as ProgressInfo
            broadcastStateUpdate()
            break

        case 'scan_finding':
            const finding = data as Finding
            // ✅ 중복 finding 방지: id 또는 상세 필드 조합 키 사용 (url/parameter null 대처)
            const findingKey = finding.id ?? 
                `${finding.title}__${finding.url ?? ''}__${finding.severity}__${finding.parameter ?? ''}`
            
            if (!seenFindingIds.has(findingKey)) {
                seenFindingIds.add(findingKey)
                currentScanState.findings.push(finding)
                broadcastStateUpdate()
            }
            break

        case 'scan_completed':
            currentScanState.status = 'completed'
            currentScanState.summary = data.summary as ScanSummary
            if (currentScanState.progress) {
                currentScanState.progress.percent = 100
                currentScanState.progress.message = 'Scan completed'
            }
            broadcastStateUpdate()
            disconnectNative(nativePort)
            nativePort = null

            const historyItem = {
                scanId: `scan_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`,
                targetUrl: currentScanState.targetUrl,
                timestamp: new Date().toISOString(),
                status: currentScanState.status,
                summary: currentScanState.summary!,
                findings: currentScanState.findings,
            }
            saveScanHistory(historyItem).catch((err) => {
                console.error('[Background] Failed to save scan history:', err)
            })
            break

        case 'scan_failed':
        case 'scan_stopped':
            currentScanState.status = 'failed'
            currentScanState.error = data?.error || 'Scan stopped'
            broadcastStateUpdate()
            disconnectNative(nativePort)
            nativePort = null
            break

        case 'pong':
        case 'version':
            break

        default:
            console.warn('[Background] Unknown action from native host:', action)
    }
}

function handleNativeDisconnect(error?: string) {
    console.warn('[Background] Native port disconnected. Error:', error)
    if (currentScanState.status === 'scanning' || currentScanState.status === 'validating') {
        currentScanState.status = isNotInstalledError(error) ? 'not_installed' : 'failed'
        currentScanState.error = error || 'Lost connection to native host during scan.'
        broadcastStateUpdate()
    }
    nativePort = null
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {

    if (message.type === 'ping') {
        sendNativeMessage({ action: 'ping' })
            .then((response) => sendResponse({ success: true, data: response }))
            .catch((err) => {
                const msg = err instanceof Error ? err.message : 'Unknown error'
                if (isNotInstalledError(msg) && currentScanState.status === 'idle') {
                    currentScanState.status = 'not_installed'
                    currentScanState.error = msg
                    broadcastStateUpdate()
                }
                sendResponse({ success: false, error: msg })
            })
        return true
    }

    if (message.type === 'get_version') {
        sendNativeMessage({ action: 'get_version' })
            .then((response) => sendResponse({ success: true, data: response }))
            .catch((err) => sendResponse({ success: false, error: err instanceof Error ? err.message : 'Unknown error' }))
        return true
    }

    if (message.type === 'get_scan_state') {
        sendResponse(currentScanState)
        return false
    }

    if (message.type === 'start_scan') {
        if (currentScanState.status === 'scanning') {
            sendResponse({ success: false, error: 'Scan already in progress' })
            return false
        }

        const { targetUrl, plugins } = message.payload

        // ✅ 새 스캔 시작 시 중복 추적 Set 초기화
        seenFindingIds = new Set<string>()

        currentScanState = {
            ...INITIAL_SCAN_STATE,
            status: 'validating',
            targetUrl,
            selectedPlugins: plugins,
        }
        broadcastStateUpdate()

        if (nativePort) disconnectNative(nativePort)
        nativePort = connectNative({
            onMessage: handleNativeMessage,
            onDisconnect: handleNativeDisconnect,
        })

        nativePort.postMessage({
            action: 'start_scan',
            data: { target_url: targetUrl, plugins },
        })

        sendResponse({ success: true })
        return false
    }

    if (message.type === 'stop_scan') {
        if (nativePort) {
            nativePort.postMessage({ action: 'stop_scan' })
        }
        // ✅ 스캔 중단 시에도 Set 초기화
        seenFindingIds = new Set<string>()
        currentScanState.status = 'idle'
        currentScanState.progress = null
        currentScanState.error = null
        broadcastStateUpdate()
        sendResponse({ success: true })
        return false
    }

    return false
})

console.log('[S2N] Background service worker loaded.')