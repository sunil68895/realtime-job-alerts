"""Read the private env file and validate the job-alert cron schedule."""

import re
from pathlib import Path


CRON_FIELDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
_ENV_KEY = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_CRON_ATOM = re.compile(r"^(\*|\d+(?:-\d+)?)(?:/(\d+))?$")


def read_env_file(path: Path) -> dict:
    """Read KEY=VALUE entries from a simple env file."""
    values = {}
    with path.open(encoding="utf-8") as env_file:
        for line_number, raw_line in enumerate(env_file, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if not separator or not _ENV_KEY.fullmatch(key):
                raise ValueError(f"Invalid env-file entry on line {line_number}")
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            elif value.startswith(("'", '"')) or value.endswith(("'", '"')):
                raise ValueError(f"Unmatched quote in env-file line {line_number}")
            values[key] = value
    return values


def validate_cron_expression(expression: str) -> str:
    """Validate a numeric five-field cron expression and return its normalized form."""
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("JOB_ALERTS_CRON must have five cron fields")

    for field, (minimum, maximum) in zip(fields, CRON_FIELDS):
        for atom in field.split(","):
            match = _CRON_ATOM.fullmatch(atom)
            if not match:
                raise ValueError(f"Invalid cron field: {field}")
            base, step = match.groups()
            if step and int(step) == 0:
                raise ValueError(f"Cron step must be greater than zero: {field}")
            if base == "*":
                continue
            bounds = base.split("-", maxsplit=1)
            start = int(bounds[0])
            end = int(bounds[-1])
            if not minimum <= start <= maximum or not minimum <= end <= maximum or start > end:
                raise ValueError(f"Cron value out of range: {field}")
            if len(bounds) == 1 and step:
                raise ValueError(f"Cron step requires '*' or a range: {field}")

    return " ".join(fields)
