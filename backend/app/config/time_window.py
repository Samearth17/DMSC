"""Timezone-aware publication filtering; collection time is never a substitute."""
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def instant(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('Timestamps must include a UTC offset')
    return dt.astimezone(timezone.utc)


@dataclass
class TimeWindow:
    hours: int | None = 24
    start_time: str | None = None
    end_time: str | None = None
    timezone: str = 'Asia/Kolkata'

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict) or set(data) - {'hours', 'start_time', 'end_time', 'timezone'}:
            raise ValueError('Invalid time window')
        window = cls(**data)
        try:
            ZoneInfo(window.timezone)
        except (ZoneInfoNotFoundError, TypeError, ValueError):
            raise ValueError('Choose a valid IANA timezone') from None
        if window.hours is not None:
            if type(window.hours) is not int or window.hours not in (1, 6, 12, 24, 48, 168, 720):
                raise ValueError('Choose a supported relative time window')
            if window.start_time is not None or window.end_time is not None:
                raise ValueError('Relative windows cannot also specify dates')
        else:
            try:
                if not window.start_time:
                    raise ValueError('Custom time windows require a start date/time')
                start = instant(window.start_time)
                end = instant(window.end_time) if window.end_time else datetime.now(timezone.utc)
            except (ValueError, TypeError, AttributeError) as e:
                raise ValueError(f'Invalid date/time for time window: {e}') from None
            if start >= end:
                raise ValueError('Start time must precede end time')
            window.start_time, window.end_time = start.isoformat(), end.isoformat()
        return window

    def resolve(self, at=None):
        if self.hours is None:
            return self
        end = at or datetime.now(timezone.utc)
        return TimeWindow(None, (end-timedelta(hours=self.hours)).isoformat(), end.isoformat(), self.timezone)

    def classify(self, published_at):
        try:
            published = instant(published_at)
        except (ValueError, TypeError, AttributeError):
            return 'UNKNOWN_TIME'
        resolved = self.resolve()
        if published < instant(resolved.start_time):
            return 'STALE'
        if published > instant(resolved.end_time):
            return 'AFTER_WINDOW'
        return 'CURRENT'

    def snapshot(self):
        return asdict(self)
