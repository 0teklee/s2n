"""
SiteMap — 크롤링 결과를 구조화하는 데이터 모듈
- PageInfo/ClassifiedForm을 집계하고 플러그인별 공격 대상을 매핑
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

from s2n.s2nscanner.crawler.classifier import ClassifiedForm, FormType, PageInfo


# 기본 플러그인-FormType 매핑 (플러그인이 target_form_types를 선언하지 않은 경우 fallback)
_DEFAULT_PLUGIN_FORM_MAP: Dict[str, List[FormType]] = {
    "xss": [FormType.TEXT_INPUT, FormType.SEARCH, FormType.GENERIC],
    "sqlinjection": [FormType.TEXT_INPUT, FormType.SEARCH, FormType.GENERIC],
    "file_upload": [FormType.FILE_UPLOAD],
    "oscommand": [FormType.COMMAND, FormType.TEXT_INPUT],
    "csrf": list(FormType),
    "brute_force": [FormType.LOGIN],
    "soft_brute_force": [FormType.LOGIN],
}


@dataclass
class SiteMap:
    """크롤링 + 분류 결과를 보관하는 구조체."""

    base_url: str
    pages: Dict[str, PageInfo] = field(default_factory=dict)
    forms_by_type: Dict[FormType, List[ClassifiedForm]] = field(
        default_factory=lambda: defaultdict(list)
    )
    login_forms: List[ClassifiedForm] = field(default_factory=list)
    all_urls: List[str] = field(default_factory=list)

    # 동적 플러그인-FormType 레지스트리 (register_plugin으로 등록)
    _plugin_form_map: Dict[str, List[FormType]] = field(
        default_factory=lambda: dict(_DEFAULT_PLUGIN_FORM_MAP)
    )

    # ------------------------------------------------------------------
    # 플러그인 등록
    # ------------------------------------------------------------------

    def register_plugin(self, plugin_name: str, form_types: List[FormType]) -> None:
        """플러그인의 대상 FormType을 동적으로 등록.

        플러그인이 target_form_types 속성을 선언하면
        scan_engine에서 자동으로 호출한다.
        """
        self._plugin_form_map[plugin_name.lower()] = form_types

    # ------------------------------------------------------------------
    # 페이지/폼 추가
    # ------------------------------------------------------------------

    def add_page(self, page: PageInfo) -> None:
        """PageInfo를 등록하고 내부 인덱스를 갱신."""
        if page.url not in self.pages:
            self.all_urls.append(page.url)
        self.pages[page.url] = page

        for cf in page.forms:
            self.forms_by_type[cf.form_type].append(cf)
            if cf.form_type == FormType.LOGIN:
                self.login_forms.append(cf)

    # ------------------------------------------------------------------
    # 조회 API
    # ------------------------------------------------------------------

    def get_attack_targets(self, plugin_name: str) -> List[ClassifiedForm]:
        """플러그인 이름에 맞는 ClassifiedForm 목록을 반환.

        우선순위: register_plugin 등록 > _DEFAULT_PLUGIN_FORM_MAP > 전체 FormType
        """
        target_types = self._plugin_form_map.get(plugin_name.lower(), list(FormType))
        results: List[ClassifiedForm] = []
        for ft in target_types:
            results.extend(self.forms_by_type.get(ft, []))
        return results

    def get_urls(self) -> List[str]:
        """crawl_recursive 호환 — 발견된 URL 목록 반환."""
        return self.all_urls

    def get_forms(self, *types: FormType) -> List[ClassifiedForm]:
        """지정 FormType에 해당하는 폼 목록 반환."""
        results: List[ClassifiedForm] = []
        for ft in types:
            results.extend(self.forms_by_type.get(ft, []))
        return results
