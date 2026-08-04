"""
smart_crawl — 고급 크롤러
- 기존 crawl_recursive와 동일한 BFS 로직 사용
- 각 페이지에서 PageClassifier로 폼을 분류하고 SiteMap에 축적
- crawler/__init__.py 는 수정하지 않음
"""

from __future__ import annotations

import urllib.parse
from collections import deque
from typing import Any, Callable, Optional

from s2n.s2nscanner.crawler import extract_same_origin_links
from s2n.s2nscanner.crawler.classifier import PageClassifier
from s2n.s2nscanner.crawler.sitemap import SiteMap
from s2n.s2nscanner.logger import get_logger

logger = get_logger("smart_crawler")


def smart_crawl(
    base_url: str,
    client: Any,
    depth: int = 2,
    timeout: int = 5,
    classifier: Optional[PageClassifier] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> SiteMap:
    """BFS 크롤링 + 페이지별 폼 분류 → SiteMap 반환.

    기존 crawl_recursive 와 동일한 BFS/도메인 제한 로직을 사용하되,
    각 페이지에서 PageClassifier 로 폼을 분류하고 SiteMap 에 축적한다.
    """
    classifier = classifier or PageClassifier()
    sitemap = SiteMap(base_url=base_url)

    visited: set[str] = set()
    to_visit: deque[tuple[str, int]] = deque([(base_url, 0)])
    parsed_base = urllib.parse.urlparse(base_url)

    while to_visit:
        if should_cancel and should_cancel():
            logger.info("smart_crawl: cancellation requested")
            break
        url, d = to_visit.popleft()
        if d > depth or url in visited:
            continue
        visited.add(url)

        try:
            resp = client.get(url, timeout=timeout)
            html = resp.text or ""
        except Exception:
            logger.debug("smart_crawl: failed to GET %s", url, exc_info=True)
            continue

        # 페이지 분류
        page_info = classifier.classify_page(url, html)
        sitemap.add_page(page_info)

        # 링크 추출 — 공유 유틸 사용
        for full in extract_same_origin_links(html, url, parsed_base.netloc):
            if full not in visited:
                to_visit.append((full, d + 1))

    logger.info(
        "smart_crawl: %d pages, %d forms discovered for %s",
        len(sitemap.pages),
        sum(len(p.forms) for p in sitemap.pages.values()),
        base_url,
    )
    return sitemap
