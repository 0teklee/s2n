"""
Scanner 엔진
-------------
ScanConfig/ScanContext ↔ PluginContext ↔ PluginResult/ScanReport 흐름을 담당합니다.
플러그인 로드, 실행, 결과 집계를 관리하며 인터페이스 모듈에서 정의한 데이터 구조에 맞춰
최종 ScanReport를 반환합니다.
"""

from __future__ import annotations

import getpass
import logging
import platform
import socket
import sys
import traceback
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:
    from importlib import metadata as importlib_metadata
except ImportError:  # pragma: no cover - <py3.8 fallback>
    import importlib_metadata  # type: ignore

from s2n.s2nscanner.finding import create_plugin_result, create_scan_report
from s2n.s2nscanner.clients.http_client import HttpClient
from s2n.s2nscanner.clients.protocols import HttpClientConfig
from s2n.s2nscanner.interfaces import (
    Confidence,
    Finding,
    PluginConfig,
    PluginContext,
    PluginError,
    PluginResult,
    PluginStatus,
    ScanConfig,
    ScanContext,
    ScanMetadata,
    ScanReport,
    ProgressInfo,
    Severity,
)
from s2n.s2nscanner.logger import get_logger
from s2n.s2nscanner.plugins.discovery import discover_plugins

PLUGIN_PACKAGE = "s2n.s2nscanner.plugins"
DEFAULT_SCANNER_VERSION = "0.1.0"


