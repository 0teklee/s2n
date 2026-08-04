import { describe, expect, it } from 'vitest'

import { generateHtmlReport } from './report-template'
import type { ScanHistoryItem } from '../types/scan'

describe('generateHtmlReport', () => {
    it('escapes findings, blocks unsafe links, and contains no remote scripts', () => {
        const scan: ScanHistoryItem = {
            scanId: 'scan-1',
            targetUrl: 'https://example.com/<script>',
            timestamp: new Date().toISOString(),
            status: 'completed',
            summary: {
                totalFindings: 1,
                severityCounts: { CRITICAL: 0, HIGH: 1, MEDIUM: 0, LOW: 0, INFO: 0 },
                pluginCounts: { xss: 1 },
                totalUrlsScanned: 1,
                durationSeconds: 1,
            },
            findings: [{
                id: 'finding-1',
                plugin: 'xss',
                severity: 'HIGH',
                title: '<script>alert(1)</script>',
                description: '<img src=x onerror=alert(1)>',
                references: ['javascript:alert(1)', 'https://owasp.org/www-community/attacks/xss/'],
                timestamp: new Date().toISOString(),
            }],
        }

        const report = generateHtmlReport(scan)

        expect(report).toContain('&lt;script&gt;alert(1)&lt;/script&gt;')
        expect(report).not.toContain('<script')
        expect(report).not.toContain('href="javascript:')
        expect(report).not.toContain('cdn.tailwindcss.com')
        expect(report).toContain('href="https://owasp.org/www-community/attacks/xss/"')
    })
})
