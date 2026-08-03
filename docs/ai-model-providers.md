# S2N-Agent 멀티 모델 Provider 설계

> 대상 저장소: `s2n-agent` (`s2nagent/client/`), 일부는 `s2n`의 `s2n/s2nscanner/cli/runner.py`
> 관련 문서: `s2n-agent`의 `docs/plugin-plan.md`, `docs/plugins/*.md`, `docs/plugins/integration-gaps.md`
> 작성 시점: 2026-08-03

## 배경

기존 `s2n-agent`는 Ollama(로컬 서버)와 HuggingFace `transformers`(로컬 인프로세스 추론) 두 가지 방식만 지원했고, 이 둘 중 하나를 자동으로 고르는 하드코딩된 폴백(`agent.py`/`s2n_agent_plugin.py`에 각각 중복 구현됨) 외에는 provider를 선택할 방법이 없었다. Claude API, OpenAI GPT API, 그 외 클라우드 AI 서비스를 붙이려면 새 클라이언트 클래스를 추가하는 것 자체는 쉬웠지만(두 클라이언트가 이미 `generate()`/`is_available()`라는 동일한 두 메서드만 구현하고 있었음), 그것을 실제로 선택해서 쓸 수 있는 경로가 전혀 없었다.

이 문서는 그 간극을 메운 설계를 기록한다: 공통 인터페이스를 `Protocol`로 명문화하고, Claude/GPT(및 OpenAI 호환 서비스)용 클라이언트를 추가하고, provider를 명시적으로 고를 수 있는 팩토리와 CLI 옵션을 배선했다.

## 아키텍처

```
s2nagent/client/
  base.py               # LLMClient Protocol — generate()/is_available() 계약
  _util.py              # strip_code_fence() 등 공유 파싱 유틸
  ollama.py             # OllamaClient        — 로컬 Ollama 서버
  huggingface.py        # HuggingFaceClient   — 로컬 transformers 인프로세스 추론
  anthropic_client.py   # AnthropicClient     — Claude (Messages API)
  openai_compatible.py  # OpenAICompatibleClient — GPT + OpenAI 호환 서버/서비스 전부
  factory.py            # build_client(provider, endpoint, model, api_key)
  __init__.py           # 위 전부 재노출
```

```
BaseTask.run(**kwargs)
  -> prompt = self.build_prompt(**kwargs)
  -> response = self.client.generate(prompt, system=self.SYSTEM_PROMPT)   # ← 여기만 provider별로 다름
  -> return self.parse_response(response)
```

`s2nagent/tasks/base.py`의 `BaseTask`(모든 Task A-D와 `plugin_agents/*`가 상속)는 `client.generate(prompt, system=...) -> dict`만 호출한다. 즉 **어떤 provider를 쓰든 Task/Agent 코드는 단 한 줄도 바뀌지 않는다** — 이번 작업도 실제로 `tasks/`, `plugin_agents/`, `plugins/s2n_agent_plugin.py`의 `_task` 호출부는 전혀 건드리지 않았다.

### `LLMClient` 계약 (`client/base.py`)

```python
@runtime_checkable
class LLMClient(Protocol):
    def generate(self, prompt: str, *, system: str | None = None) -> dict[str, Any]: ...
    def is_available(self) -> bool: ...
```

- `generate()`는 항상 **파싱된 JSON dict**를 반환해야 한다. 실패 시(HTTP 오류, JSON 파싱 실패, 인증 누락 등) 예외를 던진다 — 전부 `LLMClientError`의 하위 클래스(`OllamaError`, `HuggingFaceError`, `AnthropicError`, `OpenAICompatibleError`)라서 호출자가 provider를 몰라도 `except LLMClientError`로 일괄 처리할 수 있다.
- `is_available()`는 절대 예외를 던지지 않고 `bool`만 반환해야 한다 — `factory._auto_detect()`가 이 값으로 provider 간 자동 폴백을 결정하기 때문이다.

### 새 provider 클라이언트

