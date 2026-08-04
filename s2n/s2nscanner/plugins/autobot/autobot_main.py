"""
autobot_main.py
AutobotPlugin — 봇 탐지 플러그인 메인 진입점.

실행 흐름:
  1. resolve_target_url()
  2. _request_user_confirmation()  (accept_risk 지원)
  3. setup_driver(headless)
  4. _load_behaviors(names)  → BotBehavior 목록
  5. 각 행위 실행 → 차단되지 않은 행위 수집
  6. driver.quit()  (finally)
  7. block_threshold 초과 시 Finding 생성
  8. PluginResult 반환
"""

import logging
import time
from datetime import datetime
from typing import List, Optional

from s2n.s2nscanner.interfaces import (
    Confidence,
    Finding,
    PluginConfig,
    PluginContext,
    PluginError,
    PluginResult,
    PluginStatus,
    Severity,
)
from s2n.s2nscanner.plugins import helper

from .autobot_behaviors import BehaviorResult, load_behaviors
from .autobot_driver import setup_driver


# ---------------------------------------------------------------------------
# Finding 생성 헬퍼
# ---------------------------------------------------------------------------


def _create_finding(
    target_url: str,
    unblocked_results: List[BehaviorResult],
) -> Finding:
    """차단되지 않은 행위 목록을 기반으로 Finding을 생성한다."""
    behavior_names = ", ".join(r.behavior_name for r in unblocked_results)
    evidence_lines = [f"[{r.behavior_name}] {r.evidence}" for r in unblocked_results]
    evidence = "\n".join(evidence_lines)

    return Finding(
        id="autobot-001",
        plugin="autobot",
        severity=Severity.HIGH,
        confidence=Confidence.FIRM,
        title="Bot Detection Absent",
        description=(
            f"대상 URL({target_url})이 다음 봇 행위를 차단하지 않았습니다: {behavior_names}. "
            "봇 탐지/차단 메커니즘(WAF, Rate Limiting, CAPTCHA 등)이 부재하거나 "
            "우회 가능한 상태입니다."
        ),
        url=target_url,
        evidence=evidence,
        remediation=(
            "1. WAF(Web Application Firewall)를 도입해 자동화 트래픽을 차단하세요.\n"
            "2. Rate Limiting을 적용해 짧은 시간 내 다수 요청을 제한하세요.\n"
            "3. reCAPTCHA, hCAPTCHA 등 CAPTCHA를 민감한 엔드포인트에 추가하세요.\n"
            "4. User-Agent, TLS Fingerprint, navigator.webdriver 등 봇 시그널을 검사하세요."
        ),
    )


# ---------------------------------------------------------------------------
# 메인 플러그인 클래스
# ---------------------------------------------------------------------------


