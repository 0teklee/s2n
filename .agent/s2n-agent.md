# S2N-Agent 파인튜닝 모델 개발 계획서

> **Claude Code 최적화 버전** — 파일 경로·라인 번호 기반으로 실제 코드베이스와 동기화됨.
> 최종 검증: 2026-04-27

---

## 1. 프로젝트 개요

S2N(v0.3.0)은 플러그인 기반 웹 취약점 스캐너입니다.

```
Crawler → SiteMap 생성 → Plugin 실행 → ScanReport
```

현재 실행 흐름:

| 단계 | 파일 | 핵심 |
|------|------|------|
| CLI 진입 | `s2n/s2nscanner/cli/runner.py` | Click CLI |
| 플러그인 탐색 | `s2n/s2nscanner/plugins/discovery.py` | `discover_plugins()` |
| 스캔 실행 | `s2n/s2nscanner/scan_engine.py` | `Scanner.scan()` |
| 인터페이스 | `s2n/s2nscanner/interfaces.py` | 모든 타입 정의 |

**S2N-Agent 목표**: 기존 결정론적 스캔에 LLM 의사결정 레이어 추가.

```
기존: URL/DOM → 조건 충족 → Plugin 실행
목표: URL/DOM/SiteMap/응답 → S2N-Agent 추론 → Plugin 선택 + Payload 계획 → 결과 해석
```

---

## 2. 현재 플러그인 목록 (12개, 2026-04-27 기준)

```
s2n/s2nscanner/plugins/
  autobot/         brute_force/     csrf/           file_upload/
  jwt/             oscommand/       path_traversal/ react2shell/
  sensitive_files/ soft_brute_force/ sqlinjection/  xss/
```

ATT&CK 매핑 (mitre-attack-plugin-guide.md §2 참조):

| Plugin | TID | Tactic |
|--------|-----|--------|
| xss | T1059.007 | Execution |
| sqlinjection | T1190 | Initial Access |
| oscommand | T1059 | Execution |
| csrf | T1185 | Collection |
| file_upload | T1505.003 | Persistence |
| brute_force / soft_brute_force | T1110 | Credential Access |
| jwt | T1528 | Credential Access |
| autobot | T1190 | Initial Access |
| path_traversal | T1083 | Discovery |
| sensitive_files | T1552.001 | Credential Access |
| react2shell | T1505.003 | Persistence |

---

## 3. S2N-Agent 핵심 원칙

```
모델 = 사고 / 판단 / 계획
플러그인 = 실제 공격 실행
```

모델이 하는 것:
- 어떤 플러그인을 실행할지 결정
- 어떤 payload를 쓸지 결정
- 결과 해석
- 다음 단계 판단

모델이 하지 않는 것:
- HTTP 요청 직접 전송
- 세션/쿠키 관리
- DOM 파싱 직접 처리

---

## 4. 실제 통합 포인트 (코드베이스 검증 완료)

### 4-1. `ScannerConfig`에 `ai_mode` 추가

**파일**: `s2n/s2nscanner/interfaces.py:113`

```python
@dataclass(frozen=True)
class ScannerConfig:
    crawl_depth: int = 2
    max_threads: int = 5
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0
    user_agent: str = "S2N-Scanner/0.1.0"
    follow_redirects: bool = True
    verify_ssl: bool = True
    # 추가 대상:
    ai_mode: str = "off"          # off | assist | smart | aggressive
    ai_model: str = "s2n-agent"   # Ollama 모델명
    ai_endpoint: str = "http://localhost:11434"
```

### 4-2. 플러그인 생명주기 훅 (이미 존재)

**파일**: `s2n/s2nscanner/scan_engine.py:464-512`

```
pre_scan(plugin_context)   → 스캔 전 AI context 주입 가능
run(plugin_context)        → 실제 스캔
post_scan(plugin_context)  → 결과 해석 + 다음 액션 계획
cleanup(plugin_context)    → 정리
```

`S2NAgentPlugin`은 `pre_scan`에서 SiteMap을 읽어 대상 플러그인 목록을 결정하고, `run`은 위임 실행, `post_scan`에서 결과를 해석해 다음 스캔 계획을 반환하는 구조로 설계.

