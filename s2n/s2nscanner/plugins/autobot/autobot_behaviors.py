"""
autobot_behaviors.py
BotBehavior 추상 클래스 및 기본 봇 행위 구현체.

각 구현체는 실제로 봇처럼 행동하고 BehaviorResult를 반환한다.
차단 여부 판정은 autobot_detector.py에 위임한다.
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver


# ---------------------------------------------------------------------------
# 데이터 클래스
# ---------------------------------------------------------------------------


@dataclass
class BehaviorResult:
    """단일 봇 행위 실행 결과."""

    behavior_name: str
    was_blocked: bool          # True → 차단 확인 (PASS 기여)
    evidence: str              # 차단/통과 근거 텍스트
    raw_status: Optional[int] = None   # HTTP 상태 코드 (가능하면)
    requests_sent: int = 0    # 이 행위에서 발생한 요청 수


# ---------------------------------------------------------------------------
# 추상 기반 클래스
# ---------------------------------------------------------------------------


class BotBehavior(ABC):
    """봇 행위를 추상화한 인터페이스 (Strategy 패턴)."""

    name: str = ""

    @abstractmethod
    def execute(
        self,
        driver: WebDriver,
        target_url: str,
        logger: logging.Logger,
        target_urls: Optional[List[str]] = None,
    ) -> BehaviorResult:
        """봇 행위를 실행하고 차단 여부를 반환."""


# ---------------------------------------------------------------------------
# 기본 구현체
# ---------------------------------------------------------------------------


class RapidCrawlBehavior(BotBehavior):
    """
    rapid_crawl: sitemap URL 목록을 딜레이 없이 빠르게 순회.
    target_urls가 전달되면 최대 20개를 순회하고, 없으면 target_url 하나만 방문한다.
    """

    name = "rapid_crawl"

    def execute(
        self,
        driver: WebDriver,
        target_url: str,
        logger: logging.Logger,
        target_urls: Optional[List[str]] = None,
    ) -> BehaviorResult:
        from .autobot_detector import is_blocked

        urls_to_visit: List[str] = (target_urls or [])[:20] or [target_url]
        requests_sent = 0
        blocked_count = 0
        evidence_parts: List[str] = []

        logger.info(f"[rapid_crawl] {len(urls_to_visit)}개 URL 빠른 순회 시작")

        for url in urls_to_visit:
            try:
                driver.get(url)
                requests_sent += 1
                blocked, reason = is_blocked(driver)
                if blocked:
                    blocked_count += 1
                    evidence_parts.append(f"BLOCKED at {url}: {reason}")
                    logger.debug(f"[rapid_crawl] 차단 감지: {url} → {reason}")
                else:
                    evidence_parts.append(f"PASS at {url}")
            except Exception as e:
                logger.debug(f"[rapid_crawl] 요청 오류 ({url}): {e}")
                evidence_parts.append(f"ERROR at {url}: {e}")

        was_blocked = blocked_count > 0
        evidence = "; ".join(evidence_parts[:5])  # 증거는 최대 5개만 표시
        if not was_blocked:
            evidence = f"차단 미탐지: {len(urls_to_visit)}개 URL 모두 접근 허용됨. " + evidence

        logger.info(f"[rapid_crawl] 결과: was_blocked={was_blocked}, 요청={requests_sent}")
        return BehaviorResult(
            behavior_name=self.name,
            was_blocked=was_blocked,
            evidence=evidence,
            requests_sent=requests_sent,
        )


class HeadlessSignalBehavior(BotBehavior):
    """
    headless_signal: navigator.webdriver=true 상태 그대로 요청.
    WebDriver 환경에서 기본적으로 navigator.webdriver가 true이므로
    이를 숨기지 않고 그대로 방문해 탐지 여부를 확인한다.
    """

    name = "headless_signal"

    def execute(
        self,
        driver: WebDriver,
        target_url: str,
        logger: logging.Logger,
        target_urls: Optional[List[str]] = None,
    ) -> BehaviorResult:
        from .autobot_detector import is_blocked

        logger.info("[headless_signal] navigator.webdriver=true 상태로 요청")

        try:
            driver.get(target_url)
            webdriver_flag = driver.execute_script("return navigator.webdriver;")
            logger.debug(f"[headless_signal] navigator.webdriver = {webdriver_flag}")

            blocked, reason = is_blocked(driver)
            evidence = (
                f"navigator.webdriver={webdriver_flag}; "
                + (f"차단 감지: {reason}" if blocked else "차단 미탐지")
            )
            return BehaviorResult(
                behavior_name=self.name,
                was_blocked=blocked,
                evidence=evidence,
                requests_sent=1,
            )
        except Exception as e:
            logger.debug(f"[headless_signal] 오류: {e}")
            return BehaviorResult(
                behavior_name=self.name,
                was_blocked=False,
                evidence=f"실행 오류: {e}",
                requests_sent=1,
            )


class NoUserInteractionBehavior(BotBehavior):
    """
    no_user_interaction: 마우스 이동·스크롤 없이 페이지 내 첫 번째 폼을 즉시 Submit.
    폼이 없으면 단순 방문만 기록한다.
    """

    name = "no_user_interaction"

    def execute(
        self,
        driver: WebDriver,
        target_url: str,
        logger: logging.Logger,
        target_urls: Optional[List[str]] = None,
    ) -> BehaviorResult:
        from .autobot_detector import is_blocked

        logger.info("[no_user_interaction] 마우스 이동 없이 폼 즉시 Submit 시도")

        try:
            driver.get(target_url)
            requests_sent = 1

            forms = driver.find_elements(By.TAG_NAME, "form")
            if forms:
                try:
                    forms[0].submit()
                    requests_sent += 1
                    logger.debug("[no_user_interaction] 폼 Submit 완료")
                except Exception as form_err:
                    logger.debug(f"[no_user_interaction] 폼 Submit 오류: {form_err}")

            blocked, reason = is_blocked(driver)
            evidence = "즉시 폼 Submit 후 " + (f"차단 감지: {reason}" if blocked else "차단 미탐지")

            return BehaviorResult(
                behavior_name=self.name,
                was_blocked=blocked,
                evidence=evidence,
                requests_sent=requests_sent,
            )
        except Exception as e:
            logger.debug(f"[no_user_interaction] 오류: {e}")
            return BehaviorResult(
                behavior_name=self.name,
                was_blocked=False,
                evidence=f"실행 오류: {e}",
                requests_sent=1,
            )


class RepetitiveQueryBehavior(BotBehavior):
    """
    repetitive_query: 동일 URL을 짧은 간격(0.1s)으로 10회 재요청.
    """

    name = "repetitive_query"
    REPEAT_COUNT = 10
    DELAY_SECONDS = 0.1

    def execute(
        self,
        driver: WebDriver,
        target_url: str,
        logger: logging.Logger,
        target_urls: Optional[List[str]] = None,
    ) -> BehaviorResult:
        from .autobot_detector import is_blocked

        logger.info(f"[repetitive_query] {self.REPEAT_COUNT}회 반복 요청 시작")

        requests_sent = 0
        blocked_count = 0

        for i in range(self.REPEAT_COUNT):
            try:
                driver.get(target_url)
                requests_sent += 1
                blocked, reason = is_blocked(driver)
                if blocked:
                    blocked_count += 1
                    logger.debug(f"[repetitive_query] {i+1}회차 차단: {reason}")
                    break  # 차단 확인되면 조기 종료
                time.sleep(self.DELAY_SECONDS)
            except Exception as e:
                logger.debug(f"[repetitive_query] {i+1}회차 오류: {e}")
                break

        was_blocked = blocked_count > 0
        evidence = (
            f"{requests_sent}회 반복 요청 후 "
            + (f"차단 감지 ({blocked_count}회)" if was_blocked else "차단 미탐지")
        )

        logger.info(f"[repetitive_query] 결과: was_blocked={was_blocked}, 요청={requests_sent}")
        return BehaviorResult(
            behavior_name=self.name,
            was_blocked=was_blocked,
            evidence=evidence,
            requests_sent=requests_sent,
        )


# ---------------------------------------------------------------------------
# 행위 팩토리
# ---------------------------------------------------------------------------

_BEHAVIOR_REGISTRY: dict = {
    "rapid_crawl": RapidCrawlBehavior,
    "headless_signal": HeadlessSignalBehavior,
    "no_user_interaction": NoUserInteractionBehavior,
    "repetitive_query": RepetitiveQueryBehavior,
}


def load_behaviors(names: List[str]) -> List[BotBehavior]:
    """
    이름 목록을 받아 BotBehavior 인스턴스 목록을 반환한다.
    알 수 없는 이름은 경고 후 스킵.
    """
    behaviors: List[BotBehavior] = []
    for name in names:
        cls = _BEHAVIOR_REGISTRY.get(name)
        if cls is None:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                f"알 수 없는 봇 행위 이름: '{name}'. 스킵합니다. "
                f"사용 가능: {list(_BEHAVIOR_REGISTRY.keys())}"
            )
            continue
        behaviors.append(cls())
    return behaviors
