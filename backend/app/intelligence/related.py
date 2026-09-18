"""Seed-driven coverage discovery. Bounded search, no claim of exhaustive coverage."""
import re
import unicodedata
from collections import Counter
from urllib.parse import urlsplit

STOP = set("""
the a an and or of to in on at for from with by is are was were be been being this that it as has have had news breaking latest update updates said says report reported reports today video watch new who whom whose which when where why how after before while during into onto over under out up down about between through against among because although though if then else but nor yet so very also just more most other some any all each every both few many much own same such than too can could will would shall should may might must friday saturday sunday monday tuesday wednesday thursday month months year years week weeks day days hour hours minute minutes time times press conference development official officials source sources according claim claims claimed claiming arrested arrest told tells added adding director general officer commanding chief minister police
""".split())


def tokens(text):
    text = unicodedata.normalize('NFC', text).casefold()
    return [t for t in re.findall(r'[^\W_]+', text, flags=re.UNICODE) if len(t) > 2 and t not in STOP]


def validate_seed(data):
    if not isinstance(data, dict) or set(data) - {'text', 'url', 'anchors'}:
        raise ValueError('Seed supports text, url and anchors')
    text = data.get('text', '')
    url = data.get('url', '')
    anchors = data.get('anchors', [])
    if not isinstance(text, str) or not 20 <= len(text.strip()) <= 20000:
        raise ValueError('Paste or upload 20–20,000 characters of news text')
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError('Invalid seed URL')
    if url:
        p = urlsplit(url)
        if p.scheme not in {'https', 'http'} or not p.hostname or p.username or p.password:
            raise ValueError('Use a public HTTP(S) seed URL without credentials')
    if not isinstance(anchors, list) or not 2 <= len(anchors) <= 8 or any(not isinstance(a, str) or not 2 <= len(a.strip()) <= 100 for a in anchors):
        raise ValueError('Choose 2–8 distinguishing names, places or issue terms')
    anchors = list(dict.fromkeys(' '.join(a.split()) for a in anchors))
    if len(anchors) < 2:
        raise ValueError('Choose at least two different anchors')
    return {'text': text.strip(), 'url': url, 'anchors': anchors}


def suggest_anchors(text):
    caps = re.findall(r'\b[A-Z][a-zA-Z0-9]*(?:\s+[A-Z][a-zA-Z0-9]*)*\b', text)
    codes = re.findall(r'\b[A-Z0-9]+(?:-[A-Z0-9]+)+\b', text)
    toks = tokens(text)

    candidates = []
    # Add distinctive capitalized terms
    for c in caps:
        c = c.strip()
        if c.casefold() in STOP or len(c) < 3:
            continue
        if not any(c.casefold() in x.casefold() or x.casefold() in c.casefold() for x in candidates):
            candidates.append(c)

    for code in codes:
        if code not in candidates:
            candidates.append(code)

    for t, _ in Counter(toks).most_common(10):
        m = re.search(r'\b' + re.escape(t) + r'\b', text, re.IGNORECASE)
        word = m.group(0) if m else t
        if not any(word.casefold() in x.casefold() for x in candidates):
            candidates.append(word)

    if len(candidates) < 2:
        for t in toks:
            if t not in candidates:
                candidates.append(t)
            if len(candidates) >= 4:
                break
    return candidates[:5]


def compare_seed(seed, text, url):
    from app.intelligence.rules import matches_term
    seed_words = set(tokens(seed['text']))
    target = set(tokens(text))
    shared = sorted(seed_words & target)
    hits = [a for a in seed['anchors'] if matches_term(a, text)]
    missing = [a for a in seed['anchors'] if a not in hits]

    target_cov = len(shared) / max(1, len(target))
    seed_cov = len(shared) / max(1, min(len(seed_words), 40))
    coverage = round((target_cov + seed_cov) / 2, 3)

    anchor_score = len(hits) / max(1, len(seed['anchors']))
    score = round(0.55 * anchor_score + 0.45 * coverage, 3)
    same = bool(seed.get('url')) and seed['url'].rstrip('/') == url.rstrip('/')

    # A record is a candidate if it matches at least one distinguishing anchor, shares >=2 tokens, and passes score threshold
    candidate = len(hits) >= 1 and len(shared) >= 2 and score >= 0.20 and not same
    return {
        'score': score,
        'candidate': candidate,
        'matched_anchors': hits,
        'missing_anchors': missing,
        'shared_terms': shared,
        'same_seed': same,
        'relationship': 'candidate_related_coverage' if candidate else 'seed_record' if same else 'insufficient_overlap',
        'reasons': (['Original seed URL, not additional coverage'] if same else [
            'Required anchors: ' + ', '.join(hits or ['none']),
            'Missing anchors: ' + ', '.join(missing or ['none']),
            'Shared content terms: ' + str(len(shared)),
            'Same-event identity and independence are not verified'
        ])
    }


def build_profile(base, data):
    from app.config.profile import Profile
    seed = validate_seed(data.get('seed', {}))
    platforms = data.get('platforms', {'news': True, 'web': True})
    if not isinstance(platforms, dict):
        raise ValueError('Select platforms')
    snapshot = base.snapshot()
    snapshot.update(
        name='Related coverage',
        dimensions={},
        saved_sources={},
        platform_queries={},
        platforms=platforms,
        investigation=seed,
        relevance={'mode': 'all_categories', 'exclude_terms': []},
        time_window=data.get('time_window', {'hours': 168})
    )
    # Conjoin distinguishing anchors for query generation. Use top 2 most specific terms if >2 anchors.
    anchors = seed['anchors']
    target_anchors = anchors[:2] if len(anchors) >= 2 else anchors
    query = ' AND '.join('"' + a.replace('"', ' ') + '"' for a in target_anchors)
    for platform, enabled in platforms.items():
        if enabled:
            snapshot['platform_queries'][platform] = [query]
    return Profile.parse(snapshot)
