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

    # A record is a candidate if it matches at least 2 anchors, or 1 anchor with strong story token overlap (>= 3 terms, score >= 0.20)
    is_candidate = (
        not same and
        score >= 0.18 and
        (len(hits) >= 2 or (len(hits) >= 1 and len(shared) >= 3 and score >= 0.20))
    )

    relationship = 'candidate_related_coverage' if is_candidate else 'seed_record' if same else 'insufficient_overlap'

    if is_candidate:
        reasons = [
            f"Candidate related coverage ({int(score * 100)}% story overlap)",
            f"Matched anchors ({len(hits)}/{len(seed['anchors'])}): " + ', '.join(hits),
            f"Shared story terms: {len(shared)} (" + ', '.join(shared[:6]) + ('...' if len(shared) > 6 else '') + ')',
            "Same-event identity and independence should be verified"
        ]
    elif same:
        reasons = ['Original seed URL, not additional coverage']
    else:
        reasons = [
            'Insufficient overlap with news story',
            'Matched anchors: ' + (', '.join(hits) if hits else 'none'),
            'Missing anchors: ' + ', '.join(missing or ['none']),
            f'Shared story terms: {len(shared)}'
        ]

    return {
        'score': score,
        'candidate': is_candidate,
        'matched_anchors': hits,
        'missing_anchors': missing,
        'shared_terms': shared,
        'same_seed': same,
        'relationship': relationship,
        'reasons': reasons
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


def suggest_weighted_anchors(title, paragraphs):
    lead_strip = re.compile(r'^(?:behind|after|inside|in|on|at|how|why|what|when|where|who)\s+', re.I)
    clean_title = lead_strip.sub('', title)
    title_caps = re.findall(r'\b[A-Z][a-zA-Z0-9]*(?:\s+[A-Z][a-zA-Z0-9]*)*\b', clean_title)
    body_text = ' '.join(paragraphs[:12]) if isinstance(paragraphs, list) else str(paragraphs)
    body_caps = re.findall(r'\b[A-Z][a-zA-Z0-9]*(?:\s+[A-Z][a-zA-Z0-9]*)*\b', body_text)
    codes = re.findall(r'\b(?:[A-Z0-9]+-[A-Z0-9]+|\d+\s+[A-Z][a-z]+)\b', title + ' ' + body_text)

    STOP_WORDS = STOP | {'days', 'hours', 'minutes', 'weeks', 'months', 'years', 'after', 'before', 'inside', 'behind', 'under', 'over', 'during', 'amid', 'into', 'with', 'per', 'via', 'news'}

    candidates = []

    def add_cand(phrase):
        words = phrase.strip().split()
        while words and words[0].casefold() in STOP_WORDS:
            words.pop(0)
        while words and words[-1].casefold() in STOP_WORDS:
            words.pop(-1)
        if not words:
            return
        cand = ' '.join(words)
        if len(cand) < 3 or cand.casefold() in STOP_WORDS:
            return
        if not any(cand.casefold() in x.casefold() or x.casefold() in cand.casefold() for x in candidates):
            candidates.append(cand)

    # 1. Designation / weapon / military codes (e.g. 20 Madras, AK-203)
    for code in codes:
        add_cand(code)

    # 2. Headline capitalized multi-word entities and names (highest priority)
    for c in title_caps:
        add_cand(c)

    # 3. Capitalized terms in lead paragraphs
    for c in body_caps:
        add_cand(c)

    # 4. Weighted content tokens: Heading words receive 4x multiplier over body words
    title_toks = tokens(title) * 4
    body_toks = tokens(body_text)
    for t, _ in Counter(title_toks + body_toks).most_common(15):
        m = re.search(r'\b' + re.escape(t) + r'\b', title + ' ' + body_text, re.IGNORECASE)
        word = m.group(0) if m else t
        add_cand(word)

    if len(candidates) < 2:
        for t in tokens(title + ' ' + body_text):
            add_cand(t)
            if len(candidates) >= 4:
                break
    return candidates[:6]


def fetch_article_from_url(url):
    import html as html_lib
    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError

    if not isinstance(url, str) or not url.strip():
        raise ValueError("Please provide a valid article URL")
    url = url.strip()
    p = urlsplit(url)
    if p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password:
        raise ValueError("Use a public HTTP(S) news URL without credentials")

    # Multi-user-agent strategy to bypass aggressive news bot filters
    ua_candidates = [
        'facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
        'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        'Twitterbot/1.0'
    ]

    raw_html = None
    final_url = url
    for ua in ua_candidates:
        headers = {
            'User-Agent': ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9'
        }
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=8) as resp:
                content_type = resp.headers.get('Content-Type', '')
                if 'text/html' in content_type or 'text/plain' in content_type:
                    data = resp.read(4 * 1024 * 1024 + 1).decode('utf-8', errors='replace')
                    if len(data) > 1500 and "Just a moment" not in data[:600]:
                        raw_html = data
                        final_url = resp.geturl()
                        break
        except Exception:
            continue

    # Fallback to Jina Reader if direct scrape was challenged/blocked
    if not raw_html:
        try:
            jina_url = f"https://r.jina.ai/{url}"
            req = Request(jina_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urlopen(req, timeout=10) as resp:
                jina_text = resp.read(4 * 1024 * 1024).decode('utf-8', errors='replace')
                if len(jina_text) > 200 and "Target URL returned error" not in jina_text[:300]:
                    lines = [line.strip() for line in jina_text.split('\n') if line.strip()]
                    title = ""
                    for line in lines:
                        if line.lower().startswith('title:'):
                            title = line.split(':', 1)[1].strip()
                            break
                    paras = [line for line in lines if len(line) > 50 and not line.startswith('http') and not line.startswith('![')]
                    if not title and paras:
                        title = paras[0][:100]
                    clean_paras = paras[1:] if title in (paras[:1] or []) else paras
                    combined = (title + '\n\n' + '\n\n'.join(clean_paras[:12])).strip()
                    if len(combined) >= 20:
                        anchors = suggest_weighted_anchors(title, clean_paras)
                        return {
                            'url': url,
                            'title': title,
                            'published_at': None,
                            'paragraphs_count': len(clean_paras),
                            'text': combined[:20000],
                            'anchors': anchors
                        }
        except Exception:
            pass

    if not raw_html:
        raise ValueError("Could not access article content from this URL. Please check the link or paste article text directly.")

    # Strip non-content blocks (header, nav, footer, aside, scripts)
    html_clean = re.sub(r'<(header|footer|nav|aside|script|style|noscript)[^>]*>.*?</\1>', '', raw_html, flags=re.I | re.S)

    # Title extraction
    og_title = re.search(r'<meta\s+property=[\"\']og:title[\"\']\s+content=[\"\'](.*?)[\"\']', html_clean, re.I)
    title = html_lib.unescape(og_title.group(1)) if og_title else ''
    if not title:
        m = re.search(r'<h1[^>]*>(.*?)</h1>', html_clean, re.I | re.S)
        title = html_lib.unescape(re.sub(r'<[^>]+>', '', m.group(1))) if m else ''
    if not title:
        m = re.search(r'<title[^>]*>(.*?)</title>', html_clean, re.I | re.S)
        title = html_lib.unescape(m.group(1)) if m else ''

    title = re.sub(r'\s*[-|–—:]\s*(The Indian Express|The Hindu|NDTV|Times of India|News18|ThePrint|India Today|Hindustan Times|Deccan Chronicle|Telangana Today|NewsMeter|The Wire|Livemint|Economic Times).*$', '', title, flags=re.I).strip()
    title = re.sub(r'\s+', ' ', title)

    # Published date extraction
    pub_match = re.search(r'<meta\s+(?:property|name)=[\"\'](?:article:published_time|publish-date|date|pubdate|parsely-pub-date)[\"\']\s+content=[\"\'](.*?)[\"\']', html_clean, re.I)
    published_at = pub_match.group(1).strip() if pub_match else None
    if not published_at:
        m = re.search(r'<time[^>]*datetime=[\"\'](.*?)[\"\']', html_clean, re.I)
        published_at = m.group(1).strip() if m else None

    # Paragraphs extraction
    paras = re.findall(r'<p[^>]*>(.*?)</p>', html_clean, re.I | re.S)
    clean_paras = []
    boiler_filter = ['cookie', 'subscribe', 'all rights reserved', 'read also', 'sign in', 'download app', 'newsletter', 'privacy policy', 'terms of service', 'advertisement']
    social_nav = {'facebook', 'instagram', 'linkedin', 'twitter', 'youtube', 'whatsapp', 'telegram', 'pinterest'}
    for p_tag in paras:
        clean = html_lib.unescape(re.sub(r'<[^>]+>', '', p_tag)).strip()
        clean = re.sub(r'\s+', ' ', clean)
        if len(clean) < 40:
            continue
        lower = clean.lower()
        if any(k in lower for k in boiler_filter):
            continue
        if sum(1 for s in social_nav if s in lower) >= 2:
            continue
        if any(len(w) > 30 for w in clean.split()):
            continue
        clean_paras.append(clean)

    combined_text = (title + '\n\n' + '\n\n'.join(clean_paras[:12])).strip()
    if len(combined_text) < 20:
        raise ValueError("Could not extract readable article text from the URL. Please paste text directly.")

    anchors = suggest_weighted_anchors(title, clean_paras)

    return {
        'url': final_url,
        'title': title,
        'published_at': published_at,
        'paragraphs_count': len(clean_paras),
        'text': combined_text[:20000],
        'anchors': anchors
    }

