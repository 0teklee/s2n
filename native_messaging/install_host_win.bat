@echo off
REM =============================================================================
REM S2N Scanner - Windows Native Messaging Host 설치 스크립트
REM =============================================================================
REM Chrome Extension이 로컬 Python 스캐너와 통신하기 위한
REM Native Messaging Host 매니페스트를 레지스트리에 등록합니다.
REM
REM 사용법:
REM   install_host_win.bat <EXTENSION_ID>
REM
REM 예시:
REM   install_host_win.bat abcdefghijklmnopqrstuvwxyz123456
REM =============================================================================

setlocal enabledelayedexpansion

set HOST_NAME=com.s2n.scanner

REM ----- 인자 검증 -----
if "%~1"=="" (
    echo.
    echo [ERROR] 사용법: %~nx0 ^<EXTENSION_ID^>
    echo.
    echo   Extension ID는 Chrome에서 chrome://extensions 페이지에서 확인할 수 있습니다.
    echo   개발자 모드를 활성화한 후 '압축 해제된 확장 프로그램 로드'로 설치하면 ID가 표시됩니다.
    exit /b 1
)

set EXTENSION_ID=%~1

REM ----- 경로 설정 -----
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..

if exist "%SCRIPT_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%SCRIPT_DIR%\.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

set NATIVE_HOST_PATH=%PROJECT_ROOT%\native_host.py
set MANIFEST_TEMPLATE=%SCRIPT_DIR%%HOST_NAME%.json
set TARGET_DIR=%LOCALAPPDATA%\Google\Chrome\User Data\NativeMessagingHosts
set TARGET_MANIFEST=%TARGET_DIR%\%HOST_NAME%.json

echo ======================================================
echo   S2N Native Messaging Host 설치 (Windows)
echo ======================================================
echo.

REM ----- native_host.py 존재 확인 -----
if not exist "%NATIVE_HOST_PATH%" (
    echo [ERROR] native_host.py를 찾을 수 없습니다: %NATIVE_HOST_PATH%
    exit /b 1
)
echo [OK] native_host.py 확인: %NATIVE_HOST_PATH%

REM ----- Python 경로 확인 -----
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [WARNING] python이 PATH에 없습니다. 매니페스트의 path에 python 인터프리터 경로를 직접 설정해야 합니다.
)

REM ----- 대상 디렉토리 생성 -----
if not exist "%TARGET_DIR%" (
    mkdir "%TARGET_DIR%"
)
echo [OK] 매니페스트 디렉토리 확인: %TARGET_DIR%

REM ----- 절대 경로 변환 -----
for %%F in ("%NATIVE_HOST_PATH%") do set ABS_HOST_PATH=%%~fF

REM ----- Windows에서 경로의 백슬래시를 이스케이프 -----
set "ESCAPED_PATH=%ABS_HOST_PATH:\=\\%"

REM ----- 매니페스트 JSON 생성 -----
(
echo {
echo     "name": "%HOST_NAME%",
echo     "description": "S2N Vulnerability Scanner Native Messaging Host",
echo     "path": "%ESCAPED_PATH%",
echo     "type": "stdio",
echo     "allowed_origins": [
echo         "chrome-extension://%EXTENSION_ID%/"
echo     ]
echo }
) > "%TARGET_MANIFEST%"

echo [OK] 매니페스트 설치 완료: %TARGET_MANIFEST%

REM ----- 레지스트리 등록 -----
reg add "HKCU\Software\Google\Chrome\NativeMessagingHosts\%HOST_NAME%" /ve /t REG_SZ /d "%TARGET_MANIFEST%" /f >nul 2>nul
if %errorlevel% equ 0 (
    echo [OK] 레지스트리 등록 완료
) else (
    echo [WARNING] 레지스트리 등록 실패. 관리자 권한으로 다시 실행해 주세요.
)

REM ----- 결과 출력 -----
echo.
echo -- 설치된 매니페스트 내용 --
type "%TARGET_MANIFEST%"
echo.
echo.
echo [SUCCESS] 설치가 완료되었습니다!
echo [INFO] Chrome을 재시작하면 Native Messaging Host가 활성화됩니다.

endlocal
