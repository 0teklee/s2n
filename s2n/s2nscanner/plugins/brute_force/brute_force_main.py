from datetime import datetime
from typing import Dict, List, Optional

# S2N 인터페이스 및 데이터 구조 임포트
from s2n.s2nscanner.interfaces import (
    PluginConfig, PluginContext, PluginResult, PluginStatus,
    Finding, Severity, Confidence, PluginError
)

# 내부 모듈 임포트
from .brute_force_cache import initialize_password_list
from .brute_force_selenium import setup_driver, scan_brute_force_with_selenium
from .brute_force_dvwa_helper import perform_dvwa_login_and_setup
from .brute_force_crawling import url as crawl_url


def _create_brute_force_finding(url: str, user: str, password: str) -> Finding:
    return Finding(
        id="brute-force-001",
        plugin="brute_force",
        severity=Severity.HIGH,
        title="무차별 대입 공격 성공 (Brute Force Success)",
        description=f"사전 공격을 통해 인증에 성공했습니다. ID: '{user}', 비밀번호: '{password}'",
        url=url,
        parameter="password/username",
        payload=f"Username: {user}, Password: {password}",
        confidence=Confidence.FIRM,
        timestamp=datetime.now().isoformat()
    )


class BruteForcePlugin:

    name = "brute_force"
    description = "Checks whether common username and password combinations are accepted"

    # config를 받을 수 있도록 __init__ 메서드 추가
    def __init__(self, config: Optional[PluginConfig] = None):
        self.config = config
        # depth: custom_params에서 가져오거나 기본값 2 사용 (참고용, brute force는 crawler 미사용)
        custom_params = getattr(config, "custom_params", None) or {}
        self.depth = int(custom_params.get("depth", 2))

    def _request_user_confirmation(self, plugin_context) -> bool:
        """
        사용자에게 무차별 대입 공격 실행 여부를 확인합니다.
        Y/N 외의 입력은 반복해서 재질문하여 오타 입력 시 바로 스킵되지 않도록 합니다.
        """
        logger = plugin_context.logger
        scan_config = plugin_context.scan_context.config
        if getattr(scan_config, 'accept_risk', False):
            logger.info("[--accept-risk] Flag activated. Automatically agreeing to the brute force attack warning. / [--accept-risk] 플래그가 활성화되어 무차별 대입 공격 경고에 자동으로 동의합니다.")
            return True

        warning_message = (
            "\n\033[91m[WARNING]\033[0m This plugin performs an actual Brute Force attack.\n"
            "We are not responsible for any legal issues, server load, or account lockouts caused by this.\n"
            "이 플러그인은 실제로 무차별 대입 공격(Brute Force)을 수행합니다.\n"
            "이로 인해 발생하는 법적 문제나 서버 부하, 계정 잠금 등의 문제에 대해 책임지지 않습니다.\n"
            "\nDo you want to proceed? / 그래도 진행하시겠습니까? (Y/N): "
        )

        logger.warning("Waiting for user confirmation... / 사용자 동의 대기 중...")

        try:
            while True:
                response = input(warning_message).strip().lower()
                if response in ("y", "yes"):
                    logger.info("User agreed. Starting scan. / 사용자가 동의하여 스캔을 시작합니다.")
                    return True
                if response in ("n", "no"):
                    logger.warning("User disagreed. Stopping scan. / 사용자가 동의하지 않아 스캔을 중단합니다.")
                    return False

                logger.warning("Please enter Y or N. / Y 또는 N으로 입력해주세요. (예: y, n)")
        except EOFError:
            # 입력 스트림이 닫혀있는 경우 (비대화형 환경 등)
            logger.error("입력을 받을 수 없는 환경입니다. 스캔을 중단합니다.")
            return False

    def run(self, plugin_context: PluginContext) -> PluginResult:
        # S2N 플러그인의 메인 실행 로직.
        logger = plugin_context.logger
        target_url = plugin_context.scan_context.config.target_url
        start_time = datetime.now()
        requests_sent = 0
        findings: List[Finding] = []
        error: Optional[PluginError] = None

        logger.info("--- 🛡️ Brute Force (무차별 대입) 탐지 스캐너 시작 ---")

        # 0. 사용자 동의 확인
        if not self._request_user_confirmation(plugin_context):
            logger.info("사용자가 스캔을 취소했습니다.")
            return PluginResult(
                plugin_name=plugin_context.plugin_name,
                status=PluginStatus.SKIPPED,
                start_time=start_time,
                end_time=datetime.now(),
                duration_seconds=(datetime.now() - start_time).total_seconds(),
                requests_sent=requests_sent,
                findings=[]
            )

        # 1. 대상 URL 유효성 검사
        if not target_url or not target_url.startswith('http'):
            message = "대상 URL이 'http' 또는 'https'로 시작하지 않아 스캔을 중단합니다."
            logger.error(message)
            return PluginResult(
                plugin_name=plugin_context.plugin_name,
                status=PluginStatus.FAILED,
                start_time=start_time,
                end_time=datetime.now(),
                duration_seconds=(datetime.now() - start_time).total_seconds(),
                requests_sent=requests_sent,
                error=PluginError(
                    error_type="ConfigurationError",
                    message=message,
                    timestamp=datetime.now(),
                )
            )

        # 2. 비밀번호 목록 초기화 (로거 전달)
        try:
            PASSWORD_LIST = initialize_password_list(logger)
            if not PASSWORD_LIST:
                raise ValueError("유효한 사전 공격 목록을 확보하지 못했습니다.")
        except Exception as e:
            message = f"비밀번호 목록 초기화 실패: {type(e).__name__} - {e}"
            logger.error(message)
            return PluginResult(
                plugin_name=plugin_context.plugin_name,
                status=PluginStatus.FAILED,
                start_time=start_time,
                end_time=datetime.now(),
                duration_seconds=(datetime.now() - start_time).total_seconds(),
                requests_sent=requests_sent,
                error=PluginError(
                    error_type="PasswordListError",
                    message=message,
                    timestamp=datetime.now(),
                )
            )

        # 3. 비밀번호 목록 일부 출력
        passwords_to_attempt = PASSWORD_LIST[:20]
        logger.info(f"[+] 크롤링된 사전 공격 목록 ({len(PASSWORD_LIST)}개 중 20개 시도)")

        for idx, passwd in enumerate(passwords_to_attempt[:7]):
            logger.debug(f"  {idx + 1}위: {passwd}")
        logger.info(f"비밀번호 출처: {crawl_url}")

        # 4. 스캔 실행
        driver = None
        try:
            driver = setup_driver(logger)

            is_dvwa = "/dvwa/" in target_url.lower()

            if is_dvwa:
                success, _ = perform_dvwa_login_and_setup(driver, target_url, logger)
                if not success:
                    raise Exception("DVWA 초기 설정(관리자 로그인/보안 레벨 설정) 실패")

            success_details: Optional[Dict[str, str]] = scan_brute_force_with_selenium(
                driver, target_url, passwords_to_attempt, is_dvwa, logger
            )

            if success_details:
                user = success_details['user']
                password = success_details['password']
                findings.append(_create_brute_force_finding(target_url, user, password))
                logger.critical(f"🚨🚨 Brute Force 취약점 발견: ID='{user}', PW='{password}'")
            else:
                logger.info("🎉 Brute Force 취약점 징후가 발견되지 않았습니다.")

        except Exception as e:
            message = f"스캔 중 최종 오류 발생: {type(e).__name__} - {e}"
            logger.error(message, exc_info=True)
            error = PluginError(
                error_type=type(e).__name__,
                message=message,
                timestamp=datetime.now(),
            )
        finally:
            if driver:
                driver.quit()

        # 5. 결과 반환 (PluginResult)
        status = PluginStatus.SUCCESS
        if error:
            status = PluginStatus.FAILED if not findings else PluginStatus.PARTIAL

        end_time = datetime.now()
        return PluginResult(
            plugin_name=plugin_context.plugin_name,
            status=status,
            findings=findings,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=(end_time - start_time).total_seconds(),
            requests_sent=requests_sent,
            error=error
        )


# main 함수 사용
def main(config: Optional[PluginConfig] = None):
    return BruteForcePlugin(config)
