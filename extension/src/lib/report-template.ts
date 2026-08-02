/**
 * S2N Scanner - HTML Report Template generator
 */

import type { ScanHistoryItem } from '@/types/scan'

/**
 * HTML 특수문자 이스케이프 — XSS 방지
 */
function esc(s: string | undefined | null): string {
    if (!s) return ''
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
}

function safeHref(value: string): string | null {
    try {
        const url = new URL(value)
        return url.protocol === 'http:' || url.protocol === 'https:' ? esc(url.href) : null
    } catch {
        return null
    }
}

/**
 * 통계 데이터를 포함한 예쁜 HTML 리포트 생성
 */
export function generateHtmlReport(scan: ScanHistoryItem): string {
    const findingsListHtml = scan.findings.map(finding => {
        const reference = finding.reference ? safeHref(finding.reference) : null
        return `
        <article class="finding">
            <div class="finding-head">
                <h3>${esc(finding.title)}</h3>
                <span class="severity severity-${finding.severity.toLowerCase()}">${esc(finding.severity)}</span>
            </div>
            <p class="description">${esc(finding.description)}</p>
            <dl class="details">
                ${finding.url ? `<div><dt>URL</dt><dd>${esc(finding.url)}</dd></div>` : ''}
                ${finding.method ? `<div><dt>Method</dt><dd>${esc(finding.method)}</dd></div>` : ''}
                ${finding.plugin ? `<div><dt>Plugin</dt><dd>${esc(finding.plugin)}</dd></div>` : ''}
                ${finding.parameter ? `<div><dt>Parameter</dt><dd>${esc(finding.parameter)}</dd></div>` : ''}
                ${finding.cweId ? `<div><dt>CWE</dt><dd>${esc(finding.cweId)}</dd></div>` : ''}
                ${finding.cvssScore !== undefined ? `<div><dt>CVSS Score</dt><dd>${finding.cvssScore}</dd></div>` : ''}
            </dl>
            ${finding.evidence ? `<section class="evidence"><strong>Evidence</strong><pre>${esc(finding.evidence)}</pre></section>` : ''}
            ${reference ? `<p class="reference"><strong>Reference:</strong> <a href="${reference}" target="_blank" rel="noopener noreferrer">${esc(finding.reference)}</a></p>` : ''}
        </article>`
    }).join('')

    return `
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>S2N Scanner Report - ${esc(scan.targetUrl)}</title>
    <style>
        * { box-sizing: border-box; }
        body { margin: 0; padding: 32px; background: #f4f4f5; color: #27272a; font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
        main { max-width: 960px; margin: 0 auto; }
        header { padding: 24px; margin-bottom: 24px; background: #fff; border-top: 4px solid #2563eb; }
        h1, h2, h3, p { margin-top: 0; }
        .target { color: #1d4ed8; overflow-wrap: anywhere; }
        .summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 28px; }
        .stat { padding: 16px; background: #fff; border-left: 4px solid #71717a; }
        .stat span { display: block; color: #71717a; font-size: 12px; }
        .stat strong { font-size: 24px; }
        .finding { padding: 18px; margin-bottom: 14px; background: #fff; border: 1px solid #e4e4e7; overflow-wrap: anywhere; }
        .finding-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
        .finding h3 { margin-bottom: 8px; }
        .severity { flex: none; padding: 3px 8px; color: #fff; font-size: 11px; font-weight: 700; }
        .severity-critical { background: #dc2626; } .severity-high { background: #ea580c; }
        .severity-medium { background: #ca8a04; } .severity-low { background: #2563eb; } .severity-info { background: #52525b; }
        .description { white-space: pre-wrap; color: #52525b; }
        .details { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; padding: 12px; background: #fafafa; }
        .details div { min-width: 0; } dt { font-weight: 700; } dd { margin: 0; overflow-wrap: anywhere; }
        .evidence, .reference { margin-top: 14px; }
        pre { padding: 12px; overflow: auto; background: #27272a; color: #f4f4f5; white-space: pre-wrap; }
        a { color: #2563eb; }
        footer { margin-top: 28px; color: #71717a; text-align: center; }
        @media (max-width: 680px) { body { padding: 16px; } .summary, .details { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <main>
        <header>
            <h1>S2N Vulnerability Scan Report</h1>
            <p>Generated on ${esc(new Date(scan.timestamp).toLocaleString())}</p>
            <strong>Target</strong>
            <div class="target">${esc(scan.targetUrl)}</div>
            <div>Status: ${esc(scan.status.toUpperCase())}</div>
        </header>

        <!-- Summary Statistics -->
        <section class="summary">
            <div class="stat"><span>Critical & High</span><strong>${(scan.summary.severityCounts.CRITICAL || 0) + (scan.summary.severityCounts.HIGH || 0)}</strong></div>
            <div class="stat"><span>Medium</span><strong>${scan.summary.severityCounts.MEDIUM || 0}</strong></div>
            <div class="stat"><span>Low & Info</span><strong>${(scan.summary.severityCounts.LOW || 0) + (scan.summary.severityCounts.INFO || 0)}</strong></div>
            <div class="stat"><span>Total Findings</span><strong>${scan.summary.totalFindings}</strong></div>
        </section>

        <!-- Findings List -->
        <section>
            <h2>Detailed Findings</h2>
            ${scan.findings.length > 0 ? findingsListHtml : '<p>No vulnerabilities found.</p>'}
        </section>
        
        <footer>
            <p>S2N Scanner Extension • Automatic Vulnerability Discovery</p>
        </footer>
    </main>
</body>
</html>
    `
}