| 클라이언트 | 실제 대상 | 인증 | JSON 강제 방식 |
| --- | --- | --- | --- |
| `AnthropicClient` | Claude (Messages API, `api.anthropic.com`) | `x-api-key` 헤더 (`ANTHROPIC_API_KEY` 또는 `api_key` 인자) | Claude에는 Ollama의 `format:"json"` 같은 강제 모드가 없음 → **assistant 턴을 `"{"`로 prefill**해 모델이 객체 내부에서 이어쓰도록 유도(표준 기법). 응답에는 prefill이 포함되지 않으므로 파싱 전에 다시 붙인다. |
| `OpenAICompatibleClient` | OpenAI GPT(`api.openai.com`) **및** `base_url`만 바꾸면 Azure OpenAI/OpenRouter/Groq/Together/Fireworks/vLLM·LM Studio·llama.cpp server 같은 로컬·서드파티 OpenAI 호환 엔드포인트 전부 | `Authorization: Bearer` (`OPENAI_API_KEY` 또는 서드파티용 `S2NAGENT_API_KEY`, 로컬 서버는 생략 가능) | `response_format={"type":"json_object"}` 사용. 이를 모르는 구버전 로컬 서버가 400을 반환하면 **자동으로 그 옵션 없이 한 번 재시도**한다. |

두 클라이언트 모두 공식 `anthropic`/`openai` SDK에 의존하지 않고 `httpx`로 REST 엔드포인트를 직접 호출한다 — 이 패키지의 필수 의존성(`httpx`, `pydantic`, `click`)에 새 패키지를 추가하지 않기 위한 의도적 선택이다(기존 `OllamaClient`도 동일한 스타일). 스트리밍이나 재시도 정책처럼 SDK가 주는 이점이 나중에 필요해지면, `LLMClient` Protocol만 만족시키면 되므로 언제든 해당 클라이언트 내부 구현만 SDK 기반으로 바꿀 수 있다 — 다른 코드는 영향받지 않는다.

`OpenAICompatibleClient` 하나로 "GPT"와 "기타 AI 서비스/로컬 LLM"을 동시에 커버하는 이유: 이 provider들 대부분이 OpenAI Chat Completions 요청/응답 스키마를 표준처럼 채택하고 있어서, provider별로 클래스를 따로 만들 필요 없이 `base_url`(그리고 필요하면 `api_key`)만 바꾸면 되기 때문이다. Anthropic Messages API는 요청/응답 스키마 자체가 달라서(system이 최상위 필드, content가 block 배열 등) 별도 클라이언트가 필요했다.

## Provider 선택 팩토리 (`client/factory.py`)

```python
def build_client(
    provider: str | None = None,   # "auto"(기본) | "ollama" | "huggingface"/"hf" | "anthropic"/"claude" | "openai"/"gpt"/"openai-compatible"
    *, endpoint: str | None = None,  # provider별 의미가 다름 (아래 표 참고)
    model: str | None = None,
    api_key: str | None = None,
) -> LLMClient: ...
```

| provider 값 | `endpoint`의 의미 | `model`의 의미 |
| --- | --- | --- |
| `ollama` | Ollama 서버 URL (기본 `http://localhost:11434`) | Ollama 태그 |
| `huggingface`/`hf` | (미사용) | HuggingFace repo id |
| `anthropic`/`claude` | Anthropic API base URL (기본 공식 엔드포인트) | Claude 모델명 (예: `claude-sonnet-4-5`) |
| `openai`/`gpt`/`openai-compatible` | OpenAI(호환) `base_url` (기본 `https://api.openai.com/v1`; 로컬/서드파티 서버는 여기에 그 서버 주소를 넣음) | 모델명 (GPT 모델명 또는 로컬 서버에 로드된 모델명) |

`provider`가 `None`/`"auto"`이면 **기존 동작을 그대로 보존**한다 — `_auto_detect()`가 Ollama에 먼저 ping해보고 되면 그걸 쓰고, 안 되면 HuggingFace로 폴백한다. 반면 provider를 **명시적으로 지정하면 자동 폴백을 하지 않는다** — 사용자가 의도적으로 고른 provider가 (예: Ollama가 잠깐 죽어서) 조용히 다른 것으로 바뀌면 원인 파악이 어려워지기 때문에, 이 경우는 해당 클라이언트가 직접 에러를 던지게 둔다.

