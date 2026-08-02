"""
UniversalAuthAdapter — 범용 로그인 어댑터
- 어떤 사이트든 로그인 폼을 자동 탐지하고 인증을 시도
- DVWAAdapter와 동일한 duck-type 인터페이스 제공
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse


from s2n.s2nscanner.clients.http_client import HttpClient
from s2n.s2nscanner.constants import (
    AUTH_TIMEOUT,
    AUTH_POST_TIMEOUT,
    FIELD_TYPE_HIDDEN,
    FIELD_TYPE_PASSWORD,
    FIELD_TYPE_SUBMIT,
    FIELD_TYPE_FILE,
    FIELD_TYPE_TEXT,
    FIELD_TYPE_EMAIL,
)
from s2n.s2nscanner.crawler.classifier import (
    ClassifiedForm,
    FormType,
    PageClassifier,
)
from s2n.s2nscanner.logger import get_logger

logger = get_logger("universal_auth")

# 흔한 로그인 경로
_COMMON_LOGIN_PATHS = [
    "/login", "/login.php", "/signin", "/sign-in",
    "/auth/login", "/user/login", "/account/login",
    "/admin/login", "/wp-login.php", "/Login",
]

# 로그인 실패 시 나타나는 에러 메시지 패턴
_LOGIN_ERROR_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"invalid\s+(username|password|credentials|login)",
        r"login\s+failed",
        r"authentication\s+failed",
        r"incorrect\s+(username|password)",
        r"wrong\s+(username|password)",
        r"bad\s+credentials",
        r"access\s+denied",
        r"로그인\s*실패",
        r"인증.*실패",
    ]
]


class UniversalAuthAdapter:
    """범용 로그인 어댑터 — 사이트 구조를 자동 분석해 로그인 수행."""

    def __init__(
        self,
        base_url: str,
        client: Optional[HttpClient] = None,
        login_url: Optional[str] = None,
    ):
        if not base_url:
            raise ValueError("base_url을 지정하세요")
        self.base_url = base_url.rstrip("/")
        self._client = client or HttpClient()
        self._login_url = login_url
        self._classifier = PageClassifier()
        self._authenticated = False
        self.logger = logger

    # ------------------------------------------------------------------
    # Public API (DVWAAdapter 호환 duck-type)
    # ------------------------------------------------------------------

    def ensure_authenticated(
        self, creds: List[Tuple[str, str]], retries: int = 1
    ) -> bool:
        """인증 보장 — 이미 인증됐으면 True, 아니면 로그인 시도.

        모든 내부 예외는 이 메서드에서 최종 처리한다.
        """
        try:
            if self._authenticated and self.is_authenticated():
                return True

            for _ in range(retries + 1):
                login_url = self._discover_login_page()
                if not login_url:
                    self.logger.warning("로그인 페이지를 찾을 수 없습니다.")
                    return False

                login_form = self._analyze_login_form(login_url)
                if not login_form:
                    self.logger.warning("로그인 폼을 찾을 수 없습니다: %s", login_url)
                    return False

                for username, password in creds:
                    if self._attempt_login(login_form, username, password):
                        self._authenticated = True
                        self.logger.info("로그인 성공: %s@%s", username, login_url)
                        return True

                time.sleep(1)

            self.logger.warning("모든 자격증명으로 로그인 실패")
            return False
        except Exception:
            self.logger.error("인증 중 예외 발생: %s", self.base_url, exc_info=True)
            return False

    def is_authenticated(self) -> bool:
        """현재 세션이 인증 상태인지 확인."""
        resp = self._client.get(self.base_url, timeout=AUTH_TIMEOUT)
        text = resp.text or ""
        if re.search(r'(logout|sign.?out|로그아웃)', text, re.I):
            return True
        if re.search(r'type=["\']password["\']', text, re.I):
            return False
        return self._authenticated

    def get_client(self) -> HttpClient:
        """인증된 세션의 HttpClient 반환."""
        return self._client

    def save_cookies(self, path: str) -> None:
        """세션 쿠키를 JSON으로 저장."""
        cookies = self._client.s.cookies.get_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        self.logger.info("쿠키 저장 완료: %s", path)

    def load_cookies(self, path: str) -> None:
        """저장된 쿠키를 세션에 복원."""
        with open(path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        for k, v in cookies.items():
            self._client.s.cookies.set(k, v)
        self.logger.info("쿠키 복원 완료: %s", path)

    # ------------------------------------------------------------------
    # 내부 메서드 — 예외는 상위(ensure_authenticated)로 전파
    # ------------------------------------------------------------------

    def _discover_login_page(self) -> Optional[str]:
        """로그인 페이지 URL 탐색."""
        # 1) 명시적으로 지정된 경우
        if self._login_url:
            return self._login_url

        # 2) 대상 URL 자체가 로그인 페이지인지 확인
        resp = self._client.get(self.base_url, timeout=AUTH_TIMEOUT)
        base_html = resp.text or ""
        page = self._classifier.classify_page(self.base_url, base_html)
        if page.has_login_form:
            return self.base_url

        # 3) 공통 로그인 경로 시도
        for path in _COMMON_LOGIN_PATHS:
            test_url = f"{self.base_url}{path}"
            resp = self._client.get(test_url, timeout=AUTH_TIMEOUT)
            if resp.status_code >= 400:
                continue
            html = resp.text or ""
            page = self._classifier.classify_page(test_url, html)
            if page.has_login_form:
                self.logger.debug("로그인 페이지 발견: %s", test_url)
                return test_url

        # 4) base_url 페이지의 링크에서 login 키워드 찾기 (step 2의 HTML 재사용)
        base_netloc = urlparse(self.base_url).netloc
        for m in re.finditer(r'href=["\']([^"\']*login[^"\']*)["\']', base_html, re.I):
            candidate = urljoin(self.base_url, m.group(1))
            if urlparse(candidate).netloc != base_netloc:
                self.logger.warning("오프사이트 로그인 링크 무시: %s", candidate)
                continue
            r2 = self._client.get(candidate, timeout=AUTH_TIMEOUT)
            page = self._classifier.classify_page(candidate, r2.text or "")
            if page.has_login_form:
                return candidate

        return None

    def _analyze_login_form(self, url: str) -> Optional[ClassifiedForm]:
        """지정 URL에서 LOGIN 타입 폼을 탐지."""
        resp = self._client.get(url, timeout=AUTH_TIMEOUT)
        html = resp.text or ""

        page = self._classifier.classify_page(url, html)
        for cf in page.forms:
            if cf.form_type == FormType.LOGIN:
                return cf
        return None

    def _attempt_login(
        self, form: ClassifiedForm, username: str, password: str
    ) -> bool:
        """로그인 폼에 자격증명을 넣어 POST 시도."""
        data: Dict[str, str] = {}

        # CSRF 토큰 재추출 (폼 페이지를 새로 가져와 최신 토큰 확보)
        fresh_resp = self._client.get(form.url, timeout=AUTH_TIMEOUT)
        fresh_html = fresh_resp.text or ""
        fresh_page = self._classifier.classify_page(form.url, fresh_html)
        for cf in fresh_page.forms:
            if cf.form_type == FormType.LOGIN:
                form = cf
                break

        # hidden 필드 (CSRF 토큰 포함) 먼저 채우기
        for name, fi in form.fields.items():
            if fi.field_type == FIELD_TYPE_HIDDEN:
                data[name] = fi.value

        # username/password 필드 자동 매핑
        username_field = None
        password_field = None
        for name, fi in form.fields.items():
            if fi.field_type == FIELD_TYPE_PASSWORD:
                password_field = name
            elif fi.field_type in (FIELD_TYPE_TEXT, FIELD_TYPE_EMAIL) and not username_field:
                username_field = name

        if not password_field:
            self.logger.warning("password 필드를 찾을 수 없음")
            return False

        # username 필드를 못 찾았으면 폼의 첫 번째 text 계열 필드 사용
        if not username_field:
            for name, fi in form.fields.items():
                if fi.field_type not in (FIELD_TYPE_HIDDEN, FIELD_TYPE_PASSWORD, FIELD_TYPE_SUBMIT, FIELD_TYPE_FILE):
                    username_field = name
                    break

        if username_field:
            data[username_field] = username
        data[password_field] = password

        # submit 버튼 값이 있으면 포함
        for name, fi in form.fields.items():
            if fi.field_type == FIELD_TYPE_SUBMIT and fi.value:
                data[name] = fi.value

        # 로그인 전 쿠키 스냅샷
        pre_cookies = dict(self._client.s.cookies.get_dict())

        # POST 요청
        resp = self._client.post(form.action_url, data=data, timeout=AUTH_POST_TIMEOUT)

        return self._check_login_success(pre_cookies, resp)

    def _check_login_success(
        self, pre_cookies: Dict[str, str], response: Any
    ) -> bool:
        """다중 휴리스틱으로 로그인 성공 여부 판단."""
        text = response.text or ""

        # 1) 에러 메시지 존재 → 실패
        for pattern in _LOGIN_ERROR_PATTERNS:
            if pattern.search(text):
                return False

        # 2) logout/sign-out 링크 존재 → 성공
        if re.search(r'(logout|sign.?out|로그아웃)', text, re.I):
            return True

        # 3) 로그인 폼이 여전히 존재 → 실패
        if re.search(r'type=["\']password["\']', text, re.I):
            return False

        # 4) 쿠키 변화 감지 → 성공 가능성 높음
        post_cookies = dict(self._client.s.cookies.get_dict())
        if post_cookies != pre_cookies and len(post_cookies) > len(pre_cookies):
            return True

        # 5) 리다이렉트가 발생했으면 성공으로 간주
        if hasattr(response, 'history') and response.history:
            return True
        if hasattr(response, 'status_code') and response.status_code in (301, 302, 303):
            return True

        return False
