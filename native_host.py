#!/usr/bin/env python3
"""
S2N Scanner - Native Messaging Host
====================================
Chrome Extension과 로컬 Python 스캐너 사이의 브릿지 어댑터.
Chrome Native Messaging 프로토콜(4바이트 little-endian length prefix + JSON)을 사용하여
stdin/stdout으로 통신합니다.

사용법:
  이 스크립트는 Chrome이 Native Messaging Host로 직접 실행합니다.
  수동 테스트: echo '{"action":"ping"}' | python native_host.py
"""

import json
import logging
import os
import struct
import sys
import threading
import tempfile
import traceback
import warnings
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

warnings.filterwarnings("ignore", category=UserWarning, module="urllib3")

# s2nscanner 코어 임포트
try:
    from s2n.s2nscanner.scan_engine import Scanner
    from s2n.s2nscanner.plugins.discovery import discover_plugins
    from s2n.s2nscanner.interfaces import (
        ScanConfig,
        ScannerConfig,
        PluginConfig,
        Finding,
        ProgressInfo,
        Severity,
    )
    from s2n.s2nscanner.ai_integration import (
        build_ai_plugins,
        AiPluginSetup,
        S2NAgentNotInstalled,
        AiIntegrationError,
    )
    S2N_AVAILABLE = True
except ImportError:
    S2N_AVAILABLE = False


# ============================================================================
# 전역 상태 및 동기화
# ============================================================================

# stdout 쓰기 동기화를 위한 Lock (멀티스레드 스캔 결과를 안전하게 전송)
write_lock = threading.Lock()

# Chrome의 Native Messaging 통신 채널 보존
REAL_STDIN = sys.stdin.buffer
REAL_STDOUT = sys.stdout.buffer

current_scan_thread: Optional[threading.Thread] = None
current_cancel_event: Optional[threading.Event] = None


def isolate_standard_streams() -> None:
    """Prevent plugin input/print calls from corrupting the native protocol."""
    sys.stdin = open(os.devnull, "r", encoding="utf-8")
    sys.stdout = open(os.devnull, "w", encoding="utf-8")


# ============================================================================
# Chrome Native Messaging 프로토콜 구현
# ============================================================================

