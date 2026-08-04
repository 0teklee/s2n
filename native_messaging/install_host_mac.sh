#!/bin/bash
# =============================================================================
# S2N Scanner - Mac Native Messaging Host 설치 스크립트
# =============================================================================
# Chrome Extension이 로컬 Python 스캐너와 통신하기 위한
# Native Messaging Host 매니페스트를 등록합니다.
#
# 사용법:
#   ./install_host_mac.sh <EXTENSION_ID>
#
# 예시:
#   ./install_host_mac.sh abcdefghijklmnopqrstuvwxyz123456
# =============================================================================

set -euo pipefail

# ----- 색상 정의 -----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

HOST_NAME="com.s2n.scanner"

# ----- 인자 검증 -----
if [ $# -lt 1 ]; then
    echo -e "${RED}❌ 사용법: $0 <EXTENSION_ID>${NC}"
    echo ""
    echo "  Extension ID는 Chrome에서 chrome://extensions 페이지에서 확인할 수 있습니다."
    echo "  개발자 모드를 활성화한 후 '압축 해제된 확장 프로그램 로드'로 설치하면 ID가 표시됩니다."
    exit 1
fi

EXTENSION_ID="$1"

# ----- 경로 설정 -----
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
NATIVE_HOST_PATH="$PROJECT_ROOT/native_host.py"
MANIFEST_TEMPLATE="$SCRIPT_DIR/${HOST_NAME}.json"

# Chrome NativeMessagingHosts 디렉토리
TARGET_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
TARGET_MANIFEST="$TARGET_DIR/${HOST_NAME}.json"

echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   S2N Native Messaging Host 설치 (macOS)     ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ----- native_host.py 존재 확인 -----
if [ ! -f "$NATIVE_HOST_PATH" ]; then
    echo -e "${RED}❌ native_host.py를 찾을 수 없습니다: $NATIVE_HOST_PATH${NC}"
    exit 1
fi
echo -e "${GREEN}✅ native_host.py 확인: $NATIVE_HOST_PATH${NC}"

# ----- 실행 권한 부여 -----
chmod +x "$NATIVE_HOST_PATH"
echo -e "${GREEN}✅ 실행 권한 부여 완료${NC}"

# ----- 매니페스트 템플릿 확인 -----
if [ ! -f "$MANIFEST_TEMPLATE" ]; then
    echo -e "${RED}❌ 매니페스트 템플릿을 찾을 수 없습니다: $MANIFEST_TEMPLATE${NC}"
    exit 1
fi

# ----- 대상 디렉토리 생성 -----
mkdir -p "$TARGET_DIR"
echo -e "${GREEN}✅ 매니페스트 디렉토리 확인: $TARGET_DIR${NC}"

# ----- 동적 래퍼(Launcher) 스크립트 생성 -----
LAUNCHER_PATH="$TARGET_DIR/${HOST_NAME}_launcher.sh"
cat <<EOF > "$LAUNCHER_PATH"
#!/bin/bash
# S2N Native Messaging Host Launcher (기기에 맞게 자동 생성됨)

SCRIPT_DIR="$PROJECT_ROOT"
export PYTHONPATH="\$SCRIPT_DIR:\$SCRIPT_DIR/s2n:\$PYTHONPATH"

if [ -f "\$SCRIPT_DIR/.venv/bin/python3" ]; then
    PYTHON_EXE="\$SCRIPT_DIR/.venv/bin/python3"
else
    # Automatically capture the python3 that is active when the script runs
    PYTHON_EXE="$(which python3)"
fi

exec "\$PYTHON_EXE" "\$SCRIPT_DIR/native_host.py" "\$@"
EOF
chmod +x "$LAUNCHER_PATH"
echo -e "${GREEN}✅ 동적 래퍼 생성 완료: $LAUNCHER_PATH${NC}"

# ----- 매니페스트 생성 (플레이스홀더 치환) -----
sed -e "s|__NATIVE_HOST_PATH__|$LAUNCHER_PATH|g" \
    -e "s|__EXTENSION_ID__|$EXTENSION_ID|g" \
    "$MANIFEST_TEMPLATE" > "$TARGET_MANIFEST"

echo -e "${GREEN}✅ 매니페스트 설치 완료: $TARGET_MANIFEST${NC}"

# ----- 결과 출력 -----
echo ""
echo -e "${CYAN}── 설치된 매니페스트 내용 ──${NC}"
cat "$TARGET_MANIFEST"
echo ""
echo ""
echo -e "${GREEN}🎉 설치가 완료되었습니다!${NC}"
echo -e "${YELLOW}ℹ️  Chrome을 재시작하면 Native Messaging Host가 활성화됩니다.${NC}"
