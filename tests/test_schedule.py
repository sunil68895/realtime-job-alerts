import os

import pytest

from alerts.logging_setup import configure_logging
from alerts.schedule import read_env_file, validate_cron_expression
from scripts.install_cron import (
    BEGIN_MARKER,
    END_MARKER,
    ensure_log_link,
    replace_managed_entry,
)


def test_read_env_file_supports_comments_whitespace_and_quotes(tmp_path):
    env_file = tmp_path / "job-alerts.env"
    env_file.write_text(
        '# private settings\nJOB_ALERTS_CRON="*/10 * * * *"\nTELEGRAM_CHAT_ID = "-100123"\n',
        encoding="utf-8",
    )

    assert read_env_file(env_file) == {
        "JOB_ALERTS_CRON": "*/10 * * * *",
        "TELEGRAM_CHAT_ID": "-100123",
    }


@pytest.mark.parametrize("expression", [
    "*/10 * * * *",
    "7 * * * *",
    "0 8-18/2 * 1,6 1-5",
])
def test_validate_cron_expression_accepts_valid_numeric_schedules(expression):
    assert validate_cron_expression(expression) == expression


@pytest.mark.parametrize("expression", [
    "",
    "*/10 * * *",
    "60 * * * *",
    "0 24 * * *",
    "*/0 * * * *",
    "* * * * *; touch /tmp/bad",
])
def test_validate_cron_expression_rejects_invalid_schedules(expression):
    with pytest.raises(ValueError):
        validate_cron_expression(expression)


def test_replace_managed_entry_preserves_unrelated_entries():
    existing = "MAILTO=alerts@example.com\n0 2 * * * /backup\n"
    updated = replace_managed_entry(existing, "*/10 * * * * /job-alerts")

    assert updated == (
        "MAILTO=alerts@example.com\n"
        "0 2 * * * /backup\n"
        f"{BEGIN_MARKER}\n"
        "*/10 * * * * /job-alerts\n"
        f"{END_MARKER}\n"
    )


def test_replace_managed_entry_replaces_existing_schedule():
    existing = f"{BEGIN_MARKER}\n0 * * * * /old\n{END_MARKER}\n"
    updated = replace_managed_entry(existing, "*/10 * * * * /new")

    assert updated.count(BEGIN_MARKER) == 1
    assert "0 * * * * /old" not in updated
    assert "*/10 * * * * /new" in updated


def test_ensure_log_link_points_to_persistent_log_directory(tmp_path):
    project = tmp_path / "project"
    state_dir = tmp_path / "state" / "job-alerts"
    project.mkdir()
    state_dir.mkdir(parents=True)

    link = ensure_log_link(project, state_dir)

    assert link.is_symlink()
    assert link.resolve() == state_dir.resolve()
    assert ensure_log_link(project, state_dir) == link


def test_ensure_log_link_refuses_unmanaged_existing_path(tmp_path):
    project = tmp_path / "project"
    state_dir = tmp_path / "state"
    project.mkdir()
    state_dir.mkdir()
    (project / "logs").mkdir()

    with pytest.raises(ValueError, match="not the managed log symlink"):
        ensure_log_link(project, state_dir)


def test_logging_rotates_hourly_and_removes_only_logs_older_than_five_days(tmp_path):
    old_log = tmp_path / "job-alerts.log.2020-01-01_00"
    unrelated_log = tmp_path / "other.log.2020-01-01_00"
    old_log.write_text("old", encoding="utf-8")
    unrelated_log.write_text("keep", encoding="utf-8")
    old_log.touch()
    os.utime(old_log, (1, 1))

    logger = configure_logging(tmp_path)
    logger.info("successful fetch: company=Example jobs=3")
    handler = next(h for h in logger.handlers if hasattr(h, "when"))
    try:
        assert handler.when == "H"
        assert handler.interval == 3600
        assert (tmp_path / "job-alerts.log").read_text(encoding="utf-8").find("successful fetch") >= 0
        assert not old_log.exists()
        assert unrelated_log.exists()
    finally:
        for active_handler in logger.handlers[:]:
            logger.removeHandler(active_handler)
            active_handler.close()
