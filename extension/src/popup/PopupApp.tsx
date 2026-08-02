import { useState, useEffect, useRef } from 'react'
import type { FormEvent } from 'react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useScan } from '@/hooks/useScan'
import { AVAILABLE_PLUGINS } from '@/types/scan'
import type { Severity } from '@/types/scan'
import {
    Play, Square, Loader2, AlertTriangle,
    ShieldCheck, ShieldAlert, X, Download,
    House, ChevronDown, ChevronUp, Info,
    Terminal, RefreshCw,
} from 'lucide-react'
import { exportFindingsToJson, exportFindingsToHtml } from '@/lib/export'

const SEV: Record<Severity, { dot: string; label: string; bar: string }> = {
    CRITICAL: { dot: '#ef4444', label: '#f87171', bar: '#ef4444' },
    HIGH: { dot: '#f97316', label: '#fb923c', bar: '#f97316' },
    MEDIUM: { dot: '#eab308', label: '#facc15', bar: '#eab308' },
    LOW: { dot: '#3b82f6', label: '#60a5fa', bar: '#3b82f6' },
    INFO: { dot: '#71717a', label: '#a1a1aa', bar: '#71717a' },
}
const SEV_ORDER: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']

const cleanMsg = (s: string) =>
    s.replace(/[\u{1F000}-\u{1FFFF}]/gu, '').replace(/\s{2,}/g, ' ').trim()

const css = {
    root: {
        width: 420,
        height: 560,
        display: 'flex',
        flexDirection: 'column' as const,
        background: '#111113',
        color: '#f4f4f5',
        fontFamily: '"Inter", -apple-system, BlinkMacSystemFont, sans-serif',
        overflow: 'hidden',
        fontSize: 13,
    },
    header: {
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px 16px',
        borderBottom: '1px solid rgba(255,255,255,0.07)',
        flexShrink: 0,
    },
    label: {
        fontSize: 10,
        fontWeight: 600,
        letterSpacing: '0.08em',
        textTransform: 'uppercase' as const,
        color: 'rgba(255,255,255,0.3)',
    },
    input: {
        width: '100%',
        height: 38,
        padding: '0 12px',
        borderRadius: 8,
        background: 'rgba(255,255,255,0.05)',
        border: '1px solid rgba(255,255,255,0.08)',
        color: '#f4f4f5',
        fontSize: 12,
        outline: 'none',
        transition: 'border-color 0.15s',
        boxSizing: 'border-box' as const,
        fontFamily: 'inherit',
    },
    card: {
        borderRadius: 8,
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid rgba(255,255,255,0.07)',
        padding: '10px 12px',
    },
    btn: {
        width: '100%',
        height: 38,
        borderRadius: 8,
        border: 'none',
        background: '#f4f4f5',
        color: '#111113',
        fontSize: 12,
        fontWeight: 700,
        letterSpacing: '0.04em',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 7,
        transition: 'opacity 0.15s, transform 0.1s',
        fontFamily: 'inherit',
    },
    divider: {
        height: 1,
        background: 'rgba(255,255,255,0.06)',
        margin: '4px 0',
    },
}