### 4-3. `on_finding` 실시간 콜백 (이미 존재)

**파일**: `s2n/s2nscanner/scan_engine.py:71`

```python
Scanner(
    config=scan_config,
    on_finding=lambda f: agent.analyze_finding(f),  # AI 실시간 피드백
)
```

### 4-4. `ScanContext.session_data` — AI 상태 저장

**파일**: `s2n/s2nscanner/interfaces.py:207`

```python
scan_context.session_data["agent_state"] = {
    "plan": [...],
    "completed_plugins": [...],
    "next_actions": [...],
}
```

### 4-5. `scan_context.sitemap` — 크롤 결과 접근

**파일**: `s2n/s2nscanner/scan_engine.py:174-179`

`smart_crawl()` 결과가 `scan_context.sitemap`에 자동 첨부됨. Agent는 이를 읽어 공격면을 추론.

```python
sitemap = getattr(plugin_context.scan_context, "sitemap", None)
pages = sitemap.pages if sitemap else []
```

### 4-6. `PluginResult.metadata` — AI 결정 기록

**파일**: `s2n/s2nscanner/interfaces.py:291`

```python
PluginResult(
    ...,
    metadata={
        "agent_decision": {"plugin": "xss", "confidence": 91},
        "payloads_tried": 12,
        "reasoning": "input[name=q] detected — XSS likely",
    }
)
```

### 4-7. CLI 플러그인 목록 — 동적 탐색 (이미 업데이트됨)

**파일**: `s2n/s2nscanner/cli/runner.py:153-154`

```python
# 현재 코드 (하드코딩 아님 — discover_plugins() 동적 방식)
if run_all or not plugin_list:
    plugin_list = [p["id"] for p in discover_plugins()]
```

새 플러그인 추가 시 `runner.py` 수정 불필요. `__init__.py`에 `Plugin` export만 있으면 자동 포함됨.

---

## 5. 모델 학습 태스크 정의

### Task A. Plugin Selection

```json
{
  "input": {
    "url": "/search?q=test",
    "dom": "<input name='q' type='text'>",
    "sitemap_summary": "3 forms, 1 file input, 0 login forms"
  },
  "output": {"plugin": "xss", "confidence": 91}
}
```

### Task B. Payload Planning

```json
{
  "input": {"plugin": "xss", "parameter": "q", "context": "html_attribute"},
  "output": {
    "payloads": ["<svg/onload=alert(1)>", "\"><img src=x onerror=alert(1)>"]
  }
}
```

### Task C. False Positive Filter

```json
{
  "input": {
    "finding": "Possible SQLi",
    "evidence": "error: near syntax",
    "response_body": "Welcome to our site"
  },
  "output": {"verdict": "likely_false_positive", "reason": "error not in response"}
}
```

### Task D. Multi-step Planner

```json
{
  "input": {
    "completed": ["xss", "csrf"],
    "findings": [{"plugin": "jwt", "severity": "HIGH"}],
    "sitemap": "admin route /admin/panel discovered"
  },
  "output": {
    "next_action": "run path_traversal",
    "reason": "admin route suggests privileged file access possible"
  }
}
```

---

## 6. 데이터셋 구성

| 유형 | 수량 |
|------|------|
| XSS | 800 |
| SQLi | 800 |
| Upload / react2shell | 400 |
| Auth/JWT | 500 |
| IDOR / Path Traversal | 500 |
| False Positive 사례 | 1000 |
| **합계** | **4000+** |

데이터 소스: DVWA, Juice Shop, WebGoat, 직접 생성 샘플

---

## 7. 권장 Base 모델

| 용도 | 모델 | 이유 |
|------|------|------|
| 실전 | Qwen2.5-Coder 7B | HTML/JS/JSON 강함, Tool calling, M1 가능 |
| 실험 | Qwen 3B | 빠른 반복 |
| 보고서 보조 | Gemma 계열 | 자연어 출력 품질 |

---

## 8. 파인튜닝 방식

- **방법**: LoRA / QLoRA
- **도구**: MLX-LM (Apple Silicon), PEFT, Transformers
- **운영**: 낮 = 개발/추론, 밤 = 파인튜닝

