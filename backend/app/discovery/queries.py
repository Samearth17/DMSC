from dataclasses import asdict, dataclass
from app.config.profile import Profile


@dataclass(frozen=True)
class Query:
    text: str
    dimension: str
    term: str


def generate(profile: Profile, platform: str) -> list[Query]:
    """Bounded round-robin across dimensions; no Cartesian products.

    Dimensions are independent discovery lanes (OR), not implicit AND filters.
    Priority determines the order within every round. Quotes prevent a value
    such as 'OR site:example' being treated as a raw query expression.
    """
    if not profile.platforms[platform]:
        return []
    groups = sorted(((k, d) for k, d in profile.dimensions.items() if d.enabled and d.values),
                    key=lambda pair: -pair[1].priority)
    queries = [Query(value, 'saved_source', value) for value in profile.saved_sources.get(platform, [])]
    queries = queries[:profile.policies[platform].query_limit]
    seen, index = {q.text.casefold() for q in queries}, 0
    while groups and len(queries) < profile.policies[platform].query_limit:
        added = False
        for key, dimension in groups:
            if index >= len(dimension.values):
                continue
            added = True
            term = dimension.values[index]
            text = '"' + term.replace('"', ' ').replace('\\', ' ').strip() + '"'
            if text.casefold() not in seen:
                queries.append(Query(text, key, term))
                seen.add(text.casefold())
            if len(queries) == profile.policies[platform].query_limit:
                break
        if not added:
            break
        index += 1
    return queries


def plan(profile):
    return {p: [asdict(q) for q in generate(profile, p)] for p in profile.platforms}
