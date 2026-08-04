from datetime import datetime
from unittest.mock import MagicMock

from s2n.s2nscanner.clients.http_client import HttpClient
from s2n.s2nscanner.clients.protocols import HttpClientConfig
from s2n.s2nscanner.finding import create_scan_report
from s2n.s2nscanner.interfaces import (
    Finding,
    NetworkConfig,
    PluginConfig,
    PluginResult,
    PluginStatus,
    ScanConfig,
    ScannerConfig,
    Severity,
)
from s2n.s2nscanner.plugins.discovery import discover_plugins
from s2n.s2nscanner.report.csv_formatter import CSVFormatter
from s2n.s2nscanner.report.html_formatter import HTMLFormatter
from s2n.s2nscanner.scan_engine import Scanner


def test_http_request_options_override_client_defaults():
    session = MagicMock()
    session.request.return_value = MagicMock()
    client = HttpClient(
        HttpClientConfig(timeout=30, verify_ssl=False, allow_redirects=False),
        session=session,
    )

    client.get(
        "https://example.com",
        timeout=5,
        verify=True,
        allow_redirects=True,
    )

    _, kwargs = session.request.call_args
    assert kwargs["timeout"] == 5
    assert kwargs["verify"] is True
    assert kwargs["allow_redirects"] is True


def test_scanner_builds_http_client_from_scan_config():
    config = ScanConfig(
        target_url="https://example.com",
        scanner_config=ScannerConfig(
            max_retries=4,
            retry_delay=0.5,
            user_agent="quality-test",
            follow_redirects=False,
            verify_ssl=False,
        ),
        network_config=NetworkConfig(
            max_connections=7,
            connection_timeout=2,
            read_timeout=9,
            rate_limit=3.0,
            proxy="http://proxy.example:8080",
        ),
    )

    scanner = Scanner(config)
    client_config = scanner.http_client.config

    assert client_config.retry == 4
    assert client_config.backoff == 0.5
    assert client_config.timeout == (2, 9)
    assert client_config.verify_ssl is False
    assert client_config.allow_redirects is False
    assert client_config.base_headers["User-Agent"] == "quality-test"
    assert client_config.max_connections == 7
    assert client_config.rate_limit == 3.0
    assert client_config.proxy == "http://proxy.example:8080"


def test_preloaded_plugins_are_filtered_by_stable_plugin_id():
    metadata = discover_plugins(include_instances=True)
    requested_ids = [item["id"] for item in metadata]
    config = ScanConfig(
        target_url="https://example.com",
        plugin_configs={plugin_id: PluginConfig() for plugin_id in requested_ids},
    )
    scanner = Scanner(config, plugins=[item["instance"] for item in metadata])

    loaded_ids = [scanner._get_plugin_identifier(plugin) for plugin in scanner.discover_plugins()]

    assert loaded_ids == requested_ids
    assert "autobot" in loaded_ids
    assert "brute_force" in loaded_ids


def _hostile_report():
    now = datetime.now()
    finding = Finding(
        id="=CMD()",
        plugin="xss",
        severity=Severity.HIGH,
        title="<script>alert(1)</script>",
        description="attacker-controlled <b>markup</b>",
        payload="<img src=x onerror=alert(1)>",
        evidence="=HYPERLINK(\"https://evil.example\")",
    )
    result = PluginResult(
        plugin_name="xss",
        status=PluginStatus.SUCCESS,
        findings=[finding],
        start_time=now,
        end_time=now,
    )
    return create_scan_report(
        scan_id="scan-test",
        target_url="https://example.com/<script>",
        scanner_version="test",
        start_time=now,
        end_time=now,
        config=ScanConfig(target_url="https://example.com"),
        plugin_results=[result],
    )


def test_html_report_escapes_attacker_controlled_fields(tmp_path):
    formatter = HTMLFormatter()
    output = formatter.format(_hostile_report())

    assert "<script>alert(1)</script>" not in output
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in output

    destination = tmp_path / "nested" / "report.html"
    formatter.save(_hostile_report(), destination)
    assert destination.exists()


def test_csv_report_neutralizes_spreadsheet_formulas():
    output = CSVFormatter().format(_hostile_report())

    assert "'=CMD()" in output
    assert "'=HYPERLINK" in output


def _disable_smart_crawl(monkeypatch):
    """단위 테스트에서 실제 네트워크 크롤링을 타지 않도록 smart_crawl을 무력화."""
    import s2n.s2nscanner.crawler.smart_crawler as smart_crawler_mod

    def _raise(*_args, **_kwargs):
        raise RuntimeError("network disabled in unit test")

    monkeypatch.setattr(smart_crawler_mod, "smart_crawl", _raise)


def _fake_plugin_result(plugin_name: str) -> PluginResult:
    now = datetime.now()
    return PluginResult(
        plugin_name=plugin_name,
        status=PluginStatus.SUCCESS,
        findings=[],
        start_time=now,
        end_time=now,
    )


def test_on_scan_complete_is_called_once_after_all_plugins_run(monkeypatch):
    """scan()이 모든 플러그인 run() 종료 후 on_scan_complete 훅을 1회 호출해야 한다.

    S2NAgentPlugin.on_scan_complete()가 aggregate FP 필터/multi-step planner를
    구동하는 진입점인데, 지금까지 scan_engine.py에 호출부 자체가 없어 이 훅이
    한 번도 실행되지 않았다 (docs/plugins/integration-gaps.md §2 참고).
    """
    _disable_smart_crawl(monkeypatch)

    calls: list[tuple[object, list]] = []

    class _PluginWithOnScanComplete:
        name = "fake_with_hook"

        def run(self, plugin_context):
            return _fake_plugin_result("fake_with_hook")

        def on_scan_complete(self, scan_context, plugin_results):
            calls.append((scan_context, list(plugin_results)))

    class _PluginWithoutOnScanComplete:
        """on_scan_complete를 구현하지 않은 일반 플러그인 — 회귀 없이 그대로 스킵되어야 한다."""

        name = "fake_without_hook"

        def run(self, plugin_context):
            return _fake_plugin_result("fake_without_hook")

    config = ScanConfig(target_url="https://example.invalid")
    scanner = Scanner(
        config,
        plugins=[_PluginWithOnScanComplete(), _PluginWithoutOnScanComplete()],
    )

    scanner.scan()

    assert len(calls) == 1
    called_scan_context, called_plugin_results = calls[0]
    assert called_scan_context is scanner.scan_context
    assert {r.plugin_name for r in called_plugin_results} == {
        "fake_with_hook",
        "fake_without_hook",
    }


def test_on_scan_complete_exception_does_not_abort_scan(monkeypatch):
    """on_scan_complete()에서 예외가 발생해도 스캔 전체는 정상적으로 완료돼야 한다."""
    _disable_smart_crawl(monkeypatch)

    class _ExplodingPlugin:
        name = "exploding_plugin"

        def run(self, plugin_context):
            return _fake_plugin_result("exploding_plugin")

        def on_scan_complete(self, scan_context, plugin_results):
            raise ValueError("boom")

    config = ScanConfig(target_url="https://example.invalid")
    scanner = Scanner(config, plugins=[_ExplodingPlugin()])

    report = scanner.scan()

    assert report is not None
    assert len(report.plugin_results) == 1
