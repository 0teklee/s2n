/**
 * S2N Scanner - Native Messaging 유틸 모듈
 * ==========================================
 * Chrome Extension Service Worker에서 Native Messaging Host(native_host.py)와
 * 통신하기 위한 유틸리티 함수와 타입 정의.
 *
 * 두 가지 통신 모드:
 * 1. sendNativeMessage — 단발성 요청/응답 (ping, get_version 등)
 * 2. connectNative — 장기 연결 포트 (스캔 스트리밍 등)
 */

// ============================================================================
// 상수
// ============================================================================

/** Native Messaging Host 식별자 (manifest.json의 name과 일치) */
export const NATIVE_HOST_NAME = 'com.s2n.scanner'

// ============================================================================
// 타입 정의
// ============================================================================

/** Native Host로 보내는 요청 메시지 */
export interface NativeRequest {
    action: string
    data?: Record<string, unknown>
}

/** Native Host에서 수신하는 응답 메시지 */
export interface NativeResponse {
    status: 'ok' | 'error'
    action?: string
    data?: Record<string, unknown>
    error?: string
}

/** connectNative 포트 이벤트 콜백 */
export interface NativePortCallbacks {
    onMessage?: (message: NativeResponse) => void
    onDisconnect?: (error?: string) => void
}

// ============================================================================
// 단발성 메시지 (sendNativeMessage)
// ============================================================================

/**
 * Native Host에 단발성 메시지를 보내고 응답을 기다립니다.
 * 주로 ping, get_version 등 짧은 요청/응답에 사용.
 *
 * @param message - 전송할 요청 메시지
 * @returns Promise<NativeResponse>
 * @throws Error - 연결 실패 또는 호스트 에러
 *
 * @example
 * ```ts
 * const res = await sendNativeMessage({ action: 'ping' })
 * console.log(res) // { status: 'ok', action: 'pong' }
 * ```
 */
export function sendNativeMessage(message: NativeRequest): Promise<NativeResponse> {
    return new Promise((resolve, reject) => {
        try {
            chrome.runtime.sendNativeMessage(
                NATIVE_HOST_NAME,
                message,
                (response: NativeResponse) => {
                    if (chrome.runtime.lastError) {
                        reject(new Error(chrome.runtime.lastError.message ?? 'Native messaging error'))
                        return
                    }
                    resolve(response)
                },
            )
        } catch (err) {
            reject(err instanceof Error ? err : new Error(String(err)))
        }
    })
}

// ============================================================================
// 장기 연결 (connectNative)
// ============================================================================

/**
 * Native Host와 장기 연결 포트를 생성합니다.
 * 스캔 스트리밍 등 지속적인 메시지 교환에 사용.
 *
 * @param callbacks - 메시지 수신/연결 해제 콜백
 * @returns chrome.runtime.Port
 *
 * @example
 * ```ts
 * const port = connectNative({
 *   onMessage: (msg) => console.log('Received:', msg),
 *   onDisconnect: (err) => console.log('Disconnected:', err),
 * })
 * port.postMessage({ action: 'start_scan', data: { target_url: '...' } })
 * ```
 */
export function connectNative(callbacks?: NativePortCallbacks): chrome.runtime.Port {
    const port = chrome.runtime.connectNative(NATIVE_HOST_NAME)

    if (callbacks?.onMessage) {
        port.onMessage.addListener(callbacks.onMessage)
    }

    if (callbacks?.onDisconnect) {
        port.onDisconnect.addListener(() => {
            const error = chrome.runtime.lastError?.message
            callbacks.onDisconnect!(error)
        })
    }

    return port
}

/**
 * Native Messaging 포트를 안전하게 해제합니다.
 *
 * @param port - 해제할 포트
 */
export function disconnectNative(port: chrome.runtime.Port | null): void {
    if (port) {
        try {
            port.disconnect()
        } catch {
            // 이미 해제된 포트 — 무시
        }
    }
}

/**
 * 에러 메시지가 native host 미설치/미등록으로 인한 것인지 판별합니다.
 *
 * Chrome이 반환하는 대표적인 메시지:
 *  - "Specified native messaging host not found."  (manifest 없음 / s2n 미설치)
 *  - "Access to the specified native messaging host is forbidden."  (extension ID 불일치)
 */
export function isNotInstalledError(error?: string | null): boolean {
    if (!error) return false
    const msg = error.toLowerCase()
    return (
        msg.includes('not found') ||
        msg.includes('forbidden') ||
        msg.includes('specified native messaging host')
    )
}
