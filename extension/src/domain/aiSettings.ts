/**
 * S2N Scanner - AI mode settings (domain types + defaults)
 *
 * This module must not import `chrome` or React — it is pure data so it can
 * be unit tested and reused by both the background worker and the UI.
 */

/** AI 모드 — CLI `--ai-mode`와 동일한 값 집합 */
export type AiMode = 'off' | 'assist' | 'smart' | 'aggressive'

/** AI provider — CLI `--ai-provider`와 동일하게 "auto"는 없다 (명시 필수) */
export type AiProvider = 'ollama' | 'huggingface' | 'anthropic' | 'openai'

/** AI 모드 설정 — Options 전역 설정 탭 + Popup 토글에서 공유하는 상태 */
export interface AiSettings {
    mode: AiMode
    provider?: AiProvider
    model?: string
    endpoint?: string
    apiKey?: string
}

/** 초기/기본 AI 설정 — AI 비활성화 */
export const DEFAULT_AI_SETTINGS: AiSettings = { mode: 'off' }
