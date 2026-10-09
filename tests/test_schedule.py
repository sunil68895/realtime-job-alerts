import pytest

from alerts.schedule import read_env_file, validate_cron_expression
from scripts.install_cron import BEGIN_MARKER, END_MARKER, replace_managed_entry


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
