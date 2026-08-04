from __future__ import annotations
import click
from datetime import datetime
import sys
import platform
import json
import subprocess
from pathlib import Path

from s2n.s2nscanner.interfaces import (
    CLIArguments,
    ScanContext,
    ProgressInfo,
    PluginStatus,
    ValidationError,
)
from s2n.s2nscanner.cli.mapper import cliargs_to_scanrequest
from s2n.s2nscanner.cli.config_builder import build_scan_config
from s2n.s2nscanner.auth.dvwa_adapter import DVWAAdapter
from s2n.s2nscanner.auth.universal_adapter import UniversalAuthAdapter
from s2n.s2nscanner.scan_engine import Scanner
from s2n.s2nscanner.report import output_report, OutputFormat
from s2n.s2nscanner.logger import init_logger
from s2n.s2nscanner.plugins.discovery import discover_plugins

import os
from rich.console import Console
from rich.table import Table
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich import box

# Docker/CI 환경에서도 rich가 작동하도록 설정
# force_terminal=True: TTY가 없어도 터미널 기능 활성화
# force_interactive=False: CI 환경에서 인터랙티브 기능 비활성화
is_ci = os.getenv("CI", "").lower() in ("true", "1", "yes")
console = Console(force_terminal=True, force_interactive=not is_ci)


# S2N 전용 Click Group (Help 출력 시 로고와 예시를 항상 포함하기 위함)
class S2NGroup(click.Group):
    def format_help(self, ctx, formatter):
        ascii_logo = r"""
    (`-').->        <-. (`-')_
    ( OO)_             \( OO) )
    (_)--\_)  .----. ,--./ ,--/
    /    _ / \_,-.  ||   \ |  |
    \_..`--.    .' .'|  . '|  |)
    .-._)   \ .'  /_ |  |\    |
    \       /|      ||  | \   |
    `-----' `------'`--'  `--'

    S2N Web Vulnerability Scanner CLI
    """
        colored_logo = click.style(ascii_logo, fg="blue", bold=True)
        click.echo(colored_logo)
        click.echo("🔍 Welcome to S2N Scanner! Your plugin-based web vulnerability scanner.\n")
        
        click.echo(click.style("[Usage Examples]", fg="cyan", bold=True, underline=True))
        click.echo("  s2n scan -u http://example.com                 # Scan with all default plugins")
        click.echo("  s2n scan -u http://example.com --all           # Explicitly run all plugins")
        click.echo("  s2n scan -u http://example.com -p jwt -p autobot # Run jwt and autobot plugins only")
        click.echo("  s2n scan -u http://example.com -p brute_force -y # Run brute force, accepting risks")
        click.echo("  s2n scan -u http://example.com --output-format html -o result.html # Save HTML report")
        click.echo("  s2n list-plugins                               # List all available plugins")
        click.echo("  s2n inspect-plugin xss                         # View details of a specific plugin")
        click.echo("  s2n --help                                    # Show this help message\n")
        
        # 기본 Click 도움말 출력
        super().format_help(ctx, formatter)


# CLI Root
@click.group(cls=S2NGroup)
def cli():
    # S2NGroup에서 Help 처리를 하므로 여기서는 pass
    pass


