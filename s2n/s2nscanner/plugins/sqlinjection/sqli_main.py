from datetime import datetime
from typing import List, Optional

from s2n.s2nscanner.interfaces import (
    Finding,
    PluginConfig,
    PluginContext,
    PluginError,
    PluginResult,
    PluginStatus,
)
from s2n.s2nscanner.logger import get_logger
from s2n.s2nscanner.plugins.sqlinjection.sqli_scan import sqli_scan
from s2n.s2nscanner.plugins.helper import resolve_client, resolve_depth, resolve_target_url

logger = get_logger("plugins.sqlinjection")


class SQLInjectionPlugin:
    name = "sqlinjection"
    description = "SQL Injection 취약점을 스캐너"

    def __init__(self, config: Optional[PluginConfig] = None):
        self.config = config
        self.timeout = int(getattr(config, "timeout", 5) or 5)
        custom_params = getattr(config, "custom_params", None) or {}
        self.depth = int(custom_params.get("depth", 2))

    def run(self, plugin_context: PluginContext) -> PluginResult:
        start_dt = datetime.now()
        findings: List[Finding] = []

        # Extract configuration from plugin context
        client = resolve_client(self, plugin_context)
        depth = resolve_depth(self, plugin_context)
        target_url = resolve_target_url(self, plugin_context)
        plugin_config = getattr(plugin_context, "plugin_config", None)
        timeout = getattr(plugin_config, "timeout", self.timeout)
        
        # Logger setup
        log = plugin_context.logger or logger

        try:
            # Scan for SQL injection vulnerabilities (crawler integrated in sqli_scan)
            scan_result = sqli_scan(
                target_url,
                http_client=client,
                plugin_context=plugin_context,
                depth=depth,
                timeout=timeout,
            )
            findings.extend(scan_result)

        except Exception as e:
            log.exception(f"[SQLInjectionPlugin.run] plugin error: {e}")
            return PluginResult(
                plugin_name=self.name,
                status=PluginStatus.FAILED,
                error=PluginError(
                    error_type=type(e).__name__,
                    message=str(e),
                    traceback=str(e.__traceback__),
                ),
                duration_seconds=(datetime.now() - start_dt).total_seconds(),
            )

        # Determine status based on findings
        status = PluginStatus.PARTIAL if findings else PluginStatus.SUCCESS

        return PluginResult(
            plugin_name=self.name,
            status=status,
            findings=findings,
            duration_seconds=(datetime.now() - start_dt).total_seconds(),
            requests_sent=0,  # TODO: Track requests count if needed
        )


def main(config: Optional[PluginConfig] = None):
    return SQLInjectionPlugin(config)
