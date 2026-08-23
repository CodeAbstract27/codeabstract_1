"""
Unit tests for core/analyzer.py

Tests Exposure Score calculations, risk categorization, and secret detection metrics.
"""

import pytest
from core.analyzer import PrivacyAnalyzer, AuditReport, RiskLevel


def test_analyzer_low_risk_code():
    """Generic code without secrets should return LOW risk level and low exposure score."""
    code = """
def add_numbers(a, b):
    return a + b
"""
    analyzer = PrivacyAnalyzer(code)
    report = analyzer.analyze()

    assert isinstance(report, AuditReport)
    assert report.risk_level == RiskLevel.LOW
    assert report.exposure_score < 20.0
    assert report.secret_count == 0


def test_analyzer_high_risk_code():
    """Code with explicit secrets and passwords should return HIGH risk level."""
    code = """
AWS_SECRET_KEY = "sk_live_999888777666"
db_password = "SuperSecretPassword123"
stripe_api_key = "rk_live_111222333"
"""
    analyzer = PrivacyAnalyzer(code)
    report = analyzer.analyze()

    assert report.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    assert report.exposure_score > 50.0
    assert report.secret_count >= 2


def test_analyzer_empty_code():
    """Empty code should safely return 0.0 exposure score and LOW risk."""
    analyzer = PrivacyAnalyzer("")
    report = analyzer.analyze()

    assert report.exposure_score == 0.0
    assert report.risk_level == RiskLevel.LOW


def test_analyzer_invalid_syntax():
    """Invalid Python syntax should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid Python syntax"):
        analyzer = PrivacyAnalyzer("def invalid_function(:")
        analyzer.analyze()