class Scanner:
    """
    Scanner: 플러그인 탐색/실행을 오케스트레이션 하고 최종 ScanReport 생성

    - config(필수): ScanConfig
    - auth_adapter(선택), http_client(선택), on_finding(선택: Finding 단위 콜백)
    """
    def __init__(
        self,
        config: ScanConfig,
        *,
        scan_context: Optional[ScanContext] = None,
        plugins: Optional[List[Any]] = None,
        auth_adapter: Optional[Any] = None,
        auth_credentials: Optional[List[Tuple[str, str]]] = None,
        http_client: Optional[HttpClient] = None,
        concurrency: Optional[int] = None,
        timeout: Optional[int] = None,
        logger: Optional[logging.Logger] = None,
        on_finding: Optional[Callable[[Finding], None]] = None,
        on_progress: Optional[Callable[[ProgressInfo], None]] = None,
        defer_authentication: bool = False,
        skip_auth_plugins: Optional[Sequence[str]] = None,
        cancel_event: Optional[Any] = None,
    ) -> None:
        if config is None:
            raise ValueError("Scanner requires a ScanConfig instance.")

        self.config = config
        self.logger = logger or get_logger("scanner")
        self.auth_adapter = auth_adapter
        self.auth_credentials = auth_credentials or []
        self.defer_authentication = defer_authentication
        self.skip_auth_plugins = {name.lower() for name in (skip_auth_plugins or [])}
        self._auth_performed = False
        self.http_client = http_client or self._build_http_client()
        self.plugins = plugins or []
        self.concurrency = concurrency or self.config.scanner_config.max_threads
        self.timeout = timeout or self.config.scanner_config.timeout
        self.on_finding = on_finding
        self.on_progress = on_progress
        self.cancel_event = cancel_event

        self._discovered_plugins: List[Any] = []
        plugin_keys = list(self.config.plugin_configs.keys()) if self.config.plugin_configs else []
        self.allowed_plugins_order = [key.lower() for key in plugin_keys] or None
        self.allowed_plugins = set(self.allowed_plugins_order or [])
        if not self.allowed_plugins:
            self.allowed_plugins = None
        self.prioritized_plugins = ["brute_force"]
        self._scanner_version = self._resolve_version()
        self.scan_context = self._prepare_scan_context(scan_context)

        self.scan_context.logger = self.logger

        self.logger.debug(
            "Scanner initialized. target=%s, plugins(preloaded)=%d",
            self.config.target_url,
            len(self.plugins),
        )

    # 플러그인 탐색/실행/정규화
    def discover_plugins(self) -> List[Any]:
        """
        플러그인 동적 탐색:
        우선순위 1) 외부에서 인스턴스 리스트로 주입된 self.plugins 사용
        우선순위 2) s2n.s2nscanner.plugins 패키지 하위 모듈 순회하며 Plugin() 팩토리 호출
        """
        if self.plugins:
            self._discovered_plugins = (
                [
                    plugin
                    for plugin in self.plugins
                    if not self.allowed_plugins
                    or self._get_plugin_identifier(plugin) in self.allowed_plugins
                ]
            )
            for plugin in self._discovered_plugins:
                if not hasattr(plugin, "_s2n_module_name"):
                    setattr(
                        plugin,
                        "_s2n_module_name",
                        plugin.__class__.__module__.split(".")[-1],
                    )
            self.logger.debug(
                "Using %d pre-loaded plugin instances.", len(self._discovered_plugins)
            )
            self._apply_plugin_ordering()
            return self._discovered_plugins

        if self._discovered_plugins:
            return self._discovered_plugins

        self.logger.debug("Discovering plugins from package '%s'...", PLUGIN_PACKAGE)
        metadata = discover_plugins(include_instances=True)
        
        for m in metadata:
            modname = m["id"]
            if self.allowed_plugins and modname.lower() not in self.allowed_plugins:
                continue
            
            instance = m["instance"]
            self._discovered_plugins.append(instance)
            self.logger.debug("Loaded plugin '%s'.", getattr(instance, "name", modname))

        self._apply_plugin_ordering()
        return self._discovered_plugins

    def scan(self) -> ScanReport:
        self.logger.info("🧭 Starting scan for target %s", self.config.target_url)
        self.scan_context.start_time = datetime.utcnow()

        plugin_results: List[PluginResult] = []
        self._auth_performed = False

        if self.auth_adapter and not self.defer_authentication:
            self._ensure_authenticated()

        # smart_crawl 연동 — SiteMap 생성 후 컨텍스트에 첨부
        try:
            from s2n.s2nscanner.crawler.smart_crawler import smart_crawl

            crawl_depth = getattr(self.config.scanner_config, "crawl_depth", 2)
            sitemap = smart_crawl(
                self.config.target_url,
                self.http_client or self.scan_context.http_client,
                depth=crawl_depth,
                should_cancel=self._is_cancelled,
            )
            setattr(self.scan_context, "sitemap", sitemap)
            self.logger.info(
                "SiteMap built: %d pages, %d URLs",
                len(sitemap.pages),
                len(sitemap.all_urls),
            )
        except Exception:
            self.logger.warning("smart_crawl failed, proceeding without SiteMap", exc_info=True)

        plugins = self.discover_plugins()

        # 플러그인이 target_form_types를 선언하면 SiteMap에 동적 등록
        sitemap = getattr(self.scan_context, "sitemap", None)
        if sitemap:
            for plugin in plugins:
                form_types = getattr(plugin, "target_form_types", None)
                if form_types is not None:
                    identifier = self._get_plugin_identifier(plugin)
                    sitemap.register_plugin(identifier, form_types)

        total_plugins = len(plugins)
        if total_plugins:
            self._emit_progress(0, total_plugins, "🧭 Preparing Scan \n 스캔 준비 중")
        else:
            self._emit_progress(0, 0, "⚠️ Cannot find executable plugin \n 실행할 플러그인이 없습니다.")

        for idx, plugin in enumerate(plugins, start=1):
            if self._is_cancelled():
                self.logger.info("Scan cancellation requested; stopping before next plugin.")
                break
            plugin_name = getattr(plugin, "name", plugin.__class__.__name__)
            plugin_identifier = self._get_plugin_identifier(plugin)

            if self._should_authenticate_before_plugin(plugin_identifier):
                self._ensure_authenticated()

            self.logger.info(f"🔍 Executing plugin: {plugin_name}")
            self._emit_progress(idx - 1, total_plugins, f"🔄 {plugin_name} Running")
            plugin_config = self._resolve_plugin_config(plugin_identifier, plugin_name)
            result: Optional[PluginResult] = None

            if not plugin_config.enabled:
                self.logger.info("⏩ Plugin '%s' disabled via configuration. Skipping.", plugin_name)
                skipped = self._build_skipped_result(plugin_name, "disabled")
                result = skipped
                plugin_results.append(skipped)
                self._emit_progress(idx, total_plugins, f"⏩ {plugin_name} 비활성화됨")
                continue

            try:
                result = self._run_plugin(plugin, plugin_name, plugin_config)

                # ✅ None 방어 처리
                if result is None:
                    self.logger.warning(f"⚠️ Plugin '{plugin_name}' returned None. Forcing FAILED PluginResult.")
                    err = PluginError(
                        error_type="PluginContractError",
                        message="plugin.run() returned None",
                        traceback=None,
                    )
                    result = create_plugin_result(
                        plugin_name=plugin_name,
                        findings=[],
                        start_time=datetime.utcnow(),
                        status=PluginStatus.FAILED,
                        error=err,
                    )

                # ✅ 타입 확인 로그
                self.logger.debug(f"✅ Plugin '{plugin_name}' returned type: {type(result).__name__}")

                plugin_results.append(result)

                # findings 접근 전 유효성 체크
                findings = getattr(result, "findings", None)
                if findings is None:
                    self.logger.warning(f"⚠️ Plugin '{plugin_name}' returned result without 'findings' field.")

            except Exception as e:
                self.logger.exception(f"💥 Plugin '{plugin_name}' crashed: {e}")
                result = self._plugin_failure_result(plugin_name, e, datetime.utcnow())
                plugin_results.append(result)

            if result:
                status_icon = {
                    PluginStatus.SUCCESS: "✅",
                    PluginStatus.PARTIAL: "🟡",
                    PluginStatus.FAILED: "❌",
                    PluginStatus.SKIPPED: "⏩",
                    PluginStatus.TIMEOUT: "⏰",
                }.get(result.status, "ℹ️")
                self._emit_progress(idx, total_plugins, f"{status_icon} {plugin_name} - {result.status.value}")

        # --- 리포트 작성
        end_time = datetime.utcnow()
        metadata = self._build_metadata()
        report = create_scan_report(
            scan_id=self.scan_context.scan_id,
            target_url=self.config.target_url,
            scanner_version=self._scanner_version,
            start_time=self.scan_context.start_time,
            end_time=end_time,
            config=self.config,
            plugin_results=plugin_results,
            metadata=metadata,
        )

        setattr(self.scan_context, "last_report", report)

        self.logger.info(
            "🏁 Scan completed in %.2fs (%d plugins).",
            report.duration_seconds,
            len(plugin_results),
        )
        final_message = "Scan cancelled" if self._is_cancelled() else "🏁 스캔 완료"
        self._emit_progress(len(plugin_results), total_plugins or 1, final_message)
        return report

    def _build_http_client(self) -> HttpClient:
        scanner = self.config.scanner_config
        network = self.config.network_config
        return HttpClient(
            HttpClientConfig(
                retry=scanner.max_retries,
                backoff=scanner.retry_delay,
                timeout=(network.connection_timeout, network.read_timeout),
                verify_ssl=scanner.verify_ssl,
                allow_redirects=scanner.follow_redirects,
                base_headers={"User-Agent": scanner.user_agent},
                proxy=network.proxy,
                rate_limit=network.rate_limit,
                max_connections=network.max_connections,
            )
        )

    def _is_cancelled(self) -> bool:
        return bool(self.cancel_event and self.cancel_event.is_set())

    def _prepare_scan_context(self, scan_context: Optional[ScanContext]) -> ScanContext:
        """
        ScanContext 준비
        """
        if scan_context is None:
            ctx = ScanContext(
                scan_id=f"scan-{uuid.uuid4().hex}",
                start_time=datetime.utcnow(),
                config=self.config,
                http_client=self.http_client or HttpClient(),
                crawler=None,
            )
        else:
            ctx = scan_context
            if not getattr(ctx, "config", None):
                ctx.config = self.config
            if not getattr(ctx, "scan_id", None):
                ctx.scan_id = f"scan-{uuid.uuid4().hex}"

        # HTTP client resolution
        if getattr(ctx, "http_client", None):
            self.http_client = ctx.http_client
        else:
            ctx.http_client = self.http_client or HttpClient()
            self.http_client = ctx.http_client

        # Prefer adapter-managed client if available
        if self.auth_adapter and hasattr(self.auth_adapter, "get_client"):
            try:
                ctx.http_client = self.auth_adapter.get_client()
                self.http_client = ctx.http_client
            except Exception:  # pylint: disable=broad-except
                self.logger.exception("Failed to obtain http client from auth adapter.")

        setattr(ctx, "target_url", getattr(ctx, "target_url", self.config.target_url))
        setattr(ctx, "auth_adapter", self.auth_adapter)

        if self.config.auth_config:
            ctx.auth_config = self.config.auth_config

        return ctx

    def _resolve_version(self) -> str:
        try:
            return importlib_metadata.version("s2n")
        except Exception:  # pragma: no cover - metadata lookup failure
            return DEFAULT_SCANNER_VERSION

    def _resolve_plugin_config(
        self, plugin_identifier: str, plugin_name: str
    ) -> PluginConfig:
        config = (
            self.config.plugin_configs.get(plugin_identifier)
            or self.config.plugin_configs.get(plugin_identifier.lower())
            or self.config.plugin_configs.get(plugin_name)
            or self.config.plugin_configs.get(plugin_name.lower())
        )
        return config or PluginConfig()

    def _get_plugin_identifier(self, plugin: Any) -> str:
        module_name = getattr(plugin, "_s2n_module_name", None)
        if module_name:
            return module_name.lower()
        return getattr(plugin, "name", plugin.__class__.__name__).lower()

    def _apply_plugin_ordering(self) -> None:
        if not self._discovered_plugins:
            return

        if self.allowed_plugins_order:
            order_map = {name: idx for idx, name in enumerate(self.allowed_plugins_order)}

            def order_key(plugin: Any) -> int:
                identifier = self._get_plugin_identifier(plugin)
                return order_map.get(identifier, len(order_map))

            self._discovered_plugins.sort(key=order_key)
            return

        priority_map = {name: idx for idx, name in enumerate(self.prioritized_plugins)}

        def priority_key(plugin: Any) -> tuple[int, str]:
            identifier = self._get_plugin_identifier(plugin)
            return (
                priority_map.get(identifier, len(priority_map)),
                identifier,
            )

        self._discovered_plugins.sort(key=priority_key)

    def _should_authenticate_before_plugin(self, plugin_identifier: str) -> bool:
        if not self.auth_adapter:
            return False
        if not self.defer_authentication:
            return False
        if self._auth_performed:
            return False
        if plugin_identifier in self.skip_auth_plugins:
            return False
        return True

    def _ensure_authenticated(self) -> bool:
        if not self.auth_adapter:
            return False
        if self._auth_performed:
            return True

        credentials = self.auth_credentials or []

        try:
            if hasattr(self.auth_adapter, "ensure_authenticated"):
                ok = self.auth_adapter.ensure_authenticated(credentials)
            else:
                ok = self.auth_adapter.login()

            if ok and hasattr(self.auth_adapter, "get_client"):
                client = self.auth_adapter.get_client()
                if client:
                    self.http_client = client
                    self.scan_context.http_client = client

            self._auth_performed = True

            if ok:
                self.logger.info("Authentication succeeded via adapter.")
            else:
                self.logger.warning("Authentication failed via adapter.")

            return ok
        except Exception:
            self._auth_performed = True
            self.logger.exception("Authentication error.")
            return False

    def _run_plugin(
        self,
        plugin: Any,
        plugin_name: str,
        plugin_config: PluginConfig,
        ) -> PluginResult:

        # 0. 초기화 및 Context 준비 (initialize)
        # plugin instance는 discover_plugins()에서 이미 생성됨
        # 인스턴스 생성 시 __init__()가 호출되었으므로 별도 초기화 단계는 없음

        start_time = datetime.utcnow()
        plugin_logger = get_logger(f"plugins.{plugin_name}")

        self.logger.debug(f"🚀 Running plugin '{plugin_name}' with config: {plugin_config}")

        # SiteMap 기반 target_urls 설정
        target_urls = [self.config.target_url]
        sitemap = getattr(self.scan_context, "sitemap", None)
        if sitemap:
            sm_urls = sitemap.get_urls()
            if sm_urls:
                target_urls = sm_urls

        plugin_context = PluginContext(
            plugin_name=plugin_name,
            scan_context=self.scan_context,
            plugin_config=plugin_config,
            target_urls=target_urls,
            logger=plugin_logger,
        )

        # 레거시 호환성: set_logger / configure 호출 (새 플러그인은 __Init__에서 처리)
        for method_name in ("set_logger", "configure"):
            if hasattr(plugin, method_name):
                try:
                    getattr(plugin, method_name)(plugin_logger if method_name == "set_logger" else plugin_config, self.scan_context)
                    self.logger.debug(f"🧩 {plugin_name}.{method_name}() executed successfully.")
                except Exception as e:
                    self.logger.debug(f"⚠️ {plugin_name}.{method_name}() failed: {e}")

        # --- run() 실행
        # 1. pre-scan
        if hasattr(plugin, "pre_scan"):
            try:
                self.logger.info(f"🔧 Pre-scan setup for plugin '{plugin_name}'")
                plugin.pre_scan(plugin_context)
                self.logger.info(f"✅ Pre-scan for plugin '{plugin_name}' completed.")
            except Exception as exc:
                self.logger.exception(f"💣 Exception during {plugin_name}.pre_scan(): {exc}")

        # 2. run
        raw_result = None
        if hasattr(plugin, "run"):
            try:
                self.logger.info(f"▶️ Executing run() for plugin '{plugin_name}'")
                raw_result = plugin.run(plugin_context)
                self.logger.debug(f"🧩 Plugin '{plugin_name}' run() finished, return type={type(raw_result).__name__}")

            except Exception as exc:
                self.logger.exception(f"💣 Exception during {plugin_name}.run(): {exc}")
                raw_result = self._plugin_failure_result(plugin_name, exc, start_time)

        # 3. post-scan
        is_result_plugin_result = isinstance(raw_result, PluginResult)

        if not is_result_plugin_result and hasattr(plugin, "post_scan"):
            try:
                self.logger.info(f"▶️ {plugin_name}.post_scan() started")
                final_result = plugin.post_scan(plugin_context)
                self.logger.info(f"✅ {plugin_name}.post_scan() completed")

                if not isinstance(final_result, PluginResult):
                    raise TypeError(f"post_scan() must return a PluginResult instance, got {type(final_result).__name__}")
                
                raw_result = final_result
            
            except Exception as exc:
                self.logger.exception(f"💣 Exception during {plugin_name}.post_scan(): {exc}")
                raw_result = self._plugin_failure_result(plugin_name, exc, start_time)
                

        # 4. cleanup
        if hasattr(plugin, "cleanup"):
            try:
                self.logger.info(f"🧹 {plugin_name}.cleanup() started")
                plugin.cleanup(plugin_context)
                self.logger.info(f"✅ {plugin_name}.cleanup() completed")
            except Exception as exc:
                self.logger.exception(f"⚠️ Exception during {plugin_name}.cleanup(): {exc}")

        # 5. 최종 결과 반환 및 정규화
        if raw_result is None:
            if not hasattr(plugin, "run") and not hasattr(plugin, "post_scan"):
                self.logger.warning(f"⚠️ Plugin '{plugin_name}' has no run() or post_scan() method. Skipping.")
                return self._build_skipped_result(plugin_name, "no run() or post_scan() method")
            
            err = PluginError(error_type="PluginContractError", message="plugin returned None", timestamp=datetime.utcnow())
            return self._plugin_failure_result(plugin_name, err, start_time)
        

        if not isinstance(raw_result, PluginResult):
            findings = self._normalize_findings(plugin_name, raw_result, self.config.target_url)
            self.logger.debug(f"📊 '{plugin_name}' normalized findings count={len(findings)}")
            self._emit_findings(findings)

            return create_plugin_result(
                plugin_name=plugin_name,
                findings=findings,
                start_time=start_time,
                status=PluginStatus.SUCCESS,
            )

        findings = getattr(raw_result, "findings", None) 
        if findings is not None:
            self._emit_findings(findings)

        return raw_result
        

    def _plugin_failure_result(
        self,
        plugin_name: str,
        exc: Exception,
        start_time: datetime,
    ) -> PluginResult:
        # 플러그인 실행 중 예외를 표준 PluginResult로 변환
        error = PluginError(
            error_type=type(exc).__name__,
            message=str(exc),
            traceback=traceback.format_exc(),
        )
        return create_plugin_result(
            plugin_name=plugin_name,
            findings=[],
            start_time=start_time,
            status=PluginStatus.FAILED,
            error=error,
        )
    
    def _build_skipped_result(self, plugin_name: str, reason: str) -> PluginResult:
        # 스킵된 플러그인 결과 생성
        start_time = datetime.utcnow()
        return create_plugin_result(
            plugin_name=plugin_name,
            findings=[],
            start_time=start_time,
            status=PluginStatus.SKIPPED,
            metadata={"reason": reason},
        )
    
    def _normalize_findings(
            self,
            plugin_name: str,
            raw_result: Any,
            default_url: str,
        ) -> List[Finding]:
            """
            허용 입력: None, Finding, dict, List/Set/Tuple
            """
            if raw_result is None:
                return []
            
            items: Sequence[Any]
            if isinstance(raw_result, (list, tuple, set)):
                items = list(raw_result)
            else:
                items = [raw_result]

            findings: List[Finding] = []
            for item in items:
                if item is None:
                    continue
                if isinstance(item, Finding):
                    findings.append(item)
                elif isinstance(item, dict):
                    findings.append(self._dict_to_finding(plugin_name, item, default_url))
                else:
                    self.logger.debug(
                        "Plugin '%s' returned unsupported finding type: %s",
                        plugin_name,
                        type(item).__name__,
                    )
            return findings
    
    def _dict_to_finding(self, plugin_name: str, data: Dict[str, Any], default_url: str) -> Finding:
        """
        dict -> Finding 시 누락 필드 보정
        """
        fid = data.get("id") or f"{plugin_name}-{uuid.uuid4().hex[:8]}"
        severity = self._normalize_severity(data.get("severity", Severity.MEDIUM))
        confidence = self._normalize_confidence(data.get("confidence"))
        references = data.get("references") or []

        return Finding(
            id=fid,
            plugin=plugin_name,
            severity=severity,
            title=data.get("title", "Unnamed finding"),
            description=data.get("description", ""),
            url=data.get("url", default_url),
            parameter=data.get("parameter"),
            method=data.get("method"),
            payload=data.get("payload"),
            evidence=data.get("evidence"),
            remediation=data.get("remediation"),
            references=list(references),
            cwe_id=data.get("cwe_id"),
            cvss_score=data.get("cvss_score"),
            cvss_vector=data.get("cvss_vector"),
            confidence=confidence,
        )
    
    def _normalize_severity(self, value: Any) -> Severity:
        """문자열/Enum 혼용 입력을 Severity Enum으로 정규화."""
        if isinstance(value, Severity):
            return value
        if isinstance(value, str):
            try:
                return Severity[value.upper()]
            except KeyError:
                try:
                    return Severity(value)
                except Exception:
                    return Severity.MEDIUM
        return Severity.MEDIUM

    def _normalize_confidence(self, value: Any) -> Confidence:
        """문자열/Enum 혼용 입력을 Confidence Enum으로 정규화."""
        if isinstance(value, Confidence):
            return value
        if isinstance(value, str):
            try:
                return Confidence[value.upper()]
            except KeyError:
                try:
                    return Confidence(value)
                except Exception:
                    return Confidence.FIRM
        return Confidence.FIRM

    # ------------------------------------------------------------------ #
    # (3) 출력 단계: 메타데이터/콜백
    # ------------------------------------------------------------------ #
    def _build_metadata(self) -> ScanMetadata:
        """
        환경 메타데이터 작성:
        - hostname, username, python_version, os_info, cli_args, config_file
        """
        try:
            hostname = socket.gethostname()
        except Exception:  # pragma: no cover
            hostname = "unknown"

        try:
            username = getpass.getuser()
        except Exception:  # pragma: no cover
            username = "unknown"

        python_version = platform.python_version()
        os_info = f"{platform.system()} {platform.release()}".strip()
        cli_args = sys.argv[1:] if len(sys.argv) > 1 else None
        config_file = getattr(self.config, "config_path", None)

        return ScanMetadata(
            hostname=hostname,
            username=username,
            python_version=python_version,
            os_info=os_info,
            cli_args=cli_args,
            config_file=str(config_file) if config_file else None,
        )

    def _emit_progress(self, current: int, total: int, message: str) -> None:
        """
        ProgressInfo 콜백을 통해 콘솔/상위 UI가 실시간 진행률을 표시할 수 있게 함.
        """
        if not self.on_progress:
            return

        safe_total = total if total > 0 else 1
        completed = max(0, current)
        percentage = max(0.0, min(100.0, (completed / safe_total) * 100))

        info = ProgressInfo(
            current=completed,
            total=safe_total,
            percentage=percentage,
            message=message,
        )

        try:
            self.on_progress(info)
        except Exception:  # pylint: disable=broad-except
            self.logger.exception("on_progress callback raised an exception.")

    def _emit_findings(self, findings: Sequence[Finding]) -> None:
        """
        Finding 단위 콜백(on_finding)이 등록된 경우 호출.
        - 실시간 콘솔 출력/웹소켓 송신/진행바 업데이트 등에서 사용 가능
        """
        if not self.on_finding or not findings:
            return

        for finding in findings:
            try:
                self.on_finding(finding)
            except Exception:  # pylint: disable=broad-except
                self.logger.exception("on_finding callback raised an exception.")
