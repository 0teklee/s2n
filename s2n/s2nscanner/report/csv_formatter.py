# csv 변환 + csv 저장

"""
CSV Formatter Module

ScanReport 객체를 CSV 문자열로 직렬화하고 파일로 저장하는 기능을 제공합니다.
"""

from __future__ import annotations
from pathlib import Path
import csv
import io

from s2n.s2nscanner.interfaces import ScanReport
from s2n.s2nscanner.report.base import ReportFormatter
from s2n.s2nscanner.report.io_utils import write_text_file


def _safe_cell(value: object) -> object:
    if not isinstance(value, str):
        return value
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


class CSVFormatter(ReportFormatter):
    """
    CSV 형식 Formatter

    기능:
    - ScanReport → CSV 문자열 변환
    - CSV 파일 저장
    """

    def __init__(self):
        pass

    def format(self, report: ScanReport) -> str:
        """ScanReport를 CSV 문자열로 변환"""

        output = io.StringIO()
        writer = csv.writer(output)

        # CSV 헤더
        writer.writerow(
            [
                "ID",
                "Plugin",
                "Severity",
                "Title",
                "URL",
                "Parameter",
                "Method",
                "Payload",
                "Evidence",
                "CWE ID",
                "CVSS Score",
                "Confidence",
                "Timestamp",
            ]
        )

        # Finding rows
        for plugin_result in report.plugin_results:
            for f in plugin_result.findings:
                writer.writerow(
                    [
                        _safe_cell(f.id),
                        _safe_cell(f.plugin),
                        f.severity.value,
                        _safe_cell(f.title),
                        _safe_cell(f.url or ""),
                        _safe_cell(f.parameter or ""),
                        _safe_cell(f.method or ""),
                        _safe_cell(f.payload or ""),
                        _safe_cell(f.evidence or ""),
                        _safe_cell(f.cwe_id or ""),
                        f.cvss_score or "",
                        f.confidence.value,
                        f.timestamp.isoformat() if f.timestamp else "",
                    ]
                )

        return output.getvalue()

    def save(self, report: ScanReport, path: Path):
        """CSV 파일로 저장"""
        csv_str = self.format(report)
        write_text_file(Path(path), csv_str)
