/**
 * S2N Scanner - AI Mode Settings Panel
 *
 * Options 페이지 "전역 설정" 탭에 표시되는 AI 에이전트 모드 설정 UI.
 * `chrome.storage.session`에 저장되므로 브라우저를 재시작하면 값이 초기화된다
 * (API 키 노출 창을 줄이기 위한 의도된 동작).
 */

import { useEffect, useState } from 'react'
import { DEFAULT_AI_SETTINGS } from '@/domain/aiSettings'
import type { AiMode, AiProvider, AiSettings } from '@/domain/aiSettings'
import { getAiSettings, saveAiSettings } from '@/lib/storage'

const MODE_OPTIONS: { value: AiMode; label: string; description: string }[] = [
    { value: 'off', label: 'Off', description: '비활성화 — AI 에이전트를 사용하지 않습니다.' },
    { value: 'assist', label: 'Assist', description: '권고만 로그로 출력합니다. 자동 실행은 하지 않습니다.' },
    { value: 'smart', label: 'Smart', description: 'AI가 판단한 조치를 자동으로 실행합니다.' },
    { value: 'aggressive', label: 'Aggressive', description: '추가 payload 생성/시도까지 AI가 자동으로 수행합니다.' },
]

const PROVIDER_OPTIONS: { value: AiProvider; label: string }[] = [
    { value: 'ollama', label: 'Ollama' },
    { value: 'huggingface', label: 'HuggingFace' },
    { value: 'anthropic', label: 'Anthropic' },
    { value: 'openai', label: 'OpenAI' },
]

export function AiSettingsPanel() {
    const [settings, setSettings] = useState<AiSettings>(DEFAULT_AI_SETTINGS)
    const [isLoading, setIsLoading] = useState(true)

    useEffect(() => {
        getAiSettings()
            .then(setSettings)
            .catch((error) => console.error('Failed to load AI settings:', error))
            .finally(() => setIsLoading(false))
    }, [])

    const update = (patch: Partial<AiSettings>) => {
        const next = { ...settings, ...patch }
        setSettings(next)
        saveAiSettings(next).catch((error) => console.error('Failed to save AI settings:', error))
    }

    if (isLoading) {
        return (
            <div className="flex items-center justify-center h-64 text-muted-foreground">
                로딩 중...
            </div>
        )
    }

    return (
        <div className="bg-card border rounded-lg p-6 shadow-sm space-y-6">
            <div>
                <h3 className="text-lg font-medium mb-1">AI 에이전트 모드</h3>
                <p className="text-sm text-muted-foreground">
                    스캔 중 발견된 취약점에 대해 AI 에이전트가 얼마나 적극적으로 개입할지 설정합니다.
                </p>
            </div>

            {/* Mode */}
            <div className="space-y-2">
                <label htmlFor="ai-mode-select" className="text-sm font-semibold">모드</label>
                <select
                    id="ai-mode-select"
                    value={settings.mode}
                    onChange={(e) => update({ mode: e.target.value as AiMode })}
                    className="w-full md:w-64 px-3 py-2 border rounded-md bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                >
                    {MODE_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                </select>
                <p className="text-xs text-muted-foreground">
                    {MODE_OPTIONS.find((opt) => opt.value === settings.mode)?.description}
                </p>
            </div>

            {settings.mode !== 'off' && (
                <>
                    {/* Provider */}
                    <div className="space-y-2">
                        <label htmlFor="ai-provider-select" className="text-sm font-semibold">Provider</label>
                        <select
                            id="ai-provider-select"
                            value={settings.provider ?? ''}
                            onChange={(e) => update({ provider: (e.target.value || undefined) as AiProvider | undefined })}
                            className="w-full md:w-64 px-3 py-2 border rounded-md bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                        >
                            <option value="">선택 안 함</option>
                            {PROVIDER_OPTIONS.map((opt) => (
                                <option key={opt.value} value={opt.value}>{opt.label}</option>
                            ))}
                        </select>
                    </div>

                    {/* Ollama: endpoint */}
                    {settings.provider === 'ollama' && (
                        <div className="space-y-2">
                            <label htmlFor="ai-endpoint-input" className="text-sm font-semibold">Endpoint</label>
                            <input
                                id="ai-endpoint-input"
                                type="text"
                                placeholder="http://localhost:11434"
                                value={settings.endpoint ?? ''}
                                onChange={(e) => update({ endpoint: e.target.value })}
                                className="w-full md:w-96 px-3 py-2 border rounded-md bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                            />
                        </div>
                    )}

                    {/* HuggingFace: model repo id */}
                    {settings.provider === 'huggingface' && (
                        <div className="space-y-2">
                            <label htmlFor="ai-model-input" className="text-sm font-semibold">Model repo ID</label>
                            <input
                                id="ai-model-input"
                                type="text"
                                placeholder="org/model-name"
                                value={settings.model ?? ''}
                                onChange={(e) => update({ model: e.target.value })}
                                className="w-full md:w-96 px-3 py-2 border rounded-md bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                            />
                        </div>
                    )}

                    {/* Anthropic / OpenAI: API key + model */}
                    {(settings.provider === 'anthropic' || settings.provider === 'openai') && (
                        <div className="space-y-4">
                            <div className="space-y-2">
                                <label htmlFor="ai-api-key-input" className="text-sm font-semibold">API 키</label>
                                <input
                                    id="ai-api-key-input"
                                    type="password"
                                    placeholder="sk-..."
                                    value={settings.apiKey ?? ''}
                                    onChange={(e) => update({ apiKey: e.target.value })}
                                    className="w-full md:w-96 px-3 py-2 border rounded-md bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                                    autoComplete="off"
                                />
                                <p className="text-xs text-muted-foreground">
                                    이 값은 세션 저장소에만 보관되며, 브라우저를 재시작하면 자동으로 삭제됩니다.
                                </p>
                            </div>
                            <div className="space-y-2">
                                <label htmlFor="ai-model-name-input" className="text-sm font-semibold">모델명</label>
                                <input
                                    id="ai-model-name-input"
                                    type="text"
                                    placeholder={settings.provider === 'anthropic' ? 'claude-sonnet-4-5' : 'gpt-4o'}
                                    value={settings.model ?? ''}
                                    onChange={(e) => update({ model: e.target.value })}
                                    className="w-full md:w-96 px-3 py-2 border rounded-md bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                                />
                            </div>
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
