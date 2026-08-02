import { useState, useEffect } from 'react'
import { createInitialScanState } from '@/types/scan'
import type { ScanState } from '@/types/scan'
import { isNotInstalledError } from '@/lib/nativeMessaging'

/** background.ts의 sendResponse()가 반환하는 공통 응답 형태 */
interface ExtensionResponse {
    success: boolean
    data?: unknown
    error?: string
}

export function useScan() {
    const [state, setState] = useState<ScanState>(createInitialScanState)

    useEffect(() => {
        // 현재 background 상태 동기화
        chrome.runtime.sendMessage({ type: 'get_scan_state' }, (response: ScanState) => {
            if (chrome.runtime.lastError) return // background 아직 준비 중 — 무시
            if (response) setState(response)
        })

        // 팝업 열릴 때 native host 연결 여부를 사전 확인
        // → 연결 불가 시 즉시 not_installed 화면 표시 (Start Scan 클릭 전에 안내)
        chrome.runtime.sendMessage({ type: 'ping' }, (response: ExtensionResponse) => {
            if (chrome.runtime.lastError) return // background 아직 준비 중 — 무시
            if (!response?.success && isNotInstalledError(response?.error)) {
                setState(prev =>
                    prev.status === 'idle'
                        ? { ...prev, status: 'not_installed', error: response.error ?? null }
                        : prev,
                )
            }
        })

        const handleMessage = (message: { type: string; state: ScanState }) => {
            if (message.type === 'state_update') {
                setState(message.state)
            }
        }

        chrome.runtime.onMessage.addListener(handleMessage)
        return () => chrome.runtime.onMessage.removeListener(handleMessage)
    }, [])

    const startScan = (targetUrl: string, plugins: string[], acceptRisk = false) => {
        setState({
            ...createInitialScanState(),
            status: 'validating',
            targetUrl,
            selectedPlugins: plugins,
        })
        chrome.runtime.sendMessage({ type: 'start_scan', payload: { targetUrl, plugins, acceptRisk } }, response => {
            if (chrome.runtime.lastError) {
                setState(prev => ({ ...prev, status: 'failed', error: chrome.runtime.lastError?.message ?? 'Unable to start scan' }))
            } else if (!response?.success) {
                setState(prev => ({ ...prev, status: 'failed', error: response?.error ?? 'Unable to start scan' }))
            }
        })
    }

    const stopScan = () => {
        setState(createInitialScanState())
        chrome.runtime.sendMessage({ type: 'stop_scan' })
    }

    /** s2n 설치 후 연결을 재확인합니다. 성공 시 idle로 복귀. */
    const checkInstallation = () => {
        chrome.runtime.sendMessage({ type: 'ping' }, (response: ExtensionResponse) => {
            if (response?.success) {
                setState(createInitialScanState())
            } else if (isNotInstalledError(response?.error)) {
                setState(prev => ({ ...prev, status: 'not_installed', error: response.error ?? null }))
            } else {
                setState(prev => ({ ...prev, status: 'failed', error: response?.error ?? 'Connection failed' }))
            }
        })
    }

    return { state, startScan, stopScan, checkInstallation }
}
