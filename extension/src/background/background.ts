/**
 * S2N Scanner - Background Service Worker
 *
 * Thin message router — all scan session state/lifecycle logic lives in
 * `scanController.ts`.
 */

import { sendNativeMessage, isNotInstalledError } from '@/lib/nativeMessaging'
import { scanController } from './scanController'

function broadcastStateUpdate() {
    chrome.runtime.sendMessage({
        type: 'state_update',
        state: scanController.getState(),
    }).catch(() => { })
}

scanController.subscribe(() => broadcastStateUpdate())

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {

    if (message.type === 'ping') {
        sendNativeMessage({ action: 'ping' })
            .then((response) => sendResponse({ success: true, data: response }))
            .catch((err) => {
                const msg = err instanceof Error ? err.message : 'Unknown error'
                if (isNotInstalledError(msg)) {
                    scanController.markNotInstalledIfIdle(msg)
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
        sendResponse(scanController.getState())
        return false
    }

    if (message.type === 'start_scan') {
        const { targetUrl, plugins, acceptRisk } = message.payload
        sendResponse(scanController.startScan(targetUrl, plugins, acceptRisk))
        return false
    }

    if (message.type === 'stop_scan') {
        sendResponse(scanController.stopScan())
        return false
    }

    return false
})

console.log('[S2N] Background service worker loaded.')