Provider는 함수 인자 대신 `S2NAGENT_PROVIDER` 환경변수로도 지정할 수 있다(인자가 우선).

## 사용법

### `s2n` 스캐너 CLI에서

```bash
# 기존과 동일 (기본값 auto — Ollama 우선, 안 되면 HuggingFace)
s2n scan -u https://target.example --ai-mode smart

# Claude
s2n scan -u https://target.example --ai-mode smart \
  --ai-provider anthropic --ai-model claude-sonnet-4-5 --ai-api-key sk-ant-...
# (또는 환경변수) export ANTHROPIC_API_KEY=sk-ant-...

# OpenAI GPT
s2n scan -u https://target.example --ai-mode smart \
  --ai-provider openai --ai-model gpt-4o-mini
# export OPENAI_API_KEY=sk-...

# 로컬 LLM (Ollama 네이티브 API가 아닌, OpenAI 호환 API를 노출하는 서버 — vLLM/LM Studio 등)
s2n scan -u https://target.example --ai-mode smart \
  --ai-provider openai --ai-endpoint http://localhost:8000/v1 --ai-model my-local-model
```

`--ai-provider`/`--ai-api-key`는 `s2n/s2nscanner/cli/runner.py`의 `scan` 명령에 추가되었고, `S2NAgentPlugin(ai_provider=..., ai_api_key=...)`로 그대로 전달된다.

### `s2n-agent` 독립 CLI에서

```bash
s2n-agent select --url "/search?q=test" --provider anthropic --model claude-sonnet-4-5 --api-key sk-ant-...
s2n-agent plan --plugin xss --provider openai --model gpt-4o-mini
```

### 코드에서 직접

```python
from s2nagent.agent import S2NAgent

agent = S2NAgent(provider="anthropic", model="claude-sonnet-4-5")           # Claude
agent = S2NAgent(provider="openai", model="gpt-4o-mini")                    # GPT
agent = S2NAgent(provider="openai", model="my-local-model",
                  endpoint="http://localhost:8000/v1")                      # OpenAI 호환 로컬 서버
agent = S2NAgent()                                                          # 기존 동작 (auto)
```

`S2NAgentPlugin`(scan_engine 플러그인 생명주기 훅 구현체)도 동일하게 `ai_provider`/`ai_api_key` 파라미터를 받는다.

## 새 provider 추가하는 법

1. `s2nagent/client/<name>.py`에 `generate(prompt, *, system=None) -> dict`와 `is_available() -> bool`을 구현하는 클래스를 작성한다 (`client/base.py`의 `LLMClient` 참고). 에러는 `LLMClientError`를 상속하는 전용 예외로 던진다.
2. `client/factory.py`의 `_ALIASES`에 별칭을 추가하고 `build_client()`에 분기를 추가한다.
3. `client/__init__.py`에 재노출을 추가한다.
4. (선택) `s2nagent/cli.py`의 `--provider` `click.Choice` 목록과 `s2n`의 `runner.py`의 `--ai-provider` `click.Choice` 목록에도 추가한다.

기존 Task(`PluginSelectionTask` 등)나 `plugin_agents/*`, `S2NAgentPlugin`의 훅 로직은 전혀 건드릴 필요가 없다 — 전부 주입받은 `client` 객체의 `generate()`만 호출한다.

## 설계 결정과 트레이드오프

