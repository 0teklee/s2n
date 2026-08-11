"""AI(S2N-Agent) 플러그인 배선 공용 헬퍼.

`s2n scan --ai-mode`(CLI, `cli/runner.py`)와 Chrome extension의
`native_host.py`가 동일한 S2NAgentPlugin 인스턴스화 + 정규 플러그인 병합
로직을 공유하기 위한 모듈이다.

콘솔 출력(rich vs 로그 파일 등 호출자마다 다름)은 여기서 하지 않는다 —
`build_ai_plugins()`는 구조화된 결과(`AiPluginSetup`) 또는 예외만 반환/발생시키고,
실제 메시지 렌더링은 호출자(runner.py, native_host.py)가 각자 방식으로 수행한다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from s2n.s2nscanner.plugins.discovery import discover_plugins


@dataclass
class AiPluginSetup:
    """`build_ai_plugins()` 반환값.

    plugins: None이면 호출자는 기존 discover_plugins() 그대로 사용 (AI off).
             리스트면 [agent_plugin] + 정규 플러그인 인스턴스들.
    on_finding: agent_plugin.on_finding 콜백. AI off면 None.
    agent_plugin_name: "s2n_agent" 등 AGENT_PLUGIN_NAME. 호출자가
             allowed_plugins에 추가할 때 사용. AI off면 None.
    provider_label: 활성화된 provider 이름(또는 "(env)"). AI off면 None.
    availability_warning: provider는 설정됐지만 agent_plugin.is_available()이
             False일 때 채워지는 경고 문자열. 그 외엔 None.
    provider_note: provider가 anthropic/claude/openai/gpt일 때 채워지는
             "API 키 존재만 확인" 안내 문자열. 그 외엔 None.
    """

    plugins: Optional[List[Any]]
    on_finding: Optional[Callable[[Any], None]]
    agent_plugin_name: Optional[str]
    provider_label: Optional[str]
    availability_warning: Optional[str]
    provider_note: Optional[str]


class S2NAgentNotInstalled(Exception):
    """s2nagent 패키지 import 실패 (선택적 [ai] extra 미설치)."""


class AiIntegrationError(Exception):
    """S2NAgentPlugin 생성자가 던진 ValueError(예: provider 미지정)를 감싼 것."""


def build_ai_plugins(
    *,
    ai_mode: str,
    ai_model: Optional[str],
    ai_endpoint: Optional[str],
    ai_provider: Optional[str],
    ai_api_key: Optional[str],
    plugin_list: List[str],
) -> AiPluginSetup:
    """AI 모드 배선 로직 — runner.py 원본과 동작 100% 동일, 출력만 값으로 반환.

    Raises:
        S2NAgentNotInstalled: s2nagent 패키지 import 실패.
        AiIntegrationError: S2NAgentPlugin(...) 생성자의 ValueError(provider 미지정 등).
    """
    if ai_mode == "off":
        return AiPluginSetup(
            plugins=None,
            on_finding=None,
            agent_plugin_name=None,
            provider_label=None,
            availability_warning=None,
            provider_note=None,
        )

    try:
        from s2nagent.plugins.s2n_agent_plugin import S2NAgentPlugin
        from s2nagent.constants import AGENT_PLUGIN_NAME
    except ImportError as exc:
        raise S2NAgentNotInstalled() from exc

    try:
        agent_plugin = S2NAgentPlugin(
            ai_mode=ai_mode,
            ai_model=ai_model,
            ai_endpoint=ai_endpoint,
            ai_provider=ai_provider,
            ai_api_key=ai_api_key,
        )
    except ValueError as exc:
        raise AiIntegrationError(str(exc)) from exc

    on_finding_cb = agent_plugin.on_finding

    # 정규 플러그인 인스턴스 로드 (s2n_agent 제외) — runner.py 원본과 동일 로직
    _regular_ids = set(plugin_list) - {AGENT_PLUGIN_NAME}
    _meta = discover_plugins(include_instances=True)
    _regular_instances = [m["instance"] for m in _meta if m["id"] in _regular_ids]
    # Agent가 항상 첫 번째로 실행되도록 prepend
    all_plugins = [agent_plugin] + _regular_instances

    # ai_provider가 비어 있어도 여기까지 왔다는 건 S2NAGENT_PROVIDER 환경변수로
    # provider가 해석됐다는 뜻이다 — 그렇지 않으면 S2NAgentPlugin() 생성자에서
    # 이미 ValueError가 발생해 위 except 절로 빠진다.
    provider_label = ai_provider or os.environ.get("S2NAGENT_PROVIDER", "(env)")

    availability_warning: Optional[str] = None
    provider_note: Optional[str] = None

    if not agent_plugin.is_available():
        availability_warning = (
            f"⚠️  provider={provider_label} 사용 불가 — API 키 또는 엔드포인트를 "
            "확인하세요 (ANTHROPIC_API_KEY / OPENAI_API_KEY / --ai-api-key / --ai-endpoint). "
            "AI 기능 호출 시 오류가 발생합니다."
        )
    elif provider_label in ("anthropic", "claude", "openai", "gpt"):
        provider_note = (
            "ℹ️  이 provider는 API 키 존재 여부만 확인했습니다 — "
            "실제 호출 성공을 보장하지 않습니다(키 만료/무효 가능)."
        )

    return AiPluginSetup(
        plugins=all_plugins,
        on_finding=on_finding_cb,
        agent_plugin_name=getattr(agent_plugin, "name", AGENT_PLUGIN_NAME),
        provider_label=provider_label,
        availability_warning=availability_warning,
        provider_note=provider_note,
    )
