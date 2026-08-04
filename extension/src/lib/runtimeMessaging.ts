/**
 * S2N Scanner - Typed background command helper
 *
 * Wraps chrome.runtime.sendMessage so both `chrome.runtime.lastError` and an
 * explicit `{ success: false }` response become a rejected promise. Popup code
 * should treat only the background's broadcasted state as authoritative;
 * this helper is for the short-lived command acknowledgement only.
 */

export interface ExtensionResponse<T = unknown> {
    success: boolean
    data?: T
    error?: string
}

export function sendRuntimeCommand<T = unknown>(message: unknown): Promise<ExtensionResponse<T>> {
    return new Promise((resolve, reject) => {
        try {
            chrome.runtime.sendMessage(message, (response: ExtensionResponse<T> | undefined) => {
                if (chrome.runtime.lastError) {
                    reject(new Error(chrome.runtime.lastError.message ?? 'Extension messaging error'))
                    return
                }
                if (!response) {
                    reject(new Error('No response from background'))
                    return
                }
                if (response.success === false) {
                    reject(new Error(response.error ?? 'Command failed'))
                    return
                }
                resolve(response)
            })
        } catch (err) {
            reject(err instanceof Error ? err : new Error(String(err)))
        }
    })
}