- **SDK 대신 httpx 직접 호출**: 필수 의존성을 늘리지 않기 위한 선택. 다만 이 때문에 재시도/백오프/스트리밍 같은 SDK의 편의 기능은 없다 — 지금은 Ollama 클라이언트도 동일한 수준이라 일관성은 있지만, 프로덕션에서 안정성이 더 필요해지면 재검토 대상이다.
- **Claude의 JSON 강제는 prefill 트릭**: Anthropic Messages API에는 OpenAI의 `response_format`이나 Ollama의 `format:"json"` 같은 진짜 강제 모드가 없다. Assistant 턴을 `"{"`로 시작하게 하는 것은 흔히 쓰이는 완화책이지만 100% 보장은 아니다 — 모델이 그 이후에도 JSON을 깨는 텍스트를 낼 수 있으므로 `AnthropicError`(JSON 파싱 실패)를 호출자가 항상 처리해야 한다(기존 Ollama/HuggingFace 클라이언트도 같은 처리를 요구했으므로 새로운 요구사항은 아니다).
- **`is_available()`의 의미가 provider마다 다르다**: Ollama/OpenAI-호환-로컬서버는 실제로 가벼운 GET을 보내 확인하지만, Anthropic/공식 OpenAI는 **API 키 존재 여부만** 확인하고 실제 네트워크 호출은 하지 않는다 — 가용성 확인마다 과금되는 API 호출을 보내고 싶지 않기 때문이다. 즉 "`is_available() == True`"가 "다음 `generate()` 호출이 반드시 성공한다"를 보장하지는 않는다(키가 만료/무효일 수 있음).
- **명시적 provider는 자동 폴백하지 않는다**: `auto`만 Ollama→HuggingFace 폴백을 한다. Claude/GPT를 명시적으로 골랐는데 실패하면 그 provider의 에러를 그대로 올린다 — 과금되는 provider 사이에서 사용자 모르게 자동으로 바뀌면 안 되기 때문이다.
- **`ScannerConfig.ai_mode/ai_model/ai_endpoint`(s2n `interfaces.py`)는 이번 변경과 무관한 별도 경로다**: 실제 `S2NAgentPlugin` 생성은 `runner.py`의 `scan()` 커맨드 로컬 변수에서 직접 이뤄지고 있어서(레거시 설계), `CLIArguments`/`ScanRequest`를 거쳐 `ScannerConfig`까지 흘러가는 값은 `config_builder.py`가 실제로 소비하지 않는 죽은 필드다. 혼동을 피하기 위해 이번 변경에서도 `ai_provider`/`ai_api_key`를 그 죽은 경로까지 확장하지는 않았다 — 필요해지면 `s2n-agent`의 `docs/plugins/integration-gaps.md`에 기록된 배선 문제들과 함께 정리하는 편이 낫다.

## 테스트

`s2n-agent/tests/test_llm_clients.py`와 `tests/test_client_factory.py`에 `httpx.Client`를 mock으로 대체한 단위 테스트를 추가했다:

- Anthropic: API 키 누락 시 `is_available()`/`generate()` 동작, prefill 재구성 후 JSON 파싱, 코드펜스 방어적 처리, 비-JSON 응답 시 에러.
- OpenAI 호환: 공식 엔드포인트에서 키 누락 시 동작, 로컬 `base_url`에서는 키 없이도 동작, `response_format` 미지원 서버(400)에 대한 자동 재시도.
- 팩토리: 별칭 해석, 알 수 없는 provider에 대한 `ValueError`, 환경변수를 통한 provider 지정, `auto`의 Ollama→HuggingFace 폴백.

기존 145개 테스트(리팩터링 전)에 새 테스트를 더해 총 164개가 전부 통과하며, 이 변경으로 `agent.py`/`plugins/s2n_agent_plugin.py`의 기존 동작(생성자 시그니처, `_build_client` 메서드명 — 테스트가 이 이름으로 patch하므로 유지)은 그대로 보존된다.

## 남은 일 / 향후 개선

- [x] 위 "설계 결정" §의 `is_available()` 비대칭성을 사용자에게 더 명확히 알리는 CLI 메시지 추가. `S2NAgentPlugin.is_available()` 공개 메서드를 추가하고, `runner.py`의 `scan` 커맨드가 AI 모드 활성화 직후 이를 호출해 provider 미가용 시 경고를, cloud provider(anthropic/openai) 사용 시 "키 존재만 확인했음" 안내를 출력하도록 배선했다.
- Claude/GPT의 실제 API 응답을 사용한 통합 스모크 테스트(현재는 전부 mock) — 비용이 드는 만큼 CI 필수 스텝보다는 수동/선택 실행으로.
- `s2nagent/data/generator.py`(학습 데이터 생성)도 동일한 provider 추상화를 쓰도록 정리할지 여부 검토 (현재는 이 문서의 범위 밖).
