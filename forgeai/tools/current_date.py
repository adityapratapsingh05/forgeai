"""Current date/time tool for date-relative reasoning."""

from __future__ import annotations

import json
from datetime import datetime, timezone


def current_date_tool() -> str:
    """Return current local and UTC date/time metadata."""
    now_local = datetime.now().astimezone()
    now_utc = datetime.now(timezone.utc)
    return json.dumps(
        {
            "local_date": now_local.date().isoformat(),
            "local_datetime": now_local.isoformat(timespec="seconds"),
            "weekday": now_local.strftime("%A"),
            "utc_date": now_utc.date().isoformat(),
        }
    )