# scan 명령어
@cli.command("scan")
@click.option("-u", "--url", required=True, help="""Target URL to scan\n스캔 대상 URL""")
@click.option(
    "-p",
    "--plugin",
    multiple=True,
    help="Plugins to use (can be used multiple times). If omitted or if --all is used, all discovered plugins will run. "
         "Run 's2n list-plugins' to see available plugins.\n"
         "사용할 플러그인 이름. 생략하거나 --all 사용 시 자동 탐지된 전체 플러그인이 실행됩니다.",
)
@click.option(
    "--all", "run_all", is_flag=True, help="Run all default plugins / 모든 기본 플러그인 실행"
)
@click.option(
    "-a",
    "--auth",
    help="Authentication type \n인증 타입 \n\n(NONE, BASIC, BEARER, DVWA, etc.)",
)
@click.option(
    "-y", "--accept-risk", is_flag=True, help="Automatically bypass brute force warning / 무차별 대입 공격 경고 자동 동의"
)
@click.option("--username", help="Username for authentication \n인증용 사용자명")
@click.option("--password", help="Password for authentication \n인증용 비밀번호")
@click.option(
    "-o", "--output", help="Output file path (e.g., result.json) \n 결과 출력 파일 경로"
)
@click.option(
    "--output-format",
    type=click.Choice([fmt.value for fmt in OutputFormat], case_sensitive=False),
    default=OutputFormat.JSON.value,
    show_default=True,
    help="Output format / 결과 출력 형식 (JSON, HTML, CSV, CONSOLE, MULTI)",
)
@click.option("--crawler-depth", default=2, help="Crawler depth / 크롤러 탐색 깊이")
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging / 상세 로그 출력")
@click.option("--log-file", help="Log file path / 로그 파일 경로")
@click.option("--login-url", default=None, help="Login page URL for auto auth / 자동 인증 시 로그인 페이지 URL")
@click.option(
    "--ai-mode",
    type=click.Choice(["off", "assist", "smart", "aggressive"], case_sensitive=False),
    default="off",
    show_default=True,
    help="AI agent mode / AI 에이전트 모드 (off|assist|smart|aggressive)",
)
@click.option(
    "--ai-model",
    default="s2n-agent",
    show_default=True,
    help="Ollama model name or HuggingFace repo ID / 사용할 AI 모델",
)
@click.option(
    "--ai-endpoint",
    default="http://localhost:11434",
    show_default=True,
    help="Ollama server endpoint / Anthropic base URL / OpenAI(-compatible) base_url "
    "— meaning depends on --ai-provider / Ollama 서버 주소 (provider에 따라 의미가 다름)",
)
@click.option(
    "--ai-provider",
    type=click.Choice(["ollama", "huggingface", "anthropic", "claude", "openai", "gpt"], case_sensitive=False),
    default=None,
    help="LLM provider / AI 공급자 — --ai-mode가 off가 아니면 반드시 지정해야 함 "
    "(자동으로 Ollama/HuggingFace가 선택되지 않음). "
    "s2n-agent의 S2NAGENT_PROVIDER 환경변수로도 지정 가능",
)
@click.option(
    "--ai-api-key",
    default=None,
    help="API key for anthropic/openai providers / Claude·GPT 등 API 기반 provider용 API 키 "
    "(생략 시 ANTHROPIC_API_KEY/OPENAI_API_KEY 환경변수 사용)",
)
def scan(
    url,
    plugin,
    run_all,
    auth,
    accept_risk,
    username,
    password,
    output,
    output_format,
    crawler_depth,
    verbose,
    log_file,
    login_url,
    ai_mode,
    ai_model,
    ai_endpoint,
    ai_provider,
    ai_api_key,
):
    """Run a vulnerability scan / 취약점 스캔 실행"""
    logger = init_logger(verbose, log_file)
    logger.info("Starting scan for %s", url)

    # HTML/CSV 포맷 선택 시 출력 경로 미지정이면 자동 생성
    if not output and output_format and output_format.lower() in ("html", "csv"):
        ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        ext = output_format.lower()
        output = f"s2n_report_{ts}.{ext}"
        console.print(f"[cyan]ℹ️  --output 미지정 — 자동 저장: {output}[/cyan]")

    # --all 플래그 처리 및 --plugin 생략 처리 (discover_plugins() 기반 동적 목록)
    plugin_list = list(plugin)
    if run_all or not plugin_list:
        plugin_list = [p["id"] for p in discover_plugins()]
        if not plugin_list:
            console.print("[red]Error: No plugins discovered. Check your installation.[/red]")
            sys.exit(1)
    else:
        available_plugins = {item["id"] for item in discover_plugins()}
        unknown_plugins = sorted(set(plugin_list) - available_plugins)
        if unknown_plugins:
            raise click.ClickException(
                f"Unknown plugins: {', '.join(unknown_plugins)}. "
                "Run 's2n list-plugins' to see available plugins."
            )

    # AI 모드 활성화 시: s2n_agent를 plugin_list 맨 앞에 추가
    # → build_scan_config의 plugin_configs에 포함되어 scan_engine allowed_plugins 필터 통과
    if ai_mode != "off":
        try:
            from s2nagent.constants import AGENT_PLUGIN_NAME
            if AGENT_PLUGIN_NAME not in plugin_list:
                plugin_list = [AGENT_PLUGIN_NAME] + plugin_list
        except ImportError:
            pass  # s2nagent 미설치 시 무시

    # CLIArguments 구성
    args = CLIArguments(
        url=url,
        plugin=plugin_list,
        auth=auth,
        username=username,
        password=password,
        output=output,
        output_format=output_format,
        depth=crawler_depth,
        verbose=verbose,
        log_file=log_file,
        accept_risk=accept_risk,
        ai_mode=ai_mode,
        ai_model=ai_model,
        ai_endpoint=ai_endpoint,
    )

    try:
        request = cliargs_to_scanrequest(args)
        config = build_scan_config(request, username=username, password=password)
    except ValidationError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        sys.exit(1)

    # 인증 처리 (DVWA)
    http_client = None
    auth_adapter = None
    auth_credentials = None

    if (auth or "").lower() == "dvwa":
        logger.info("DVWA authentication requested.")
        auth_adapter = DVWAAdapter(base_url=request.target_url)
        username = username or "admin"
        password = password or "password"

        auth_credentials = [(username, password)]

        if auth_adapter.ensure_authenticated(auth_credentials):
            http_client = auth_adapter.get_client()
            logger.info("DVWA 로그인 완료")
        else:
            logger.warning("DVWA 로그인 실패 - 인증 없이 진행")

    elif (auth or "").lower() == "auto":
        logger.info("Universal (auto) authentication requested.")
        auth_adapter = UniversalAuthAdapter(
            base_url=request.target_url,
            login_url=login_url,
        )

        if username:
            auth_credentials = [(username, password or "")]
            if auth_adapter.ensure_authenticated(auth_credentials):
                http_client = auth_adapter.get_client()
                logger.info("자동 인증 로그인 완료")
            else:
                logger.warning("자동 인증 로그인 실패 - 인증 없이 진행")
        else:
            logger.warning("--username 미지정 — 인증 없이 진행")

    # ScanContext 생성
    scan_ctx = ScanContext(
        scan_id=f"scan-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        start_time=datetime.utcnow(),
        config=config,
        http_client=http_client,
        crawler=None,
    )

    # 진행률 UI 준비
    progress = Progress(
        SpinnerColumn(style="bold cyan"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=None, complete_style="green", finished_style="magenta"),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=True,
        auto_refresh=False,
    )
    progress_task = progress.add_task("🧭 스캔 준비 중", total=1)

    def on_progress(info: ProgressInfo):
        total = info.total or 1
        progress.update(
            progress_task,
            total=total,
            completed=info.current,
            description=info.message,
            refresh=True,
        )

    # AI 모드 활성화 시 S2NAgentPlugin 주입 + 정규 플러그인 인스턴스와 합산
    # scan_engine allowed_plugins 필터를 통과하려면 plugins= 리스트에
    # agent_plugin AND 정규 플러그인 인스턴스를 함께 넘겨야 한다.
    all_plugins = None   # None → scan_engine이 자체 discover_plugins() 수행
    on_finding_cb = None
    if ai_mode != "off":
        try:
            from s2nagent.plugins.s2n_agent_plugin import S2NAgentPlugin
            from s2nagent.constants import AGENT_PLUGIN_NAME

            agent_plugin = S2NAgentPlugin(
                ai_mode=ai_mode,
                ai_model=ai_model,
                ai_endpoint=ai_endpoint,
                ai_provider=ai_provider,
                ai_api_key=ai_api_key,
            )
            on_finding_cb = agent_plugin.on_finding

            # 정규 플러그인 인스턴스 로드 (s2n_agent 제외)
            _regular_ids = set(plugin_list) - {AGENT_PLUGIN_NAME}
            _meta = discover_plugins(include_instances=True)
            _regular_instances = [
                m["instance"] for m in _meta if m["id"] in _regular_ids
            ]
            # Agent가 항상 첫 번째로 실행되도록 prepend
            all_plugins = [agent_plugin] + _regular_instances

            # ai_provider가 비어 있어도 여기까지 왔다는 건 S2NAGENT_PROVIDER 환경변수로
            # provider가 해석됐다는 뜻이다 — 그렇지 않으면 S2NAgentPlugin() 생성자에서
            # 이미 ValueError가 발생해 아래 except 절로 빠진다.
            _provider_label = ai_provider or os.environ.get("S2NAGENT_PROVIDER", "(env)")
            console.print(f"[cyan]🤖 S2N-Agent 활성화: mode={ai_mode}, model={ai_model}, provider={_provider_label}[/cyan]")

            if not agent_plugin.is_available():
                console.print(
                    f"[yellow]⚠️  provider={_provider_label} 사용 불가 — API 키 또는 엔드포인트를 "
                    "확인하세요 (ANTHROPIC_API_KEY / OPENAI_API_KEY / --ai-api-key / --ai-endpoint). "
                    "AI 기능 호출 시 오류가 발생합니다.[/yellow]"
                )
            elif _provider_label in ("anthropic", "claude", "openai", "gpt"):
                console.print(
                    "[dim]ℹ️  이 provider는 API 키 존재 여부만 확인했습니다 — "
                    "실제 호출 성공을 보장하지 않습니다(키 만료/무효 가능).[/dim]"
                )
        except ImportError:
            console.print(
                "[yellow]⚠️  s2nagent 패키지 미설치 — AI 모드 비활성화. "
                "`pip install s2n-agent` 실행 필요.[/yellow]"
            )
        except ValueError as exc:
            console.print(f"[red]❌ AI provider 오류: {exc}[/red]")
            sys.exit(1)

    scanner = Scanner(
        config=config,
        scan_context=scan_ctx,
        plugins=all_plugins,   # None → 정상 discover / list → AI+정규 플러그인 함께 실행
        auth_adapter=auth_adapter,
        auth_credentials=auth_credentials,
        logger=logger,
        on_finding=on_finding_cb,
        on_progress=on_progress,
    )

    # Scan 실행 + Duration 계산
    with progress:
        start = datetime.utcnow()
        report = scanner.scan()
        end = datetime.utcnow()
        progress.update(
            progress_task, completed=progress.tasks[0].total, description="🏁 스캔 완료"
        )

  

    # Rich Summary (fail-safe for tests with minimal FakeScanReport)
    try:
        plugin_results = getattr(report, "plugin_results", []) or []
        target_url = getattr(report, "target_url", None) or request.target_url
        duration_seconds = getattr(report, "duration_seconds", None)
        if duration_seconds is None:
            start = getattr(report, "start_time", getattr(report, "started_at", None))
            end = getattr(report, "end_time", getattr(report, "finished_at", None))
            if start and end:
                duration_seconds = (end - start).total_seconds()
        duration_text = (
            f"{duration_seconds:.2f} seconds"
            if isinstance(duration_seconds, (int, float))
            else "-"
        )

        total_findings = 0
        for pr in plugin_results:
            findings = getattr(pr, "findings", []) or []
            total_findings += len(findings)

        summary_table = Table(
            title="🚀 S2N Scan Summary",
            title_style="bold magenta",
            box=box.SIMPLE_HEAVY,
            show_header=False,
            padding=(0, 1),
        )
        summary_table.add_row("🎯 Target URL", f"[bold]{target_url}[/]")
        summary_table.add_row("🆔 Scan ID", getattr(report, "scan_id", "-"))
        summary_table.add_row(" ⏱ Duration", duration_text)
        summary_table.add_row("🧩 Plugins Loaded", str(len(plugin_results)))
        summary_table.add_row(
            "🔎 Findings Detected", f"[bold yellow]{total_findings}[/]"
        )
        summary_table.add_row(
            "📄 Output Format", getattr(config.output_config, "format", "-")
        )

        status_styles = {
            PluginStatus.SUCCESS: "green",
            PluginStatus.PARTIAL: "yellow",
            PluginStatus.FAILED: "red",
            PluginStatus.SKIPPED: "cyan",
            PluginStatus.TIMEOUT: "magenta",
        }
        status_icons = {
            PluginStatus.SUCCESS: "✅",
            PluginStatus.PARTIAL: "🟡",
            PluginStatus.FAILED: "❌",
            PluginStatus.SKIPPED: "⏩",
            PluginStatus.TIMEOUT: "⏰",
        }

        plugin_table = Table(
            title="🧩 Plugin Results",
            title_style="bold cyan",
            box=box.MINIMAL_HEAVY_HEAD,
            header_style="bold white",
        )
        plugin_table.add_column("Plugin")
        plugin_table.add_column("Status", justify="center")
        plugin_table.add_column("Findings", justify="right")
        plugin_table.add_column("Duration", justify="right")
        plugin_table.add_column("Note")

        for pr in plugin_results:
            status = getattr(pr, "status", None)
            status_color = status_styles.get(status, "white")
            icon = status_icons.get(status, "ℹ️")
            note = "-"
            metadata = getattr(pr, "metadata", None) or {}
            note = metadata.get("reason", note)
            if getattr(pr, "error", None):
                note = getattr(pr.error, "message", note)

            plugin_table.add_row(
                f"{icon} {getattr(pr, 'plugin_name', '-')}",
                f"[{status_color}]{getattr(status, 'value', status or '-')}[/{status_color}]",
                str(len(getattr(pr, "findings", []) or [])),
                f"{getattr(pr, 'duration_seconds', 0):.2f}s"
                if isinstance(getattr(pr, "duration_seconds", None), (int, float))
                else "-",
                note or "-",
            )

        console.print("\n")
        console.print(summary_table)
        if plugin_results:
            console.print(plugin_table)
        console.print("\n")
    except Exception as exc:  # pylint: disable=broad-except
        logger.debug("Failed to render summary tables: %s", exc)

    # Report 출력
    try:
        output_report(report, config.output_config)
        logger.info("Scan report successfully generated.")
    except Exception as exc:
        logger.exception("Failed to output report: %s", exc)
        raise click.ClickException(f"Failed to output report: {exc}") from exc