class AutobotPlugin:
    """봇 탐지 플러그인."""

    name = "autobot"
    description = "Checks whether automated browser behavior is detected and blocked"

    DEFAULT_BEHAVIORS = ["rapid_crawl", "headless_signal"]
    DEFAULT_BLOCK_THRESHOLD = 1
    DEFAULT_HEADLESS = True
    DEFAULT_DELAY_MS = 0

    def __init__(self, config: Optional[PluginConfig] = None) -> None:
        self.config = config
        custom = getattr(config, "custom_params", {}) or {}

        self.behavior_names: List[str] = custom.get("behaviors", self.DEFAULT_BEHAVIORS)
        self.block_threshold: int = int(custom.get("block_threshold", self.DEFAULT_BLOCK_THRESHOLD))
        self.headless: bool = bool(custom.get("headless", self.DEFAULT_HEADLESS))
        self.request_delay_ms: int = int(custom.get("request_delay_ms", self.DEFAULT_DELAY_MS))

    # ------------------------------------------------------------------
    # 사용자 동의 확인
    # ------------------------------------------------------------------

    def _request_user_confirmation(self, plugin_context: PluginContext) -> bool:
        """
        봇 행위 스캔 전 사용자 동의를 요청한다.
        accept_risk=True이면 자동 동의.
        """
        logger: logging.Logger = plugin_context.logger
        scan_config = plugin_context.scan_context.config

        if getattr(scan_config, "accept_risk", False):
            logger.info(
                "[--accept-risk] Flag activated. "
                "Automatically agreeing to the bot behavior simulation warning."
            )
            return True

        warning_message = (
            "\n\033[91m[WARNING]\033[0m This plugin simulates bot behavior against the target URL.\n"
            "이 플러그인은 타겟 URL에 대해 봇 행위(크롤링, 자동화 요청 등)를 시뮬레이션합니다.\n"
            "이로 인해 발생하는 법적 문제나 서버 부하에 대해 책임지지 않습니다.\n"
            "\nDo you want to proceed? / 그래도 진행하시겠습니까? (Y/N): "
        )

        logger.warning("Waiting for user confirmation... / 사용자 동의 대기 중...")

        try:
            while True:
                response = input(warning_message).strip().lower()
                if response in ("y", "yes"):
                    logger.info("User agreed. Starting scan.")
                    return True
                if response in ("n", "no"):
                    logger.warning("User disagreed. Stopping scan.")
                    return False
                logger.warning("Please enter Y or N.")
        except EOFError:
            logger.error("입력을 받을 수 없는 환경입니다. 스캔을 중단합니다.")
            return False

    # ------------------------------------------------------------------
    # 메인 run
    # ------------------------------------------------------------------

    def run(self, plugin_context: PluginContext) -> PluginResult:
        logger: logging.Logger = plugin_context.logger
        custom = plugin_context.plugin_config.custom_params or {}
        self.behavior_names = custom.get("behaviors", self.behavior_names)
        self.block_threshold = int(custom.get("block_threshold", self.block_threshold))
        self.headless = bool(custom.get("headless", self.headless))
        self.request_delay_ms = int(custom.get("request_delay_ms", self.request_delay_ms))
        start_time = datetime.now()
        findings: List[Finding] = []
        error: Optional[PluginError] = None
        requests_sent = 0

        logger.info("--- 🤖 Autobot (봇 탐지) 스캐너 시작 ---")

        # ── 1. target_url 확인 ──────────────────────────────────────────
        try:
            target_url = helper.resolve_target_url(self, plugin_context)
        except ValueError as e:
            msg = str(e)
            logger.error(msg)
            return PluginResult(
                plugin_name=plugin_context.plugin_name,
                status=PluginStatus.FAILED,
                start_time=start_time,
                end_time=datetime.now(),
                duration_seconds=(datetime.now() - start_time).total_seconds(),
                requests_sent=0,
                error=PluginError(error_type="ConfigurationError", message=msg),
            )

        # ── 2. 사용자 동의 ──────────────────────────────────────────────
        if not self._request_user_confirmation(plugin_context):
            return PluginResult(
                plugin_name=plugin_context.plugin_name,
                status=PluginStatus.SKIPPED,
                start_time=start_time,
                end_time=datetime.now(),
                duration_seconds=(datetime.now() - start_time).total_seconds(),
                requests_sent=0,
                findings=[],
            )

        # ── 3. SiteMap URL 목록 준비 ────────────────────────────────────
        sitemap = getattr(plugin_context.scan_context, "sitemap", None)
        if sitemap and hasattr(sitemap, "get_urls"):
            target_urls: List[str] = sitemap.get_urls()[:20]
            logger.info(f"SiteMap 사용: {len(target_urls)}개 URL 대상")
        else:
            target_urls = [target_url]

        # ── 4. 행위 로드 ────────────────────────────────────────────────
        behaviors = load_behaviors(self.behavior_names)
        if not behaviors:
            msg = f"실행할 봇 행위가 없습니다. 지정된 이름: {self.behavior_names}"
            logger.error(msg)
            return PluginResult(
                plugin_name=plugin_context.plugin_name,
                status=PluginStatus.FAILED,
                start_time=start_time,
                end_time=datetime.now(),
                duration_seconds=(datetime.now() - start_time).total_seconds(),
                requests_sent=0,
                error=PluginError(error_type="ConfigurationError", message=msg),
            )

        # ── 5. WebDriver 초기화 및 행위 실행 ────────────────────────────
        driver = None
        unblocked_results: List[BehaviorResult] = []
        partial_error: Optional[str] = None

        try:
            driver = setup_driver(logger, headless=self.headless)
        except Exception as e:
            msg = f"WebDriver 초기화 실패: {type(e).__name__} - {e}"
            logger.error(msg, exc_info=True)
            return PluginResult(
                plugin_name=plugin_context.plugin_name,
                status=PluginStatus.FAILED,
                start_time=start_time,
                end_time=datetime.now(),
                duration_seconds=(datetime.now() - start_time).total_seconds(),
                requests_sent=0,
                error=PluginError(error_type="DriverInitError", message=msg),
            )

        try:
            for behavior in behaviors:
                delay_sec = self.request_delay_ms / 1000.0
                if delay_sec > 0:
                    time.sleep(delay_sec)

                logger.info(f"[autobot] 행위 실행: '{behavior.name}'")
                try:
                    result: BehaviorResult = behavior.execute(
                        driver=driver,
                        target_url=target_url,
                        logger=logger,
                        target_urls=target_urls,
                    )
                    requests_sent += result.requests_sent

                    if result.was_blocked:
                        logger.info(f"[autobot] '{behavior.name}' → 차단 확인. {result.evidence}")
                    else:
                        logger.warning(
                            f"[autobot] '{behavior.name}' → 차단 미탐지! {result.evidence}"
                        )
                        unblocked_results.append(result)

                except Exception as e:
                    partial_err_msg = f"'{behavior.name}' 실행 중 오류: {type(e).__name__} - {e}"
                    logger.error(partial_err_msg, exc_info=True)
                    partial_error = partial_err_msg

        finally:
            if driver:
                driver.quit()
                logger.debug("WebDriver 종료 완료.")

        # ── 6. 판정 ─────────────────────────────────────────────────────
        logger.info(
            f"[autobot] 차단 미탐지 행위 수: {len(unblocked_results)} / "
            f"임계값: {self.block_threshold}"
        )

        if len(unblocked_results) >= self.block_threshold:
            finding = _create_finding(target_url, unblocked_results)
            findings.append(finding)
            logger.critical(
                f"🚨 Bot Detection Absent: "
                f"{len(unblocked_results)}개 행위가 차단되지 않음 → Finding 생성"
            )
        else:
            logger.info("✅ 봇 탐지 취약점 없음 (PASS)")

        # ── 7. 상태 결정 ─────────────────────────────────────────────────
        if partial_error and findings:
            status = PluginStatus.PARTIAL
            error = PluginError(error_type="PartialExecutionError", message=partial_error)
        elif partial_error and not findings:
            status = PluginStatus.PARTIAL
            error = PluginError(error_type="PartialExecutionError", message=partial_error)
        else:
            status = PluginStatus.SUCCESS

        end_time = datetime.now()
        return PluginResult(
            plugin_name=plugin_context.plugin_name,
            status=status,
            findings=findings,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=(end_time - start_time).total_seconds(),
            requests_sent=requests_sent,
            error=error,
        )


# ---------------------------------------------------------------------------
# Plugin 팩토리 (discovery.py가 탐색하는 main 함수)
# ---------------------------------------------------------------------------


def main(config: Optional[PluginConfig] = None) -> AutobotPlugin:
    return AutobotPlugin(config)
