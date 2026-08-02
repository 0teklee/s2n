/**
 * S2N Scanner - Report Generate & Export Utility
 */

import type { ScanHistoryItem } from '@/types/scan'
import { generateHtmlReport } from './report-template'

/**
 * Blob을 파일로 다운로드 트리거
 */
function downloadBlob(content: string, mimeType: string, filename: string) {
    const blob = new Blob([content], { type: mimeType })
    const url = URL.createObjectURL(blob)

    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()

    setTimeout(() => {
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
    }, 100)
}

/**
 * 스캔 결과를 JSON 파일로 내보내기
 */
export function exportFindingsToJson(scan: ScanHistoryItem) {
    const dataStr = JSON.stringify(scan, null, 2)
    downloadBlob(dataStr, 'application/json', `s2n_report_${scan.scanId}.json`)
}

/**
 * 스캔 결과를 HTML 리포트 문서로 내보내기
 */
export function exportFindingsToHtml(scan: ScanHistoryItem) {
    const htmlStr = generateHtmlReport(scan)
    downloadBlob(htmlStr, 'text/html', `s2n_report_${scan.scanId}.html`)
}
