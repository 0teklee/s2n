/**
 * S2N Scanner - 스캔 상태 모델 (Type Definitions)
 */

/** 스캔 상태 */
export type ScanStatus = 'idle' | 'validating' | 'scanning' | 'completed' | 'failed' | 'not_installed'

/** 심각도 레벨 */
export type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO'

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
    reference?: string
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
]

/** 초기 스캔 상태 */
export const INITIAL_SCAN_STATE: ScanState = {
    status: 'idle',
    targetUrl: '',
    selectedPlugins: [],
    progress: null,
    findings: [],
    summary: null,
    error: null,
}