권장 모델 크기: 3B (빠름), 7B (최적). 14B 이상 로컬 학습 비권장.

---

## 9. Ollama 배포

```dockerfile
# Modelfile
FROM qwen2.5-coder:7b
ADAPTER ./s2n-lora
SYSTEM """
You are S2N-Agent. Return strict JSON only.
You optimize web vulnerability scanning workflows.
Select plugins, plan payloads, interpret results, plan next actions.
"""
```

```bash
ollama create s2n-agent -f Modelfile
```

---

## 10. S2N 통합 구조 (확정된 훅 기반)

```
Scanner.scan()
  ↓ smart_crawl() → scan_context.sitemap 자동 첨부
  ↓ for plugin in discovered_plugins:
      ↓ plugin.pre_scan(ctx)   ← AI: sitemap 분석, 실행 여부 결정
      ↓ plugin.run(ctx)        ← 실제 스캔
      ↓ plugin.post_scan(ctx)  ← AI: 결과 해석, 다음 액션 계획
      ↓ plugin.cleanup(ctx)
  ↓ ScanReport 반환
```

`on_finding` 콜백 (`scan_engine.py:71`) — Finding 단위 실시간 AI 피드백 가능.

---

## 11. CLI UX 설계

```bash
s2n scan -u https://target.com --ai-mode off        # 기본 (현재)
s2n scan -u https://target.com --ai-mode assist     # AI 권고만 (실행은 기존)
s2n scan -u https://target.com --ai-mode smart      # AI가 플러그인 선택
s2n scan -u https://target.com --ai-mode aggressive # AI 멀티스텝 계획
```

`--ai-mode` 옵션 추가 위치: `s2n/s2nscanner/cli/runner.py` scan 명령어 (`@click.option` 블록)

---

## 12. 평가 지표

| 항목 | 목표 |
|------|------|
| Plugin 선택 정확도 | 85%+ |
| False Positive 감소 | 30%+ |
| 평균 탐색 시간 단축 | 20%+ |
| Hidden Endpoint 탐지율 | 증가 |

---

## 13. 개발 일정

| 주차 | 작업 |
|------|------|
| Week 1 | `ScannerConfig.ai_mode` 필드 추가 / 데이터 포맷 설계 / 학습 파이프라인 구축 |
| Week 2 | 3B 모델 1차 학습 / `S2NAgentPlugin` 스켈레톤 구현 (pre_scan/post_scan 훅 활용) |
| Week 3 | Payload planner 추가 / `on_finding` 실시간 피드백 연결 |
| Week 4 | Ollama 배포 / CLI `--ai-mode` 옵션 공개 |

---

## 14. Claude Code Skill 프롬프트 예시

### 구조 설계

```
s2n/s2nscanner/interfaces.py:113 ScannerConfig에 ai_mode, ai_model, ai_endpoint 필드 추가.
s2n/s2nscanner/scan_engine.py:71 Scanner.__init__에 ai_agent 파라미터 추가.
pre_scan/post_scan 훅(scan_engine.py:466-512)을 통해 Ollama 호출 구조 설계해줘.
```

### 데이터 생성

```
XSS plugin selection 학습용 JSONL 500개 생성.
입력: {url, dom, sitemap_summary}, 출력: {plugin, confidence}
interfaces.py:246 Finding 구조 참고.
```

### 코드 작성

```
s2n/s2nscanner/interfaces.py:113 ScannerConfig에 ai_mode: str = "off" 필드 추가 PR 수준 코드 작성.
s2n/s2nscanner/cli/runner.py scan 명령에 --ai-mode Click 옵션 추가.
```

### 평가

```
Task C (False Positive Filter) 정확도 측정 benchmark 코드 작성.
interfaces.py:246 Finding, interfaces.py:280 PluginResult 기반.
```

---

## 15. 핵심 성공 전략

```
LLM이 스캐너를 대체하면 실패한다.
LLM이 스캐너를 지휘하면 성공한다.
```

최종 권장 실행 순서:
1. Mac mini M1 → Qwen 3B 실험
2. Qwen 7B 실전 전환
3. LoRA nightly tuning
4. Ollama 배포
5. S2N AI Mode 통합
