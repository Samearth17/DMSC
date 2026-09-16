import re
from app.intelligence.boolean import is_boolean_query, eval_boolean_match


def matches_term(term, text):
    if not term or not text:
        return False
    clean = term.strip().strip('"\'').casefold()
    target = text.casefold()
    if is_boolean_query(term) or re.search(r'\s+or\s+|\s*\|\s*', term, re.IGNORECASE):
        return eval_boolean_match(term, target)
    if ' ' in clean:
        return clean in target
    pattern = r"(?<!\w)" + re.escape(clean) + r"(?!\w)"
    return bool(re.search(pattern, target))


DEFENSE_KEYWORDS = {
    "defense", "defence", "military", "army", "navy", "air force", "cantonment", "security",
    "border", "drdo", "mod", "troops", "artillery", "command", "regiment", "surveillance",
    "threat", "ammunition", "corps", "jawans", "anti-terror", "missile", "paramilitary",
    "crpf", "bsf", "cisf", "itbp", "combat", "patrol", "reconnaissance", "weapons", "radar",
    "loc", "lac", "warfare", "counter-terror", "special forces", "southern command", "northern command"
}

DEFAULT_NOISE_TERMS = [
    "ganesh", "ganpati", "visarjan", "bonalu", "festival", "lifestyle", "shopping", "outlet",
    "boutique", "discount", "real estate", "plots for sale", "wedding", "saree", "makeup",
    "celebrity", "mamera", "jamatkhana", "jewellery", "showroom", "unboxing", "vlog", "bappa"
]


def analyze(event, profile):
    content_text = (event.content or "").casefold()
    title_text = (event.title or (event.metadata.get("title") if isinstance(event.metadata, dict) else "") or "").casefold()
    transcript_text = ((event.metadata.get("transcript_text") if isinstance(event.metadata, dict) else "") or "").casefold()
    combined_text = f"{content_text} {title_text} {transcript_text}".strip()

    matches = {}
    matched_in_transcript = set()

    for dimension, terms in profile.active_terms().items():
        hits = []
        for term in terms:
            clean_term = term.strip().strip('"\'')
            if is_boolean_query(term) or re.search(r'\s+or\s+|\s*\|\s*', term, re.IGNORECASE):
                if eval_boolean_match(term, combined_text):
                    hits.append(term)
                    if transcript_text and eval_boolean_match(term, transcript_text):
                        matched_in_transcript.add(term)
            else:
                # Word boundary search if single word, phrase search if multi-word
                pattern = r"(?<!\w)" + re.escape(clean_term.casefold()) + r"(?!\w)"
                if re.search(pattern, combined_text) or (' ' in clean_term and clean_term.casefold() in combined_text):
                    hits.append(term)
                    if transcript_text and (re.search(pattern, transcript_text) or clean_term.casefold() in transcript_text):
                        matched_in_transcript.add(term)
        if hits:
            matches[dimension] = hits

    original_hashtags = list(dict.fromkeys(re.findall(r'(?<!\w)#[\w]+',event.content)))
    normalized_hashtags = list(dict.fromkeys(h.lstrip('#').casefold() for h in original_hashtags))
    
    # Topic / domain relevance configuration
    relevance_config = getattr(profile, 'relevance', {}) or {}
    mode = relevance_config.get('mode', 'defense_focus')
    exclude_terms = list(relevance_config.get('exclude_terms', []))

    # Noise exclusion check
    excluded_hits = [t for t in exclude_terms if matches_term(t, combined_text)]
    has_defense_signal = any(k in matches for k in ('keywords', 'entities', 'incident_types')) or any(matches_term(dk, combined_text) for dk in DEFENSE_KEYWORDS)
    
    if not excluded_hits and mode == 'defense_focus':
        if not has_defense_signal:
            excluded_hits = [t for t in DEFAULT_NOISE_TERMS if matches_term(t, combined_text)]

    active = [k for k, v in profile.active_terms().items() if v]
    missing = [k for k in active if k not in matches]
    
    if mode == 'all_categories':
        is_relevant = bool(active) and not missing and not excluded_hits
    elif mode == 'defense_focus':
        # If user has configured defense keywords, or record has defense signals, and not excluded
        is_relevant = bool(matches) and has_defense_signal and not excluded_hits
    else:
        is_relevant = bool(matches) and not excluded_hits

    # Relevance is a transparent objective coverage score, not a truth probability.
    weights={'keywords':1,'entities':2,'hashtags':1,'geography':2,'incident_types':2}
    score=sum(weights[k] for k in matches)/max(1,sum(weights[k] for k in active))
    if not is_relevant:
        score = min(score, 0.25)
    elif has_defense_signal:
        score = max(score, 0.8)

    reasons = []
    if excluded_hits:
        reasons.append(f"Filtered out noise / non-defense topic: {', '.join(excluded_hits[:3])}")
    if missing and mode == 'all_categories':
        reasons.append(f"Missing required categories: {', '.join(missing)}")
    if mode == 'defense_focus' and bool(matches) and not has_defense_signal:
        reasons.append("Location/hashtag matched but lacks defense/security topic signals")
    if is_relevant:
        reasons.append("Relevant defense & security intelligence match")

    transcript_status = event.metadata.get('transcript_status', 'not_configured') if isinstance(event.metadata, dict) else 'not_configured'
    if transcript_text and transcript_status == 'not_configured':
        transcript_status = 'collected'

    res = {"version": "lexical-v2", "relevant": is_relevant, "matches": matches,
            "reasons": reasons or ["Evaluated under profile rules"],
            'relevance_score':round(score,3),'score_meaning':'Weighted coverage of selected categories; not verification',
            'configured_entities':profile.active_terms().get('entities',[]),
            'matched_entities':matches.get('entities',[]),
            'extracted_entities':event.entities,'entity_extraction_method':'platform metadata; model NER not configured',
            'original_hashtags':original_hashtags,'normalized_hashtags':normalized_hashtags,
            'incident_types':matches.get('incident_types',[]),
            'processing':{'text':'unicode lexical matching','language':'undetermined',
                          'transcript':transcript_status,'vision':'not_configured'},
            "evidence_level": "Unverified", "verification_status": "not_assessed",
            "location_mentions": [{"name": name,
                                   "provenance": "transcript-derived" if name in matched_in_transcript else "text-mentioned",
                                   "confidence": 1.0,
                                   "meaning": "exact text match; not confirmed incident location"}
                                  for name in matches.get("geography", [])]}
    if getattr(profile, 'investigation', None):
        from app.intelligence.related import compare_seed
        related = compare_seed(profile.investigation, combined_text, event.url)
        res.update(related=related, relevance_score=related['score'], relevant=related['candidate'])
        res['decision'] = 'related_candidate' if res['relevant'] else 'not_related'
        res['reasons'] = related['reasons']
        res['score_meaning'] = 'Lexical overlap with the seed; candidate relationship requires human review'
    return res
