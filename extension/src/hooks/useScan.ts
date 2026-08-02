import { useState, useEffect } from 'react'
import { createInitialScanState } from '@/types/scan'
import type { ScanState } from '@/types/scan'
import { isNotInstalledError } from '@/lib/nativeMessaging'
import { sendRuntimeCommand, type ExtensionResponse } from '@/lib/runtimeMessaging'

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
        // 짧은 로컬 낙관적 상태 — background의 상태 브로드캐스트가 항상 최종 권위를 가진다.
        setState({
            ...createInitialScanState(),
            status: 'validating',
            targetUrl,
            selectedPlugins: plugins,
        })
        sendRuntimeCommand({ type: 'start_scan', payload: { targetUrl, plugins, acceptRisk } })
            .catch((err: unknown) => {
                setState(prev => ({ ...prev, status: 'failed', error: err instanceof Error ? err.message : 'Unable to start scan' }))
            })
    }

    const stopScan = () => {
        sendRuntimeCommand({ type: 'stop_scan' })
            .then(() => setState(createInitialScanState()))
            .catch((err: unknown) => {
                console.error('[useScan] stop_scan failed:', err)
                // 배경 세션이 이미 없거나 응답이 없어도 UI가 멈춰있지 않도록 로컬 상태는 초기화한다.
                setState(createInitialScanState())
            })
    }

    /** s2n 설치 후 연결을 재확인합니다. 성공 시 idle로 복귀. */
    const checkInstallation = () => {
        sendRuntimeCommand({ type: 'ping' })
            .then(() => setState(createInitialScanState()))
            .catch((err: unknown) => {
                const message = err instanceof Error ? err.message : 'Connection failed'
                if (isNotInstalledError(message)) {
                    setState(prev => ({ ...prev, status: 'not_installed', error: message }))
                } else {
                    setState(prev => ({ ...prev, status: 'failed', error: message }))
                }
            })
    }

    return { state, startScan, stopScan, checkInstallation }
}
