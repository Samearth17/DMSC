import re
from app.intelligence.boolean import is_boolean_query, eval_boolean_match


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
    # Relevance is a transparent objective coverage score, not a truth probability.
    weights={'keywords':1,'entities':2,'hashtags':1,'geography':2,'incident_types':2}
    active=[k for k,v in profile.active_terms().items() if v]
    score=sum(weights[k] for k in matches)/max(1,sum(weights[k] for k in active))

    transcript_status = event.metadata.get('transcript_status', 'not_configured') if isinstance(event.metadata, dict) else 'not_configured'
    if transcript_text and transcript_status == 'not_configured':
        transcript_status = 'collected'

    return {"version": "lexical-v2", "relevant": bool(matches), "matches": matches,
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
