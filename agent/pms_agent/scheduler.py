"""Jobs that run once a day at a set time (in PMS_TIMEZONE): preparing the day's recommendations,
then the daily email and scheduled reports."""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, tzinfo

log = logging.getLogger(__name__)

TIME = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")


def next_run(now: datetime, at: str, default: str = "07:00") -> datetime:
    """The next time it's `at` (HH:MM) after `now`; `default` if `at` isn't a time."""
    match = TIME.fullmatch(at.strip()) or TIME.fullmatch(default)
    run = now.replace(hour=int(match[1]), minute=int(match[2]), second=0, microsecond=0)
    return run if run > now else run + timedelta(days=1)


async def every_day(zone: tzinfo, at: str, job: Callable[[], Awaitable[object]], name: str) -> None:
    log.info("%s every day at %s (%s)", name, at, zone)
    while True:
        now = datetime.now(zone)
        await asyncio.sleep((next_run(now, at) - now).total_seconds())
        try:
            log.info("%s: %s", name, await job())
        except Exception:
            log.exception("%s failed", name)
