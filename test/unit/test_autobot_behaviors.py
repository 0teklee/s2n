import logging
import pytest
from unittest.mock import Mock, patch

from s2n.s2nscanner.plugins.autobot.autobot_behaviors import (
    RapidCrawlBehavior,
    HeadlessSignalBehavior,
    NoUserInteractionBehavior,
    RepetitiveQueryBehavior,
    load_behaviors,
)


@pytest.fixture
def mock_driver():
    driver = Mock()
    driver.execute_script.return_value = True  # For HeadlessSignalBehavior
    driver.find_elements.return_value = [Mock()]  # For NoUserInteractionBehavior form submit
    return driver


@pytest.fixture
def logger():
    return logging.getLogger("test_logger")


def test_rapid_crawl_behavior(mock_driver, logger):
    behavior = RapidCrawlBehavior()
    
    # 1. Blocked
    with patch("s2n.s2nscanner.plugins.autobot.autobot_detector.is_blocked", return_value=(True, "Blocked by WAF")):
        result = behavior.execute(mock_driver, "http://target.com", logger)
        assert result.behavior_name == "rapid_crawl"
        assert result.was_blocked is True
        assert "Blocked by WAF" in result.evidence
        assert result.requests_sent == 1

    # 2. Not blocked
    with patch("s2n.s2nscanner.plugins.autobot.autobot_detector.is_blocked", return_value=(False, "")):
        result = behavior.execute(mock_driver, "http://target.com", logger, target_urls=["url1", "url2"])
        assert result.behavior_name == "rapid_crawl"
        assert result.was_blocked is False
        assert "차단 미탐지" in result.evidence
        assert result.requests_sent == 2


def test_headless_signal_behavior(mock_driver, logger):
    behavior = HeadlessSignalBehavior()

    with patch("s2n.s2nscanner.plugins.autobot.autobot_detector.is_blocked", return_value=(True, "WebDriver Flag Detected")):
        result = behavior.execute(mock_driver, "http://target.com", logger)
        assert result.was_blocked is True
        assert "navigator.webdriver=" in result.evidence
        assert result.requests_sent == 1


def test_no_user_interaction_behavior(mock_driver, logger):
    behavior = NoUserInteractionBehavior()

    with patch("s2n.s2nscanner.plugins.autobot.autobot_detector.is_blocked", return_value=(False, "")):
        result = behavior.execute(mock_driver, "http://target.com", logger)
        assert result.was_blocked is False
        assert result.requests_sent == 2  # 1 (get) + 1 (form.submit())


def test_repetitive_query_behavior(mock_driver, logger):
    behavior = RepetitiveQueryBehavior()
    behavior.DELAY_SECONDS = 0  # To speed up tests

    with patch("s2n.s2nscanner.plugins.autobot.autobot_detector.is_blocked", return_value=(True, "429 Too Many Requests")):
        result = behavior.execute(mock_driver, "http://target.com", logger)
        # Should stop early
        assert result.was_blocked is True
        assert result.requests_sent == 1
        assert "차단 감지" in result.evidence

    with patch("s2n.s2nscanner.plugins.autobot.autobot_detector.is_blocked", return_value=(False, "")):
        result = behavior.execute(mock_driver, "http://target.com", logger)
        # Should execute all times
        assert result.requests_sent == 10
        assert result.was_blocked is False


def test_load_behaviors():
    names = ["rapid_crawl", "invalid_behavior"]
    behaviors = load_behaviors(names)
    assert len(behaviors) == 1
    assert isinstance(behaviors[0], RapidCrawlBehavior)
