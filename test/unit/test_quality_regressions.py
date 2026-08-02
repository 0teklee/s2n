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