# list-plugins 명령어
@cli.command("list-plugins")
def list_plugins():
    """List all available plugins / 사용 가능한 플러그인 목록 조회"""
    plugins = discover_plugins()
    if not plugins:
        console.print("[yellow]No plugins discovered.[/yellow]")
        return

    table = Table(
        title="🧩 Available S2N Plugins",
        title_style="bold cyan",
        box=box.MINIMAL_HEAVY_HEAD,
        header_style="bold white",
    )
    table.add_column("ID", style="bold green")
    table.add_column("Name")
    table.add_column("Version", justify="center")
    table.add_column("Description")

    for p in plugins:
        table.add_row(
            p["id"],
            p["name"],
            p["version"],
            p["description"]
        )

    console.print(table)
    console.print(f"\nTotal: [bold]{len(plugins)}[/] plugins installed.\n")


# inspect-plugin 명령어
@cli.command("inspect-plugin")
@click.argument("name")
def inspect_plugin(name):
    """View details of a specific plugin / 특정 플러그인 상세 정보 조회"""
    plugins = discover_plugins()
    plugin = next((p for p in plugins if p["id"].lower() == name.lower()), None)

    if not plugin:
        console.print(f"[red]Error: Plugin '{name}' not found.[/red]")
        return

    table = Table(
        show_header=False,
        box=box.SIMPLE_HEAVY,
        padding=(0, 2),
        title=f"🔎 Plugin Details: {plugin['name']}",
        title_style="bold magenta"
    )
    table.add_row("ID", plugin["id"])
    table.add_row("Name", plugin["name"])
    table.add_row("Version", plugin["version"])
    table.add_row("Description", plugin["description"])

    console.print(table)


