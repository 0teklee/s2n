/**
 * S2N Scanner - Domain model (scan/finding types, fresh-state factory, invariants)
 *
 * This module must not import `chrome` or React — it is pure data + pure functions
 * so it can be unit tested and reused by both the background worker and the UI.
 */

/** 스캔 상태 */
export type ScanStatus = 'idle' | 'validating' | 'scanning' | 'completed' | 'failed' | 'not_installed'

/** 심각도 레벨 */
export type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO'

export const SEVERITIES: readonly Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']

export function isSeverity(value: unknown): value is Severity {
    return typeof value === 'string' && (SEVERITIES as readonly string[]).includes(value)
}

/** UI에서 사용하는 Finding 모델 */
export interface Finding {
    id: string
    plugin: string
    severity: Severity
    title: string
    description: string
    url?: string
    parameter?: string
    method?: string
    evidence?: string
    cweId?: string
    cvssScore?: number
    references: string[]
    timestamp: string
}

/** 스캔 진행률 정보 */
export interface ProgressInfo {
    current: number
    total: number
    percent: number
    message: string
}

/** 스캔 결과 요약 */
export interface ScanSummary {
    totalFindings: number
    severityCounts: Record<Severity, number>
    pluginCounts: Record<string, number>
    totalUrlsScanned: number
    durationSeconds: number
}

/** 스캔 히스토리 항목 */
export interface ScanHistoryItem {
    scanId: string
    targetUrl: string
    timestamp: string
    status: ScanStatus
    summary: ScanSummary
    findings: Finding[]
}

/** 전역 스캔 상태 */
export interface ScanState {
    status: ScanStatus
    targetUrl: string
    selectedPlugins: string[]
    progress: ProgressInfo | null
    findings: Finding[]
    summary: ScanSummary | null
    error: string | null
}

/** 사용 가능한 플러그인 목록 */
export const AVAILABLE_PLUGINS = [
    { id: 'xss', name: 'XSS', description: 'Cross-site scripting' },
    { id: 'sqlinjection', name: 'SQL Injection', description: 'SQL injection attacks' },
    { id: 'csrf', name: 'CSRF', description: 'Request forgery' },
    { id: 'brute_force', name: 'Brute Force', description: 'Password enumeration' },
    { id: 'file_upload', name: 'File Upload', description: 'Malicious file upload' },
    { id: 'oscommand', name: 'OS Command', description: 'Command injection' },
    { id: 'soft_brute_force', name: 'Soft Brute Force', description: 'Rate-limited login attacks' },
    { id: 'jwt', name: 'JWT', description: 'JWT vulnerability analysis' },
    { id: 'autobot', name: 'Autobot', description: 'Automated behavior detection' },
    { id: 'path_traversal', name: 'Path Traversal', description: 'Directory/file traversal attacks' },
    { id: 'sensitive_files', name: 'Sensitive Files', description: 'Exposed sensitive file discovery' },
]

/** 초기 스캔 상태 — 호출할 때마다 새 배열/객체를 생성한다 (공유 뮤터블 상태 금지) */
export function createInitialScanState(): ScanState {
    return {
        status: 'idle',
        targetUrl: '',
        selectedPlugins: [],
        progress: null,
        findings: [],
        summary: null,
        error: null,
    }
}

/**
 * Finding의 안정적인 dedup/selection 키.
 * id가 없는(또는 손상된) 데이터에 대한 방어적 fallback으로 상세 필드 조합을 사용한다.
 */
export function getFindingKey(finding: Finding): string {
    return finding.id || `${finding.title}__${finding.url ?? ''}__${finding.severity}__${finding.parameter ?? ''}`
}

/**
 * 레거시 단일 `reference` 필드와 신규 `references` 배열을 모두 문자열 배열로 정규화한다.
 */
export function normalizeReferences(raw: unknown): string[] {
    if (Array.isArray(raw)) return raw.filter((r): r is string => typeof r === 'string' && r.length > 0)
    if (typeof raw === 'string' && raw.length > 0) return [raw]
    return []
}
