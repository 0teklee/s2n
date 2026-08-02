import { useState, useEffect } from 'react'
import { INITIAL_SCAN_STATE } from '@/types/scan'
import type { ScanState } from '@/types/scan'
import { isNotInstalledError } from '@/lib/nativeMessaging'

export function useScan() {
    const [state, setState] = useState<ScanState>(INITIAL_SCAN_STATE)

    useEffect(() => {
        // 현재 background 상태 동기화
        chrome.runtime.sendMessage({ type: 'get_scan_state' }, (response: ScanState) => {
            if (response) setState(response)
        })

        // 팝업 열릴 때 native host 연결 여부를 사전 확인
        // → 연결 불가 시 즉시 not_installed 화면 표시 (Start Scan 클릭 전에 안내)
        chrome.runtime.sendMessage({ type: 'ping' }, (response: any) => {
            if (chrome.runtime.lastError) return // background 아직 준비 중 — 무시
            if (!response?.success && isNotInstalledError(response?.error)) {
                setState(prev =>
                    prev.status === 'idle'
                        ? { ...prev, status: 'not_installed', error: response.error }
                        : prev,
                )
            }
        })

        const handleMessage = (message: any) => {
            if (message.type === 'state_update') {
                setState(message.state)
            }
        }

        chrome.runtime.onMessage.addListener(handleMessage)
        return () => chrome.runtime.onMessage.removeListener(handleMessage)
    }, [])

    const startScan = (targetUrl: string, plugins: string[]) => {
        setState({
            ...INITIAL_SCAN_STATE,
            status: 'validating',
            targetUrl,
            selectedPlugins: plugins,
        })
        chrome.runtime.sendMessage({ type: 'start_scan', payload: { targetUrl, plugins } })
    }

    const stopScan = () => {
        setState(INITIAL_SCAN_STATE)
        chrome.runtime.sendMessage({ type: 'stop_scan' })
    }

    /** s2n 설치 후 연결을 재확인합니다. 성공 시 idle로 복귀. */
    const checkInstallation = () => {
        chrome.runtime.sendMessage({ type: 'ping' }, (response: any) => {
            if (response?.success) {
                setState(INITIAL_SCAN_STATE)
            } else if (isNotInstalledError(response?.error)) {
                setState(prev => ({ ...prev, status: 'not_installed', error: response.error }))
            } else {
                setState(prev => ({ ...prev, status: 'failed', error: response?.error ?? 'Connection failed' }))
            }
        })
    }

    return { state, startScan, stopScan, checkInstallation }
}
