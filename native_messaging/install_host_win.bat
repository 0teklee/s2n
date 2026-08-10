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

REM ----- Extension ID 형식 검증 -----
echo %EXTENSION_ID%| findstr /r /x "[a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p][a-p]" >nul
if errorlevel 1 (
    echo [ERROR] 잘못된 EXTENSION_ID 형식입니다: %EXTENSION_ID%
    echo   Chrome Extension ID는 소문자^(a-p^) 32자여야 합니다.
    exit /b 1
)

REM ----- 경로 설정 -----
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..

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

REM ----- 대상 디렉토리 생성 -----
if not exist "%TARGET_DIR%" (
    mkdir "%TARGET_DIR%"
)
echo [OK] 매니페스트 디렉토리 확인: %TARGET_DIR%

REM ----- 절대 경로 변환 (프로젝트 루트) -----
for %%F in ("%PROJECT_ROOT%") do set ABS_PROJECT_ROOT=%%~fF

REM ----- 런처(Launcher) 배치 스크립트 생성 -----
REM Chrome은 매니페스트 path에 지정된 파일을 직접 실행하며 .py 파일은
REM 그 방식으로 실행할 수 없으므로, 실행 시점에 Python 인터프리터를
REM 탐지해 native_host.py를 구동하는 래퍼를 생성한다 (macOS 쪽 launcher와 동일한 방식).
set LAUNCHER_PATH=%TARGET_DIR%\%HOST_NAME%_launcher.bat
(
echo @echo off
echo REM S2N Native Messaging Host Launcher ^(기기에 맞게 자동 생성됨^)
echo set "PROJECT_ROOT=%ABS_PROJECT_ROOT%"
echo set "PYTHONPATH=%%PROJECT_ROOT%%;%%PROJECT_ROOT%%\s2n;%%PYTHONPATH%%"
echo if exist "%%PROJECT_ROOT%%\.venv\Scripts\python.exe" ^(
echo     set "PYTHON_EXE=%%PROJECT_ROOT%%\.venv\Scripts\python.exe"
echo ^) else ^(
echo     set "PYTHON_EXE=python"
echo ^)
echo "%%PYTHON_EXE%%" "%%PROJECT_ROOT%%\native_host.py" %%*
) > "%LAUNCHER_PATH%"
echo [OK] 런처 생성 완료: %LAUNCHER_PATH%

REM ----- Python 경로 확인 (정보 제공용) -----
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [WARNING] python이 PATH에 없습니다. PATH에 python.exe를 추가하거나 프로젝트에 .venv를 생성해 주세요.
)

REM ----- 절대 경로 변환 (런처) -----
for %%F in ("%LAUNCHER_PATH%") do set ABS_HOST_PATH=%%~fF

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
set REGISTRY_OK=1
reg add "HKCU\Software\Google\Chrome\NativeMessagingHosts\%HOST_NAME%" /ve /t REG_SZ /d "%TARGET_MANIFEST%" /f >nul 2>nul
if %errorlevel% equ 0 (
    echo [OK] 레지스트리 등록 완료
) else (
    set REGISTRY_OK=0
    echo [WARNING] 레지스트리 등록 실패. 관리자 권한으로 다시 실행해 주세요.
)

REM ----- 결과 출력 -----
echo.
echo -- 설치된 매니페스트 내용 --
type "%TARGET_MANIFEST%"
echo.
echo.
if "%REGISTRY_OK%"=="1" (
    echo [SUCCESS] 설치가 완료되었습니다!
    echo [INFO] Chrome을 재시작하면 Native Messaging Host가 활성화됩니다.
) else (
    echo [FAILED] 레지스트리 등록에 실패해 설치가 완료되지 않았습니다.
    echo [INFO] 관리자 권한으로 스크립트를 다시 실행한 뒤 다시 시도해 주세요.
    exit /b 1
)

endlocal
