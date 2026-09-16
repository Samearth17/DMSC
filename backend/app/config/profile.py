from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
from app.config.time_window import TimeWindow

DIMENSIONS = ("geography", "entities", "keywords", "hashtags", "incident_types")
PLATFORMS = ("youtube", "instagram", "x", "reddit", "meta", "news", "web")


@dataclass
class Dimension:
    enabled: bool = False
    values: list[str] = field(default_factory=list)
    priority: int = 50  # Larger first; equal priorities retain declared order.


@dataclass
class Policy:
    query_limit: int = 8
    items_per_query: int = 10
    min_interval_seconds: float = 2.0
    timeout_seconds: int = 45
    retries: int = 1
    backoff_seconds: float = 2.0
    cache_ttl_seconds: int = 900
    pages_per_query: int = 5


@dataclass
class Profile:
    name: str
    dimensions: dict[str, Dimension]
    platforms: dict[str, bool]
    policies: dict[str, Policy]
    time_window: TimeWindow = field(default_factory=TimeWindow)
    saved_sources: dict[str, list[str]] = field(default_factory=dict)
    platform_queries: dict[str, list[str]] = field(default_factory=dict)
    relevance: dict = field(default_factory=lambda: {'mode': 'all_categories', 'exclude_terms': []})
    investigation: dict = field(default_factory=dict)

    def snapshot(self):
        return asdict(self)

    def active_terms(self):
        return {k: d.values for k, d in self.dimensions.items() if d.enabled}

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict):
            raise ValueError("Profile must be a mapping")
        unknown = set(data) - {"name", "dimensions", "platforms", "policies", "time_window", "saved_sources", "platform_queries", "relevance", "investigation"}
        if unknown:
            raise ValueError(f"Unknown profile fields: {sorted(unknown)}")
        name = data.get("name", "Local profile")
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise ValueError("name must be a non-empty string of up to 120 characters")
        groups = {}
        for key, allowed in (("dimensions", DIMENSIONS), ("platforms", PLATFORMS), ("policies", PLATFORMS)):
            group = data.get(key, {})
            if not isinstance(group, dict) or set(group) - set(allowed):
                raise ValueError(f"Invalid {key} names or structure")
            groups[key] = group
        dimensions = {}
        for key in DIMENSIONS:
            d = groups["dimensions"].get(key, {})
            if not isinstance(d, dict) or set(d) - {"enabled", "values", "priority"}:
                raise ValueError(f"Invalid dimension: {key}")
            enabled, values, priority = d.get("enabled", False), d.get("values", []), d.get("priority", 50)
            if type(enabled) is not bool or not isinstance(values, list) or len(values) > 1000:
                raise ValueError(f"Invalid enabled/values: {key}")
            if type(priority) is not int or not 0 <= priority <= 100:
                raise ValueError("priority must be an integer from 0 to 100")
            clean, seen = [], set()
            for value in values:
                if not isinstance(value, str) or not value.strip() or len(value) > 200:
                    raise ValueError("Values must be non-empty strings of up to 200 characters")
                value = " ".join(value.split())
                if value.casefold() not in seen:
                    clean.append(value)
                    seen.add(value.casefold())
            dimensions[key] = Dimension(enabled, clean, priority)
        platforms, policies = {}, {}
        bounds = {"query_limit": (1, 100), "items_per_query": (1, 100),
                  "min_interval_seconds": (0, 300), "timeout_seconds": (1, 300),
                  "retries": (0, 3), "backoff_seconds": (0, 60), "cache_ttl_seconds": (0, 86400),
                  "pages_per_query": (0, 10)}
        for key in PLATFORMS:
            enabled = groups["platforms"].get(key, False)
            if type(enabled) is not bool:
                raise ValueError(f"platforms.{key} must be true or false")
            platforms[key] = enabled
            raw = groups["policies"].get(key, {})
            if not isinstance(raw, dict) or set(raw) - set(bounds):
                raise ValueError(f"Invalid policy: {key}")
            for k, v in raw.items():
                integer = k not in {"min_interval_seconds", "backoff_seconds"}
                if type(v) not in ((int,) if integer else (int, float)) or not bounds[k][0] <= v <= bounds[k][1]:
                    raise ValueError(f"Invalid policy value: {key}.{k}")
            defaults = {"instagram": {"timeout_seconds": 60}, "web": {"pages_per_query": 5}}.get(key, {})
            policies[key] = Policy(**{**defaults, **raw})
        saved = data.get('saved_sources', {})
        if not isinstance(saved, dict) or set(saved) - {'news', 'instagram'}:
            raise ValueError('Invalid saved sources')
        from urllib.parse import urlsplit
        import re
        for platform, values in saved.items():
            if not isinstance(values, list) or len(values) > 100:
                raise ValueError('Limit saved sources to 100 per platform')
            for value in values:
                if not isinstance(value, str) or len(value) > 2048:
                    raise ValueError('Invalid source')
                if platform == 'instagram' and not re.fullmatch(r'[A-Za-z0-9_.]{1,30}', value):
                    raise ValueError('Enter an Instagram username without @')
                if platform == 'news':
                    u = urlsplit(value)
                    if u.scheme not in {'http','https'} or not u.hostname or u.username or u.password or u.port not in (None,80,443):
                        raise ValueError('Feed must be a public HTTP(S) URL without credentials')
        pq = data.get('platform_queries', {})
        if not isinstance(pq, dict) or set(pq) - set(PLATFORMS):
            raise ValueError('Invalid platform_queries')
        platform_queries = {}
        for plat, qlist in pq.items():
            if not isinstance(qlist, list) or len(qlist) > 50:
                raise ValueError(f'platform_queries.{plat} must be a list of up to 50 terms')
            clean = []
            for q in qlist:
                if not isinstance(q, str) or not q.strip() or len(q) > 500:
                    raise ValueError('Each platform query must be a non-empty string up to 500 chars')
                clean.append(q.strip())
            platform_queries[plat] = clean
        relevance = data.get('relevance', {'mode': 'all_categories', 'exclude_terms': []})
        if not isinstance(relevance, dict) or set(relevance) - {'mode', 'exclude_terms'} or relevance.get('mode', 'all_categories') not in {'all_categories', 'any_category'}:
            relevance = {'mode': 'all_categories', 'exclude_terms': []}
        exclusions = relevance.get('exclude_terms', [])
        if not isinstance(exclusions, list) or len(exclusions) > 100 or any(not isinstance(t, str) or not t.strip() or len(t) > 200 for t in exclusions):
            exclusions = []
        investigation = data.get('investigation', {})
        if investigation:
            from app.intelligence.related import validate_seed
            investigation = validate_seed(investigation)
        return cls(name.strip(), dimensions, platforms, policies,
                   TimeWindow.parse(data.get('time_window', {})), saved, platform_queries,
                   {'mode': relevance.get('mode', 'all_categories'), 'exclude_terms': exclusions}, investigation)


def load_profile(path):
    path = Path(path)
    content = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return Profile.parse(json.loads(content))
    import yaml
    return Profile.parse(yaml.safe_load(content))