export function PopupApp() {
    const { state, startScan, stopScan, checkInstallation } = useScan()
    const [url, setUrl] = useState('')
    const [selected, setSelected] = useState<string[]>(AVAILABLE_PLUGINS.map(p => p.id))
    const [showFindings, setShowFindings] = useState(false)
    const [smoothPct, setSmoothPct] = useState(0)
    const smoothPctRef = useRef(0)

    const isScanning = state.status === 'validating' || state.status === 'scanning'
    const isCompleted = state.status === 'completed'
    const isNotInstalled = state.status === 'not_installed'
    const isIdle = !isScanning && !isCompleted && !isNotInstalled
    const total = state.summary?.totalFindings ?? 0
    const hasFindings = total > 0
    const maxCount = Math.max(...SEV_ORDER.map(s => state.summary?.severityCounts[s] ?? 0), 1)
    const pct = Math.max(0, state.progress?.percent ?? 0)

    // 스캔 시작/종료 시 smoothPct 리셋
    useEffect(() => {
        if (!isScanning) {
            smoothPctRef.current = 0
            setSmoothPct(0)
            return
        }
        // 실제 pct보다 smoothPct가 낮으면 따라가고,
        // 실제 pct 업데이트 없이도 천천히 올라가는 fake 애니메이션
        const interval = setInterval(() => {
            const target = pct > 0 ? pct : Math.min(smoothPctRef.current + 0.3, 85)
            const next = smoothPctRef.current + (target - smoothPctRef.current) * 0.08
            // 실제 값보다 앞서가지 않도록
            const clamped = Math.min(next, pct > 0 ? pct : 85)
            smoothPctRef.current = clamped
            setSmoothPct(clamped)
        }, 100)
        return () => clearInterval(interval)
    }, [isScanning, pct])

    useEffect(() => {
        if (!url && chrome?.tabs) {
            chrome.tabs.query({ active: true, currentWindow: true }, tabs => {
                const u = tabs[0]?.url
                if (u?.startsWith('http')) setUrl(u)
            })
        }
    }, [])

    const handleStart = (e: FormEvent) => {
        e.preventDefault()
        if (url && selected.length > 0) startScan(url, selected)
    }
    const toggle = (id: string) =>
        setSelected(prev => prev.includes(id) ? prev.filter(p => p !== id) : [...prev, id])
    const handleHome = () => { setShowFindings(false); stopScan() }
    const exportData = () => ({
        scanId: `export_${Date.now()}`,
        targetUrl: state.targetUrl,
        timestamp: new Date().toISOString(),
        status: state.status,
        summary: state.summary ?? {
            totalFindings: 0, durationSeconds: 0,
            severityCounts: { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0, INFO: 0 },
            pluginCounts: {}, totalUrlsScanned: 0,
        },
        findings: state.findings,
    })

    return (
        <div style={css.root}>

            {/* ── HEADER ── */}
            <header style={css.header}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    {/* Logo box — neutral bg so both logos work */}
                    <div style={{
                        width: 28, height: 28, borderRadius: 7,
                        background: 'rgba(255,255,255,0.08)',
                        border: '1px solid rgba(255,255,255,0.1)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        flexShrink: 0,
                    }}>
                        <img src="icons/logo2.png" alt="S2N"
                            style={{ width: 16, height: 16, objectFit: 'contain' }} />
                    </div>
                    <div>
                        <span style={{ fontSize: 14, fontWeight: 700, color: '#fff', letterSpacing: '-0.01em' }}>S2N</span>
                        <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)', marginLeft: 6, fontWeight: 400 }}>Security Scanner</span>
                    </div>
                </div>

                {/* Status chip */}
                <div style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '4px 10px', borderRadius: 20,
                    background: isScanning ? 'rgba(59,130,246,0.12)' :
                        isCompleted ? 'rgba(34,197,94,0.1)' :
                            state.status === 'failed' ? 'rgba(239,68,68,0.1)' :
                                isNotInstalled ? 'rgba(234,179,8,0.1)' :
                                    'rgba(255,255,255,0.06)',
                    border: `1px solid ${isScanning ? 'rgba(59,130,246,0.25)' :
                            isCompleted ? 'rgba(34,197,94,0.2)' :
                                state.status === 'failed' ? 'rgba(239,68,68,0.2)' :
                                    isNotInstalled ? 'rgba(234,179,8,0.2)' :
                                        'rgba(255,255,255,0.08)'
                        }`,
                }}>
                    <span style={{
                        width: 6, height: 6, borderRadius: '50%',
                        background: isScanning ? '#3b82f6' :
                            isCompleted ? '#22c55e' :
                                state.status === 'failed' ? '#ef4444' :
                                    isNotInstalled ? '#eab308' : '#52525b',
                        flexShrink: 0,
                        boxShadow: isScanning ? '0 0 0 2px rgba(59,130,246,0.3)' : 'none',
                        animation: isScanning ? 'pulse 1.5s infinite' : 'none',
                    }} />
                    <span style={{
                        fontSize: 10, fontWeight: 600, letterSpacing: '0.08em',
                        textTransform: 'uppercase',
                        color: isScanning ? '#60a5fa' :
                            isCompleted ? '#4ade80' :
                                state.status === 'failed' ? '#f87171' :
                                    isNotInstalled ? '#facc15' : 'rgba(255,255,255,0.4)',
                    }}>
                        {isScanning ? 'Scanning' : isCompleted ? 'Done' : state.status === 'failed' ? 'Error' : isNotInstalled ? 'Setup' : 'Ready'}
                    </span>
                </div>
            </header>

            {/* Thin progress bar under header */}
            {isScanning && (
                <div style={{ height: 2, background: 'rgba(255,255,255,0.05)', flexShrink: 0 }}>
                    <div style={{
                        height: '100%', width: `${smoothPct}%`,
                        background: 'linear-gradient(90deg, #3b82f6, #818cf8)',
                        transition: 'width 0.1s linear',
                        borderRadius: 1,
                    }} />
                </div>
            )}

            {/* ── CONTENT ── */}
            <ScrollArea className="flex-1 min-h-0">
                <div style={{ padding: '16px 16px 20px' }}>

                    {/* Error — not_installed일 때는 아래 전용 화면이 대체하므로 숨김 */}
                    {state.error && !isNotInstalled && (
                        <div style={{
                            display: 'flex', alignItems: 'flex-start', gap: 8,
                            padding: '10px 12px', borderRadius: 8, marginBottom: 14,
                            background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)',
                            color: '#f87171', fontSize: 11,
                        }}>
                            <AlertTriangle size={13} style={{ flexShrink: 0, marginTop: 1 }} />
                            <span style={{ flex: 1, lineHeight: 1.5 }}>{state.error}</span>
                            <button onClick={stopScan} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#f87171', padding: 0, flexShrink: 0 }}>
                                <X size={13} />
                            </button>
                        </div>
                    )}

                    {/* ════════ NOT INSTALLED ════════ */}
                    {isNotInstalled && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

                            {/* 경고 헤더 */}
                            <div style={{
                                display: 'flex', alignItems: 'flex-start', gap: 10,
                                padding: '12px 14px', borderRadius: 8,
                                background: 'rgba(234,179,8,0.07)',
                                border: '1px solid rgba(234,179,8,0.2)',
                            }}>
                                <AlertTriangle size={15} style={{ color: '#facc15', flexShrink: 0, marginTop: 1 }} />
                                <div>
                                    <div style={{ fontSize: 12, fontWeight: 700, color: '#facc15', marginBottom: 3 }}>
                                        S2N host not connected
                                    </div>
                                    <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.4)', lineHeight: 1.5 }}>
                                        The native messaging host could not be found or is not authorized for this extension.
                                    </div>
                                </div>
                            </div>

                            {/* 설치 단계 */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                                {[
                                    {
                                        step: '1',
                                        title: 'Install s2n',
                                        cmd: 'pip install s2n',
                                        note: 'Already installed? Run pip install --upgrade s2n',
                                    },
                                    {
                                        step: '2',
                                        title: 'Register the native host',
                                        cmd: 's2n install-gui',
                                        note: 'Press Enter to use the default extension ID, or paste yours.',
                                    },
                                    {
                                        step: '3',
                                        title: 'Restart Chrome',
                                        cmd: null,
                                        note: 'Close and reopen Chrome completely (not just this tab).',
                                    },
                                ].map(({ step, title, cmd, note }) => (
                                    <div key={step} style={{
                                        ...css.card,
                                        display: 'flex', gap: 12, alignItems: 'flex-start',
                                    }}>
                                        <div style={{
                                            width: 20, height: 20, borderRadius: '50%', flexShrink: 0,
                                            background: 'rgba(234,179,8,0.12)',
                                            border: '1px solid rgba(234,179,8,0.25)',
                                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                                            fontSize: 10, fontWeight: 800, color: '#facc15',
                                        }}>{step}</div>
                                        <div style={{ minWidth: 0 }}>
                                            <div style={{ fontSize: 11, fontWeight: 600, color: 'rgba(255,255,255,0.75)', marginBottom: cmd ? 6 : 4 }}>
                                                {title}
                                            </div>
                                            {cmd && (
                                                <div style={{
                                                    display: 'flex', alignItems: 'center', gap: 6,
                                                    padding: '5px 8px', borderRadius: 5,
                                                    background: 'rgba(0,0,0,0.35)',
                                                    border: '1px solid rgba(255,255,255,0.07)',
                                                    marginBottom: 5,
                                                }}>
                                                    <Terminal size={10} style={{ color: 'rgba(255,255,255,0.3)', flexShrink: 0 }} />
                                                    <code style={{ fontSize: 11, color: '#a5f3fc', fontFamily: 'monospace', letterSpacing: '0.01em' }}>
                                                        {cmd}
                                                    </code>
                                                </div>
                                            )}
                                            <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.28)', lineHeight: 1.5 }}>
                                                {note}
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>

                            {/* 재확인 버튼 */}
                            <button
                                type="button"
                                onClick={checkInstallation}
                                style={{
                                    ...css.btn,
                                    background: 'rgba(234,179,8,0.12)',
                                    border: '1px solid rgba(234,179,8,0.25)',
                                    color: '#facc15',
                                }}
                                onMouseEnter={e => { e.currentTarget.style.background = 'rgba(234,179,8,0.2)' }}
                                onMouseLeave={e => { e.currentTarget.style.background = 'rgba(234,179,8,0.12)' }}
                            >
                                <RefreshCw size={12} />
                                Retry Connection
                            </button>
                        </div>
                    )}

                    {/* ════════ IDLE ════════ */}
                    {isIdle && (
                        <form onSubmit={handleStart}>
                            <div style={{ marginBottom: 16 }}>
                                <div style={{ ...css.label, marginBottom: 7 }}>Target URL</div>
                                <input
                                    type="url"
                                    placeholder="https://example.com"
                                    value={url}
                                    onChange={e => setUrl(e.target.value)}
                                    required
                                    style={css.input}
                                    onFocus={e => e.currentTarget.style.borderColor = 'rgba(255,255,255,0.2)'}
                                    onBlur={e => e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)'}
                                />
                            </div>

                            <div style={{ marginBottom: 16 }}>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                                    <div style={css.label}>Scan Modules</div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                        <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.25)', fontWeight: 500, background: 'rgba(255,255,255,0.06)', padding: '2px 6px', borderRadius: 4 }}>
                                            {selected.length}/{AVAILABLE_PLUGINS.length}
                                        </span>
                                        <button
                                            type="button"
                                            onClick={() => setSelected(selected.length === AVAILABLE_PLUGINS.length ? [] : AVAILABLE_PLUGINS.map(p => p.id))}
                                            style={{
                                                background: 'rgba(255,255,255,0.07)',
                                                border: '1px solid rgba(255,255,255,0.12)',
                                                borderRadius: 5,
                                                cursor: 'pointer',
                                                color: 'rgba(255,255,255,0.6)',
                                                fontSize: 10,
                                                fontWeight: 600,
                                                padding: '3px 8px',
                                                fontFamily: 'inherit',
                                                transition: 'all 0.12s',
                                            }}
                                            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.12)'; e.currentTarget.style.color = '#fff' }}
                                            onMouseLeave={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.07)'; e.currentTarget.style.color = 'rgba(255,255,255,0.6)' }}
                                        >
                                            {selected.length === AVAILABLE_PLUGINS.length ? 'Deselect all' : 'Select all'}
                                        </button>
                                    </div>
                                </div>

                                {/* 2-col grid — compact rows */}
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 5 }}>
                                    {AVAILABLE_PLUGINS.map(plugin => {
                                        const on = selected.includes(plugin.id)
                                        return (
                                            <button
                                                key={plugin.id}
                                                type="button"
                                                onClick={() => toggle(plugin.id)}
                                                style={{
                                                    display: 'flex', alignItems: 'center', gap: 8,
                                                    padding: '8px 10px', borderRadius: 7, cursor: 'pointer',
                                                    background: on ? 'rgba(255,255,255,0.07)' : 'rgba(255,255,255,0.03)',
                                                    border: `1px solid ${on ? 'rgba(255,255,255,0.13)' : 'rgba(255,255,255,0.06)'}`,
                                                    textAlign: 'left', transition: 'all 0.12s',
                                                    fontFamily: 'inherit',
                                                }}
                                            >
                                                {/* Custom checkbox */}
                                                <span style={{
                                                    width: 14, height: 14, borderRadius: 4, flexShrink: 0,
                                                    background: on ? '#f4f4f5' : 'transparent',
                                                    border: `1.5px solid ${on ? '#f4f4f5' : 'rgba(255,255,255,0.2)'}`,
                                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                                    transition: 'all 0.12s',
                                                }}>
                                                    {on && (
                                                        <svg width="8" height="6" viewBox="0 0 8 6" fill="none">
                                                            <path d="M1 3l2 2 4-4" stroke="#111113" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                                                        </svg>
                                                    )}
                                                </span>
                                                <div style={{ minWidth: 0 }}>
                                                    <div style={{ fontSize: 11, fontWeight: 600, color: on ? '#f4f4f5' : 'rgba(255,255,255,0.4)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                                        {plugin.name}
                                                    </div>
                                                    <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.22)', marginTop: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                                        {plugin.description}
                                                    </div>
                                                </div>
                                            </button>
                                        )
                                    })}
                                </div>
                            </div>

                            <button
                                type="submit"
                                disabled={!url || selected.length === 0}
                                style={{ ...css.btn, opacity: (!url || selected.length === 0) ? 0.25 : 1 }}
                                onMouseEnter={e => { if (url && selected.length) e.currentTarget.style.opacity = '0.88' }}
                                onMouseLeave={e => { if (url && selected.length) e.currentTarget.style.opacity = '1' }}
                            >
                                <Play size={12} fill="currentColor" />
                                Start Scan
                            </button>
                        </form>
                    )}

                    {/* ════════ SCANNING ════════ */}
                    {isScanning && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

                            {/* Progress card */}
                            <div style={css.card}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                                    <div style={{ minWidth: 0, flex: 1, marginRight: 12 }}>
                                        <div style={{ ...css.label, marginBottom: 4 }}>Target</div>
                                        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.7)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {state.targetUrl}
                                        </div>
                                    </div>
                                    <div style={{ textAlign: 'right', flexShrink: 0 }}>
                                        <span style={{ fontSize: 24, fontWeight: 800, color: '#fff', lineHeight: 1, letterSpacing: '-0.03em' }}>{Math.round(smoothPct)}</span>
                                        <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.3)', marginLeft: 2 }}>%</span>
                                    </div>
                                </div>

                                {/* Progress track */}
                                <div style={{ height: 3, background: 'rgba(255,255,255,0.07)', borderRadius: 2, overflow: 'hidden', marginBottom: 10 }}>
                                    <div style={{
                                        height: '100%', width: `${smoothPct}%`,
                                        background: 'linear-gradient(90deg, #3b82f6, #818cf8)',
                                        borderRadius: 2, transition: 'width 0.1s linear',
                                    }} />
                                </div>

                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'rgba(255,255,255,0.3)', fontSize: 11 }}>
                                    <Loader2 size={11} style={{ animation: 'spin 1s linear infinite', flexShrink: 0 }} />
                                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {cleanMsg(state.progress?.message ?? 'Initializing...')}
                                    </span>
                                </div>
                            </div>

                            {/* Live findings */}
                            <div>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                                    <div style={css.label}>Live Findings</div>
                                    {state.findings.length > 0 && (
                                        <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.25)', fontWeight: 500 }}>
                                            {state.findings.length} detected
                                        </span>
                                    )}
                                </div>

                                {state.findings.length === 0 ? (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '12px 0', color: 'rgba(255,255,255,0.18)' }}>
                                        <ShieldCheck size={14} />
                                        <span style={{ fontSize: 11 }}>No findings yet</span>
                                    </div>
                                ) : (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                                        {state.findings.slice().reverse().slice(0, 6).map((f, i) => (
                                            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0' }}>
                                                <span style={{ width: 6, height: 6, borderRadius: '50%', background: SEV[f.severity].dot, flexShrink: 0 }} />
                                                <span style={{ flex: 1, fontSize: 11, color: 'rgba(255,255,255,0.6)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                    {f.title}
                                                </span>
                                                <span style={{ fontSize: 9, fontWeight: 700, color: SEV[f.severity].label, flexShrink: 0, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                                                    {f.severity}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            {/* Cancel */}
                            <button
                                type="button"
                                onClick={handleHome}
                                style={{
                                    background: 'rgba(239,68,68,0.07)',
                                    border: '1px solid rgba(239,68,68,0.18)',
                                    borderRadius: 7,
                                    cursor: 'pointer',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                                    color: 'rgba(239,68,68,0.6)',
                                    fontSize: 11, fontWeight: 600,
                                    padding: '7px 14px',
                                    fontFamily: 'inherit',
                                    transition: 'all 0.15s',
                                    alignSelf: 'flex-start',
                                }}
                                onMouseEnter={e => {
                                    e.currentTarget.style.background = 'rgba(239,68,68,0.13)'
                                    e.currentTarget.style.borderColor = 'rgba(239,68,68,0.35)'
                                    e.currentTarget.style.color = '#f87171'
                                }}
                                onMouseLeave={e => {
                                    e.currentTarget.style.background = 'rgba(239,68,68,0.07)'
                                    e.currentTarget.style.borderColor = 'rgba(239,68,68,0.18)'
                                    e.currentTarget.style.color = 'rgba(239,68,68,0.6)'
                                }}
                            >
                                <Square size={10} fill="currentColor" />
                                Cancel Scan
                            </button>
                        </div>
                    )}

                    {/* ════════ COMPLETED ════════ */}
                    {isCompleted && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>

                            {/* Result hero */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '4px 0' }}>
                                <div style={{
                                    width: 40, height: 40, borderRadius: 10, flexShrink: 0,
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    background: !hasFindings ? 'rgba(34,197,94,0.1)' :
                                        (state.summary?.severityCounts.CRITICAL ?? 0) > 0 ? 'rgba(239,68,68,0.1)' : 'rgba(234,179,8,0.1)',
                                    border: `1px solid ${!hasFindings ? 'rgba(34,197,94,0.2)' :
                                        (state.summary?.severityCounts.CRITICAL ?? 0) > 0 ? 'rgba(239,68,68,0.2)' : 'rgba(234,179,8,0.2)'}`,
                                    color: !hasFindings ? '#4ade80' :
                                        (state.summary?.severityCounts.CRITICAL ?? 0) > 0 ? '#f87171' : '#facc15',
                                }}>
                                    {hasFindings ? <ShieldAlert size={18} /> : <ShieldCheck size={18} />}
                                </div>
                                <div style={{ minWidth: 0 }}>
                                    <div style={{ fontSize: 14, fontWeight: 700, color: '#fff', letterSpacing: '-0.01em' }}>
                                        {hasFindings ? `${total} Issue${total > 1 ? 's' : ''} Found` : 'All Clear'}
                                    </div>
                                    <div style={{ fontSize: 10, color: 'rgba(255,255,255,0.3)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {state.targetUrl}
                                    </div>
                                </div>
                            </div>

                            <div style={css.divider} />

                            {/* Stats */}
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                                {[
                                    { label: 'Findings', value: String(total), color: hasFindings ? '#f87171' : '#fff' },
                                    { label: 'Duration', value: `${state.summary?.durationSeconds.toFixed(1)}s`, color: '#fff' },
                                ].map(({ label, value, color }) => (
                                    <div key={label} style={{ ...css.card, textAlign: 'center', padding: '10px 8px' }}>
                                        <div style={{ fontSize: 9, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'rgba(255,255,255,0.25)', marginBottom: 5 }}>{label}</div>
                                        <div style={{ fontSize: 18, fontWeight: 800, color, letterSpacing: '-0.02em', lineHeight: 1 }}>{value}</div>
                                    </div>
                                ))}
                            </div>

                            {/* Severity breakdown */}
                            {hasFindings && (
                                <div style={{ ...css.card }}>
                                    <div style={{ ...css.label, marginBottom: 10 }}>Breakdown</div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                                        {SEV_ORDER.map(sev => {
                                            const c = state.summary?.severityCounts[sev] ?? 0
                                            if (!c) return null
                                            return (
                                                <div key={sev} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                                    <span style={{ width: 52, textAlign: 'right', fontSize: 9, fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', color: SEV[sev].label, flexShrink: 0 }}>
                                                        {sev}
                                                    </span>
                                                    <div style={{ flex: 1, height: 3, background: 'rgba(255,255,255,0.07)', borderRadius: 2, overflow: 'hidden' }}>
                                                        <div style={{
                                                            height: '100%', width: `${Math.round((c / maxCount) * 100)}%`,
                                                            background: SEV[sev].bar, borderRadius: 2,
                                                            transition: 'width 0.7s ease',
                                                        }} />
                                                    </div>
                                                    <span style={{ width: 14, textAlign: 'right', fontSize: 11, fontWeight: 700, color: 'rgba(255,255,255,0.4)', flexShrink: 0 }}>{c}</span>
                                                </div>
                                            )
                                        })}
                                    </div>
                                </div>
                            )}

                            {/* Findings accordion */}
                            {hasFindings && (
                                <div style={{ borderRadius: 8, border: '1px solid rgba(255,255,255,0.07)', overflow: 'hidden' }}>
                                    <button
                                        type="button"
                                        onClick={() => setShowFindings(v => !v)}
                                        style={{
                                            width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                            padding: '9px 12px', background: 'rgba(255,255,255,0.04)', border: 'none', cursor: 'pointer',
                                            color: 'rgba(255,255,255,0.4)', fontSize: 11, fontWeight: 600, fontFamily: 'inherit',
                                        }}
                                    >
                                        <span>View all findings</span>
                                        {showFindings ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                                    </button>
                                    {showFindings && (
                                        <div style={{ maxHeight: 150, overflowY: 'auto', background: 'rgba(0,0,0,0.15)' }}>
                                            {state.findings.map((f, i) => (
                                                <div key={i} style={{
                                                    display: 'flex', alignItems: 'center', gap: 8,
                                                    padding: '7px 12px',
                                                    borderTop: i > 0 ? '1px solid rgba(255,255,255,0.04)' : undefined,
                                                }}>
                                                    <span style={{ width: 6, height: 6, borderRadius: '50%', background: SEV[f.severity].dot, flexShrink: 0 }} />
                                                    <span style={{ flex: 1, fontSize: 11, color: 'rgba(255,255,255,0.55)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                        {f.title}
                                                    </span>
                                                    <span style={{ fontSize: 9, fontWeight: 700, color: SEV[f.severity].label, flexShrink: 0, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
                                                        {f.severity}
                                                    </span>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}

                            {/* Export */}
                            <div style={{ opacity: hasFindings ? 1 : 0.25, pointerEvents: hasFindings ? 'auto' : 'none' }}>
                                <div style={{ ...css.label, marginBottom: 7 }}>Export</div>
                                <div style={{ display: 'flex', gap: 6 }}>
                                    {[
                                        { label: 'HTML Report', fn: () => exportFindingsToHtml(exportData()) },
                                        { label: 'JSON', fn: () => exportFindingsToJson(exportData()) },
                                    ].map(({ label, fn }) => (
                                        <button
                                            key={label}
                                            type="button"
                                            onClick={fn}
                                            style={{
                                                flex: 1, height: 34, borderRadius: 7, cursor: 'pointer',
                                                background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)',
                                                color: 'rgba(255,255,255,0.5)', fontSize: 11, fontWeight: 600,
                                                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5,
                                                transition: 'all 0.12s', fontFamily: 'inherit',
                                            }}
                                            onMouseEnter={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.09)'; e.currentTarget.style.color = 'rgba(255,255,255,0.85)' }}
                                            onMouseLeave={e => { e.currentTarget.style.background = 'rgba(255,255,255,0.05)'; e.currentTarget.style.color = 'rgba(255,255,255,0.5)' }}
                                        >
                                            <Download size={12} />
                                            {label}
                                        </button>
                                    ))}
                                </div>
                                {!hasFindings && (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 6, color: 'rgba(255,255,255,0.2)', fontSize: 10 }}>
                                        <Info size={11} />
                                        No findings to export
                                    </div>
                                )}
                            </div>

                            {/* New scan */}
                            <button
                                type="button"
                                onClick={handleHome}
                                style={css.btn}
                                onMouseEnter={e => e.currentTarget.style.opacity = '0.88'}
                                onMouseLeave={e => e.currentTarget.style.opacity = '1'}
                            >
                                <House size={13} />
                                New Scan
                            </button>
                        </div>
                    )}

                </div>
            </ScrollArea>

            <style>{`
                @keyframes spin { to { transform: rotate(360deg); } }
                @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
            `}</style>
        </div>
    )
}