def read_message() -> Optional[Dict[str, Any]]:
    """
    stdin에서 Chrome NM 프로토콜 메시지를 읽습니다.
    프로토콜: 4바이트 little-endian unsigned int (메시지 길이) + JSON bytes
    
    Returns:
        파싱된 JSON dict 또는 EOF 시 None
    """
    # 4바이트 길이 헤더 읽기
    raw_length = REAL_STDIN.read(4)
    if not raw_length or len(raw_length) < 4:
        return None

    # little-endian unsigned int로 길이 디코딩
    message_length = struct.unpack('<I', raw_length)[0]

    if message_length == 0:
        return None

    # 메시지 길이 제한 (1MB) - 악의적 입력 방어
    if message_length > 1024 * 1024:
        log_error(f"메시지 크기 초과: {message_length} bytes")
        return None

    # JSON body 읽기
    raw_message = REAL_STDIN.read(message_length)
    if len(raw_message) < message_length:
        log_error(f"불완전한 메시지: expected={message_length}, got={len(raw_message)}")
        return None

    message = json.loads(raw_message.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("Native message must be a JSON object")
    return message


def write_message(message: Dict[str, Any]) -> None:
    """
    stdout으로 Chrome NM 프로토콜 메시지를 씁니다.
    Thread-safe를 보장합니다.
    """
    encoded = json.dumps(message, ensure_ascii=False).encode('utf-8')
    length = len(encoded)

    with write_lock:
        try:
            # 4바이트 길이 헤더 + JSON body 쓰기
            REAL_STDOUT.write(struct.pack('<I', length))
            REAL_STDOUT.write(encoded)
            REAL_STDOUT.flush()
        except Exception as e:
            log_error(f"메시지 전송 실패: {e}")


def encode_message(message: Dict[str, Any]) -> bytes:
    """테스트 유틸리티 용도 인코딩"""
    encoded = json.dumps(message, ensure_ascii=False).encode('utf-8')
    return struct.pack('<I', len(encoded)) + encoded


def decode_message(data: bytes) -> Dict[str, Any]:
    """테스트 유틸리티 용도 디코딩"""
    if len(data) < 4:
        raise ValueError(f"데이터가 너무 짧습니다: {len(data)} bytes")
    
    message_length = struct.unpack('<I', data[:4])[0]
    json_data = data[4:4 + message_length]
    
    if len(json_data) < message_length:
        raise ValueError(f"불완전한 메시지: expected={message_length}, got={len(json_data)}")
    
    return json.loads(json_data.decode('utf-8'))


# ============================================================================
# 로깅 (Chrome이 stderr를 삼키므로 파일로 기록)
# ============================================================================
logging.basicConfig(
    filename=os.path.join(tempfile.gettempdir(), "s2n_native_host.log"),
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

def log_info(msg: str) -> None:
    logging.info(msg)
    sys.stderr.write(f"[S2N-Host INFO] {msg}\n")
    sys.stderr.flush()

def log_error(msg: str) -> None:
    logging.error(msg)
    sys.stderr.write(f"[S2N-Host ERROR] {msg}\n")
    sys.stderr.flush()


# ============================================================================
# S2N Scanner 연동 (스레드 실행)
# ============================================================================

def _run_scan_thread(
    target_url: str,
    selected_plugins: List[str],
    accept_risk: bool,
    cancel_event: threading.Event,
    ai_mode: str = "off",
    ai_model: Optional[str] = None,
    ai_endpoint: Optional[str] = None,
    ai_provider: Optional[str] = None,
    ai_api_key: Optional[str] = None,
) -> None:
    """백그라운드 스레드에서 실제 스캔을 수행하고 결과를 콜백을 통해 스트리밍합니다."""
    log_info(f"스캔 스레드 시작: {target_url}, 플러그인: {selected_plugins}, ai_mode: {ai_mode}")

    try:
        # ScanConfig 구성
        plugin_configs = {p: PluginConfig(enabled=True) for p in selected_plugins}
        scan_config = ScanConfig(
            target_url=target_url,
            scanner_config=ScannerConfig(),
            plugin_configs=plugin_configs,
            accept_risk=accept_risk,
        )

        # AI 모드 배선 (CLI의 runner.py와 동일한 ai_integration.build_ai_plugins() 헬퍼 공유)
        ai_setup: Optional[AiPluginSetup] = None
        try:
            ai_setup = build_ai_plugins(
                ai_mode=ai_mode,
                ai_model=ai_model,
                ai_endpoint=ai_endpoint,
                ai_provider=ai_provider,
                ai_api_key=ai_api_key,
                plugin_list=selected_plugins,
            )
        except S2NAgentNotInstalled:
            log_info("s2nagent 패키지 미설치 — AI 모드 비활성화. `pip install s2n-agent` 실행 필요.")
            ai_setup = None
        except AiIntegrationError as exc:
            log_error(f"AI provider 설정 오류: {exc}")
            write_message({
                "status": "error",
                "action": "scan_failed",
                "error": f"AI provider 설정 오류: {exc}",
            })
            return

        # 콜백: 진행 상황 전송
        def _on_progress(info: ProgressInfo) -> None:
            if cancel_event.is_set():
                return
            write_message({
                "status": "ok",
                "action": "scan_progress",
                "data": {
                    "current": info.current,
                    "total": info.total,
                    "percent": info.percentage,
                    "message": info.message,
                }
            })

        # 콜백: 취약점 발견 시 전송 (AI agent_plugin.on_finding을 먼저 호출한 뒤 기존 스트리밍 유지)
        def _on_finding(finding: Finding) -> None:
            if ai_setup and ai_setup.on_finding:
                try:
                    ai_setup.on_finding(finding)
                except Exception as exc:
                    log_error(f"AI on_finding 콜백 오류: {exc}")

            if cancel_event.is_set():
                return
            write_message({
                "status": "ok",
                "action": "scan_finding",
                "data": {
                    "id": finding.id,
                    "plugin": finding.plugin,
                    "severity": finding.severity.name if hasattr(finding.severity, 'name') else str(finding.severity),
                    "title": finding.title,
                    "description": finding.description,
                    "url": finding.url,
                    "parameter": finding.parameter,
                    "method": finding.method,
                    "evidence": finding.evidence,
                    "cweId": finding.cwe_id,
                    "cvssScore": finding.cvss_score,
                    "references": list(finding.references) if finding.references else [],
                    "timestamp": finding.timestamp.isoformat() if finding.timestamp else None,
                }
            })

        # Scanner 인스턴스화 및 실행 (사전 정의된 선택 플러그인만 허용하도록 주입 가능)
        scanner = Scanner(
            config=scan_config,
            plugins=ai_setup.plugins if ai_setup else None,
            on_progress=_on_progress,
            on_finding=_on_finding,
            cancel_event=cancel_event,
        )

        # Scanner 엔진 내부의 allowed_plugins_order를 덮어씌워서 선택한 플러그인만 실행되도록 제어
        # Scanner.__init__에서 설정한 속성을 수정
        scanner.allowed_plugins = set([p.lower() for p in selected_plugins])
        if ai_setup and ai_setup.agent_plugin_name:
            # AI 모드에서는 s2n_agent도 allowed_plugins에 없으면 discover_plugins() 필터에 걸려
            # 조용히 실행되지 않는다 (native_host.py는 CLI와 달리 plugin_list가 아닌
            # allowed_plugins로 직접 필터링하기 때문) — 반드시 보정 필요.
            scanner.allowed_plugins.add(ai_setup.agent_plugin_name.lower())

        report = scanner.scan()

        if cancel_event.is_set():
            write_message({"status": "ok", "action": "scan_stopped"})
            log_info("스캔 중단 완료 전송")
            return

        # 스캔 완료 결과 요약 계산
        severity_counts = {sev.name: 0 for sev in Severity}
        plugin_counts = {}
        total_findings = 0
        
        for plugin_res in report.plugin_results:
            total_findings += len(plugin_res.findings)
            plugin_counts[plugin_res.plugin_name] = len(plugin_res.findings)
            for f in plugin_res.findings:
                sev_name = f.severity.name if hasattr(f.severity, 'name') else str(f.severity)
                if sev_name in severity_counts:
                    severity_counts[sev_name] += 1
                else:
                    severity_counts[sev_name] = 1

        summary = {
            "totalFindings": total_findings,
            "severityCounts": severity_counts,
            "pluginCounts": plugin_counts,
            "totalUrlsScanned": 0, # 현재 엔진에서 Report summary 미개발 대응
            "durationSeconds": report.duration_seconds,
        }

        # 스캔 완료 이벤트 전송
        write_message({
            "status": "ok",
            "action": "scan_completed",
            "data": {
                "targetUrl": target_url,
                "summary": summary
            }
        })
        log_info("스캔 성공 완료 전송")

    except Exception as e:
        log_error(f"스캔 중 치명적인 예외 발생: {e}\n{traceback.format_exc()}")
        write_message({
            "status": "error",
            "action": "scan_failed",
            "error": str(e)
        })

    finally:
        global current_cancel_event, current_scan_thread
        current_scan_thread = None
        current_cancel_event = None


# ============================================================================
# 액션 핸들러
# ============================================================================

def handle_ping(data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"status": "ok", "action": "pong"}


def handle_get_version(data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not S2N_AVAILABLE:
        return {"status": "error", "action": "version", "error": "s2n scanner module not found"}

    try:
        from importlib import metadata as importlib_metadata
        version = importlib_metadata.version("s2n")
    except Exception:
        version = "unknown"

    return {
        "status": "ok",
        "action": "version",
        "data": {
            "version": version,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        },
    }


def handle_start_scan(data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """스캔을 시작하고 백그라운드 스레드로 넘깁니다."""
    global current_cancel_event, current_scan_thread

    if not S2N_AVAILABLE:
        return {"status": "error", "error": "s2n scanner module not found (sys.path issue?)"}

    if not data or "target_url" not in data:
        return {"status": "error", "error": "Missing 'target_url' in data"}

    target_url = data["target_url"]
    selected_plugins = data.get("plugins", [])
    accept_risk = bool(data.get("accept_risk", False))
    ai_mode = data.get("ai_mode", "off")
    ai_model = data.get("ai_model")
    ai_endpoint = data.get("ai_endpoint")
    ai_provider = data.get("ai_provider")
    ai_api_key = data.get("ai_api_key")

    parsed = urlparse(target_url) if isinstance(target_url, str) else None
    if not parsed or parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {"status": "error", "error": "target_url must be a valid HTTP(S) URL"}
    if not isinstance(selected_plugins, list) or not selected_plugins:
        return {"status": "error", "error": "At least one plugin must be selected"}
    if not all(isinstance(plugin, str) and plugin for plugin in selected_plugins):
        return {"status": "error", "error": "Invalid plugin list"}
    available_plugins = {plugin["id"] for plugin in discover_plugins()}
    unknown_plugins = sorted(set(selected_plugins) - available_plugins)
    if unknown_plugins:
        return {
            "status": "error",
            "error": f"Unknown plugins: {', '.join(unknown_plugins)}",
        }

    if current_scan_thread and current_scan_thread.is_alive():
        return {"status": "error", "error": "Scan already in progress"}

    current_cancel_event = threading.Event()
    thread = threading.Thread(
        target=_run_scan_thread,
        args=(target_url, selected_plugins, accept_risk, current_cancel_event),
        kwargs={
            "ai_mode": ai_mode,
            "ai_model": ai_model,
            "ai_endpoint": ai_endpoint,
            "ai_provider": ai_provider,
            "ai_api_key": ai_api_key,
        },
        daemon=True
    )
    current_scan_thread = thread
    thread.start()

    log_info(f"스캔이 새로운 스레드에서 시작되었습니다. target={target_url}")
    return {"status": "ok", "action": "scan_started", "data": {"target_url": target_url}}


def handle_stop_scan(data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Request cooperative cancellation of the active scan."""
    global current_cancel_event, current_scan_thread
    if not current_scan_thread or not current_scan_thread.is_alive():
        return {"status": "ok", "action": "scan_stopped", "message": "No scan running"}
    
    if current_cancel_event:
        current_cancel_event.set()
    log_info("스캔 중단 요청 수신")
    return {"status": "ok", "action": "scan_stopped"}


def handle_unknown(action: str) -> Dict[str, Any]:
    return {"status": "error", "action": action, "error": f"Unknown action: {action}"}


ACTION_HANDLERS: Dict[str, Callable[[Optional[Dict[str, Any]]], Dict[str, Any]]] = {
    "ping": handle_ping,
    "get_version": handle_get_version,
    "start_scan": handle_start_scan,
    "stop_scan": handle_stop_scan,
}


def dispatch(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    수신 메시지의 action 필드를 기반으로 적절한 핸들러로 라우팅합니다.
    (요청 즉시 응답할 필요가 없는 핸들러는 None을 반환할 수 있음 — Native Host에서는 응답을 쓰는게 원칙이므로 dict 반환)
    """
    action = message.get("action", "")
    data = message.get("data", {})

    handler = ACTION_HANDLERS.get(action)
    if handler:
        return handler(data)  # type: ignore
    
    return handle_unknown(action)


# ============================================================================
# 메인 루프
# ============================================================================

def main() -> None:
    isolate_standard_streams()
    log_info("S2N Native Messaging Host started.")

    while True:
        try:
            message = read_message()

            if message is None:
                log_info("stdin EOF. Shutting down.")
                break

            log_info(f"Received: {json.dumps(message, ensure_ascii=False)}")

            response = dispatch(message)
            if response:
                write_message(response)
                log_info(f"Sent: {json.dumps(response, ensure_ascii=False)}")

        except json.JSONDecodeError as e:
            log_error(f"JSON 파싱 실패: {e}")
            write_message({"status": "error", "error": f"Invalid JSON: {e}"})

        except Exception as e:
            log_error(f"예기치 않은 오류: {e}\n{traceback.format_exc()}")
            write_message({"status": "error", "error": f"Internal error: {e}"})


if __name__ == "__main__":
    main()