# install-host 명령어
@cli.command("install-host")
@click.option(
    "--ext-id",
    prompt="Chrome Extension ID (Press Enter to use default)",
    default="obfffedgblnnppemflanjipgocbbggjg",
    help="Chrome Extension ID (leave empty to use default)"
)
def install_host(ext_id):
    """Alias implementation moved to a helper or just kept here"""
    _install_host_logic(ext_id)

# install-gui (Alias for install-host)
@cli.command("install-gui")
@click.option(
    "--ext-id",
    prompt="Chrome Extension ID (Press Enter to use default)",
    default="obfffedgblnnppemflanjipgocbbggjg",
    help="Chrome Extension ID (leave empty to use default)"
)
def install_gui(ext_id):
    """Install Chrome Extension GUI & Host / 크롬 익스텐션 GUI 및 호스트 설치"""
    _install_host_logic(ext_id)

def _install_host_logic(ext_id):
    """Common logic for host installation"""
    """Install Chrome Native Messaging Host / 네이티브 메시징 호스트 설치"""
    console.print(f"[cyan]Installing S2N Native Messaging Host (Extension ID: {ext_id})...[/cyan]")
    
    # 경로 설정
    package_root = Path(__file__).resolve().parent.parent.parent.parent
    native_host_path = package_root / "native_host.py"
    
    if not native_host_path.exists():
        console.print(f"[red]Error: Cannot find native_host.py at {native_host_path}[/red]")
        return
        
    system = platform.system()
    home = Path.home()
    
    if system == "Darwin":
        target_dir = home / "Library" / "Application Support" / "Google" / "Chrome" / "NativeMessagingHosts"
    elif system == "Linux":
        target_dir = home / ".config" / "google-chrome" / "NativeMessagingHosts"
    elif system == "Windows":
        target_dir = home / "AppData" / "Local" / "Google" / "Chrome" / "User Data" / "NativeMessagingHosts"
    else:
        console.print(f"[red]Unsupported OS: {system}[/red]")
        return
        
    target_dir.mkdir(parents=True, exist_ok=True)
    target_manifest = target_dir / "com.s2n.scanner.json"
    
    if system == "Windows":
        launcher_path = target_dir / "com.s2n.scanner_launcher.bat"
        launcher_content = f'@echo off\r\n"{sys.executable}" "{native_host_path}" %*'
        launcher_path.write_text(launcher_content)
    else:
        launcher_path = target_dir / "com.s2n.scanner_launcher.sh"
        launcher_content = f'#!/bin/bash\nexport PYTHONPATH="{package_root}:$PYTHONPATH"\nexec "{sys.executable}" "{native_host_path}" "$@"\n'
        launcher_path.write_text(launcher_content)
        launcher_path.chmod(0o755)
        native_host_path.chmod(0o755)
        
    # 런타임에 매니페스트 JSON 생성 (외부 파일 의존성 제거)
    manifest_data = {
        "name": "com.s2n.scanner",
        "description": "S2N Vulnerability Scanner Native Messaging Host",
        "path": str(launcher_path),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{ext_id}/"]
    }
    
    with open(target_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=4)
        
    if system == "Windows":
        try:
            import winreg
            key_path = r"Software\\Google\\Chrome\\NativeMessagingHosts\\com.s2n.scanner"
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(target_manifest))
            winreg.CloseKey(key)
        except Exception as e:
            console.print(f"[yellow]Warning: Failed to set Windows Registry: {e}[/yellow]")
            console.print(f"[yellow]Please manually add registry key: HKCU\\{key_path} -> {target_manifest}[/yellow]")

    console.print(f"[green]✅ Installation Complete: {target_manifest}[/green]")
    
    # 확장 프로그램 프론트엔드 빌드 자동화
    extension_dir = package_root / "extension"
    if extension_dir.exists() and (extension_dir / "package.json").exists():
        console.print("[cyan]📦 Compiling Chrome Extension Frontend...[/cyan]")
        try:
            subprocess.run(["npm", "install"], cwd=extension_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["npm", "run", "build"], cwd=extension_dir, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            console.print(f"[green]✅ Frontend compiled successfully to '{extension_dir / 'dist'}'[/green]")
        except subprocess.CalledProcessError:
            console.print("[yellow]⚠️ Warning: Failed to compile frontend automatically. Please run 'npm install && npm run build' inside the 'extension' directory manually.[/yellow]")
        except FileNotFoundError:
            console.print("[yellow]⚠️ Warning: 'npm' command not found. Please install Node.js and compile manually.[/yellow]")
            
    console.print("[cyan]Please restart Google Chrome to apply changes.[/cyan]")


if __name__ == "__main__":
    cli()
