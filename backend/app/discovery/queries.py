from dataclasses import asdict, dataclass
from app.config.profile import Profile


@dataclass(frozen=True)
class Query:
    text: str
    dimension: str
    term: str


def generate(profile: Profile, platform: str) -> list[Query]:
    """Bounded round-robin across dimensions; no Cartesian products.

    If platform_queries are set for this platform, those are used first as
    priority search terms before falling back to the global dimension values.
    Dimensions are independent discovery lanes (OR), not implicit AND filters.
    """
    if not profile.platforms[platform]:
        return []
    limit = profile.policies[platform].query_limit
    queries = [Query(value, 'saved_source', value) for value in profile.saved_sources.get(platform, [])]
    queries = queries[:limit]
    seen = {q.text.casefold() for q in queries}

    # Platform-specific custom queries take priority
    pq = profile.platform_queries.get(platform, [])
    for term in pq:
        if len(queries) >= limit:
            break
        from app.intelligence.boolean import format_search_query
        text = format_search_query(term)
        if text.casefold() not in seen:
            queries.append(Query(text, 'platform_query', term))
            seen.add(text.casefold())

    # Then fill remaining slots from global dimensions
    groups = sorted(((k, d) for k, d in profile.dimensions.items() if d.enabled and d.values),
                    key=lambda pair: -pair[1].priority)
    index = 0
    while groups and len(queries) < limit:
        added = False
        for key, dimension in groups:
            if index >= len(dimension.values):
                continue
            added = True
            term = dimension.values[index]
            from app.intelligence.boolean import format_search_query
            text = format_search_query(term)
            if text.casefold() not in seen:
                queries.append(Query(text, key, term))
                seen.add(text.casefold())
            if len(queries) == limit:
                break
        if not added:
            break
        index += 1
    return queries


def plan(profile):
    return {p: [asdict(q) for q in generate(profile, p)] for p in profile.platforms}
