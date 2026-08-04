"""
S2N Native Host - 단위 테스트
==============================
native_host.py의 Chrome NM 프로토콜 메시지 직렬화/역직렬화,
ping/pong 핸들러, 그리고 subprocess를 통한 E2E 핑퐁 테스트.
"""

import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest


# native_host 모듈 경로 설정
ROOT_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT_DIR))

from native_host import encode_message, decode_message, dispatch


# ============================================================================
# 메시지 직렬화/역직렬화 테스트
# ============================================================================

class TestMessageEncoding:
    """Chrome NM 프로토콜 메시지 인코딩/디코딩 테스트"""

    def test_encode_message_basic(self):
        """기본 메시지 인코딩: 4바이트 length prefix + JSON bytes"""
        msg = {"action": "ping"}
        encoded = encode_message(msg)

        # 처음 4바이트는 JSON 길이
        length = struct.unpack('<I', encoded[:4])[0]
        json_body = encoded[4:]

        assert length == len(json_body)
        assert json.loads(json_body.decode('utf-8')) == msg

    def test_encode_message_unicode(self):
        """유니코드 메시지 인코딩 검증"""
        msg = {"action": "ping", "message": "한글 테스트 🔍"}
        encoded = encode_message(msg)
        decoded = decode_message(encoded)
        assert decoded == msg

    def test_encode_message_empty_dict(self):
        """빈 딕셔너리 인코딩 검증"""
        msg = {}
        encoded = encode_message(msg)
        decoded = decode_message(encoded)
        assert decoded == msg

    def test_decode_message_basic(self):
        """기본 메시지 디코딩: bytes → dict"""
        original = {"status": "ok", "action": "pong"}
        encoded = encode_message(original)
        decoded = decode_message(encoded)
        assert decoded == original

    def test_decode_message_too_short(self):
        """데이터가 4바이트 미만인 경우 ValueError 발생"""
        with pytest.raises(ValueError, match="데이터가 너무 짧습니다"):
            decode_message(b"\x00\x01")

    def test_decode_message_incomplete_body(self):
        """JSON body가 불완전한 경우 ValueError 발생"""
        # 길이를 100으로 설정하지만 실제 body는 짧게
        fake_data = struct.pack('<I', 100) + b'{"short"}'
        with pytest.raises(ValueError, match="불완전한 메시지"):
            decode_message(fake_data)

    def test_roundtrip_complex_message(self):
        """복잡한 메시지의 인코딩/디코딩 라운드트립 검증"""
        msg = {
            "action": "scan",
            "data": {
                "target_url": "http://example.com",
                "plugins": ["xss", "sqlinjection"],
                "config": {"depth": 3, "timeout": 30},
            },
        }
        encoded = encode_message(msg)
        decoded = decode_message(encoded)
        assert decoded == msg


# ============================================================================
# 액션 디스패치 테스트
# ============================================================================

class TestDispatch:
    """액션 핸들러 라우팅 테스트"""

    def test_ping_returns_pong(self):
        """ping 액션 → pong 응답"""
        response = dispatch({"action": "ping"})
        assert response["status"] == "ok"
        assert response["action"] == "pong"

    def test_get_version_returns_version(self):
        """get_version 액션 → 버전 정보 응답"""
        response = dispatch({"action": "get_version"})
        assert response["status"] == "ok"
        assert response["action"] == "version"
        assert "data" in response
        assert "python" in response["data"]

    def test_unknown_action_returns_error(self):
        """알 수 없는 액션 → 에러 응답"""
        response = dispatch({"action": "nonexistent"})
        assert response["status"] == "error"
        assert "Unknown action" in response["error"]

    def test_empty_action_returns_error(self):
        """빈 액션 → 에러 응답"""
        response = dispatch({"action": ""})
        assert response["status"] == "error"

    def test_missing_action_returns_error(self):
        """action 필드 누락 → 에러 응답"""
        response = dispatch({})
        assert response["status"] == "error"

    @pytest.mark.parametrize(
        "data,error",
        [
            ({"target_url": "file:///etc/passwd", "plugins": ["xss"]}, "valid HTTP(S)"),
            ({"target_url": "https://example.com", "plugins": []}, "At least one plugin"),
            ({"target_url": "https://example.com", "plugins": [None]}, "Invalid plugin"),
            ({"target_url": "https://example.com", "plugins": ["missing"]}, "Unknown plugins"),
        ],
    )
    def test_start_scan_validates_request(self, data, error):
        response = dispatch({"action": "start_scan", "data": data})

        assert response["status"] == "error"
        assert error in response["error"]


# ============================================================================
# Subprocess E2E 핑퐁 테스트
# ============================================================================

class TestSubprocessPingPong:
    """subprocess로 native_host.py를 실행하여 실제 핑퐁 통신 검증"""

    NATIVE_HOST_PATH = str(ROOT_DIR / "native_host.py")

    def _run_native_host(self, messages: list[dict]) -> list[dict]:
        """
        native_host.py를 subprocess로 실행하고,
        stdin에 메시지들을 보낸 후 stdout에서 응답들을 읽습니다.
        """
        # 입력 바이트 구성
        stdin_data = b""
        for msg in messages:
            stdin_data += encode_message(msg)

        proc = subprocess.run(
            [sys.executable, self.NATIVE_HOST_PATH],
            input=stdin_data,
            capture_output=True,
            timeout=10,
        )

        # stdout에서 응답들 파싱
        responses = []
        buf = proc.stdout
        offset = 0
        while offset < len(buf):
            if offset + 4 > len(buf):
                break
            msg_len = struct.unpack('<I', buf[offset:offset + 4])[0]
            offset += 4
            if offset + msg_len > len(buf):
                break
            json_body = buf[offset:offset + msg_len]
            responses.append(json.loads(json_body.decode('utf-8')))
            offset += msg_len

        return responses

    def test_ping_pong_e2e(self):
        """E2E: ping 메시지 전송 → pong 응답 수신"""
        responses = self._run_native_host([{"action": "ping"}])
        assert len(responses) == 1
        assert responses[0]["status"] == "ok"
        assert responses[0]["action"] == "pong"

    def test_multiple_messages_e2e(self):
        """E2E: 여러 메시지 연속 전송 → 순서대로 응답"""
        messages = [
            {"action": "ping"},
            {"action": "get_version"},
            {"action": "unknown_cmd"},
        ]
        responses = self._run_native_host(messages)
        assert len(responses) == 3
        assert responses[0]["action"] == "pong"
        assert responses[1]["action"] == "version"
        assert responses[2]["status"] == "error"

    def test_unknown_action_e2e(self):
        """E2E: 알 수 없는 액션 → 에러 응답"""
        responses = self._run_native_host([{"action": "does_not_exist"}])
        assert len(responses) == 1
        assert responses[0]["status"] == "error"
        assert "Unknown action" in responses[0]["error"]
