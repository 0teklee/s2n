/**
 * S2N Scanner - Local Storage Utility
 */

import { normalizeReferences } from '@/types/scan'
import type { ScanHistoryItem } from '@/types/scan'

const STORAGE_KEY = 's2n_scan_history'
// unlimitedStorage 권한이 없어 chrome.storage.local 기본 할당량(10MB)에 걸릴 수 있음 — 오래된 기록부터 제거
const MAX_HISTORY_ITEMS = 50
const MAX_HISTORY_BYTES = 8 * 1024 * 1024

function storageError(): Error | null {
    return chrome.runtime.lastError ? new Error(chrome.runtime.lastError.message) : null
}

function trimHistory(history: ScanHistoryItem[]): ScanHistoryItem[] {
    const trimmed = history.slice(0, MAX_HISTORY_ITEMS)
    while (trimmed.length > 1 && new TextEncoder().encode(JSON.stringify(trimmed)).length > MAX_HISTORY_BYTES) {
        trimmed.pop()
    }
    return trimmed
}

/** 구 버전 저장 데이터의 단일 `reference` 필드를 `references` 배열로 정규화한다 (EXT-007). */
function migrateHistoryItem(item: ScanHistoryItem): ScanHistoryItem {
    return {
        ...item,
        findings: (item.findings ?? []).map((finding) => {
            const legacy = finding as unknown as { reference?: unknown; references?: unknown }
            return {
                ...finding,
                references: Array.isArray(legacy.references) ? (legacy.references as string[]) : normalizeReferences(legacy.reference),
            }
        }),
    }
}

/**
 * 히스토리 전체 로드
 */
export async function getScanHistory(): Promise<ScanHistoryItem[]> {
    return new Promise((resolve, reject) => {
        chrome.storage.local.get([STORAGE_KEY], (result) => {
            const error = storageError()
            if (error) {
                reject(error)
                return
            }
            const history = result[STORAGE_KEY]
            resolve(Array.isArray(history) ? history.map(migrateHistoryItem) : [])
        })
    })
}

/**
 * 새로운 스캔 결과를 히스토리에 추가
 * 최신순 정렬을 위해 배열 앞에 추가 (unshift)
 */
export async function saveScanHistory(item: ScanHistoryItem): Promise<void> {
    const history = await getScanHistory()
    history.unshift(item)
    const trimmed = trimHistory(history)
    return new Promise((resolve, reject) => {
        chrome.storage.local.set({ [STORAGE_KEY]: trimmed }, () => {
            const error = storageError()
            if (error) reject(error)
            else resolve()
        })
    })
}

/**
 * 히스토리 중 특정 항목만 삭제
 */
export async function deleteScanHistoryItem(scanId: string): Promise<void> {
    const history = await getScanHistory()
    const newHistory = history.filter(item => item.scanId !== scanId)
    return new Promise((resolve, reject) => {
        chrome.storage.local.set({ [STORAGE_KEY]: newHistory }, () => {
            const error = storageError()
            if (error) reject(error)
            else resolve()
        })
    })
}

/**
 * 전체 히스토리 삭제
 */
export async function clearScanHistory(): Promise<void> {
    return new Promise((resolve, reject) => {
        chrome.storage.local.remove([STORAGE_KEY], () => {
            const error = storageError()
            if (error) reject(error)
            else resolve()
        })
    })
}
