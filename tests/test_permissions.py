from unittest.mock import patch

from telemetry.permissions import check_permissions


def test_check_permissions_reports_missing_input_monitoring():
    with patch("telemetry.permissions._input_monitoring_checker", return_value=False), \
         patch("telemetry.permissions._accessibility_checker", return_value=True):
        assert check_permissions() == ["Input Monitoring"]


def test_check_permissions_reports_missing_accessibility():
    with patch("telemetry.permissions._input_monitoring_checker", return_value=True), \
         patch("telemetry.permissions._accessibility_checker", return_value=False):
        assert check_permissions() == ["Accessibility"]


def test_check_permissions_reports_both_missing():
    with patch("telemetry.permissions._input_monitoring_checker", return_value=False), \
         patch("telemetry.permissions._accessibility_checker", return_value=False):
        assert check_permissions() == ["Input Monitoring", "Accessibility"]


def test_check_permissions_reports_none_missing():
    with patch("telemetry.permissions._input_monitoring_checker", return_value=True), \
         patch("telemetry.permissions._accessibility_checker", return_value=True):
        assert check_permissions() == []


def test_check_permissions_returns_empty_on_non_macos():
    """On non-macOS, the checkers are None so check_permissions returns []."""
    with patch("telemetry.permissions._input_monitoring_checker", None), \
         patch("telemetry.permissions._accessibility_checker", None):
        assert check_permissions() == []
