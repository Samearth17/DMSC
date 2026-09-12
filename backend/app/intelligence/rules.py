"""Transparent lexical relevance only; no geopolitical or truth inference."""
import re


def analyze(event, profile):
    text = event.content.casefold()
    matches = {}
    for dimension, terms in profile.active_terms().items():
        hits = [term for term in terms if re.search(r"(?<!\w)" + re.escape(term.casefold()) + r"(?!\w)", text)]
        if hits:
            matches[dimension] = hits
    original_hashtags = list(dict.fromkeys(re.findall(r'(?<!\w)#[\w]+',event.content)))
    normalized_hashtags = list(dict.fromkeys(h.lstrip('#').casefold() for h in original_hashtags))
    # Relevance is a transparent objective coverage score, not a truth probability.
    weights={'keywords':1,'entities':2,'hashtags':1,'geography':2,'incident_types':2}
    active=[k for k,v in profile.active_terms().items() if v]
    score=sum(weights[k] for k in matches)/max(1,sum(weights[k] for k in active))
    return {"version": "lexical-v2", "relevant": bool(matches), "matches": matches,
            'relevance_score':round(score,3),'score_meaning':'Weighted coverage of selected categories; not verification',
            'configured_entities':profile.active_terms().get('entities',[]),
            'matched_entities':matches.get('entities',[]),
            'extracted_entities':event.entities,'entity_extraction_method':'platform metadata; model NER not configured',
            'original_hashtags':original_hashtags,'normalized_hashtags':normalized_hashtags,
            'incident_types':matches.get('incident_types',[]),
            'processing':{'text':'unicode lexical matching','language':'undetermined',
                          'transcript':'not_configured','vision':'not_configured'},
            "evidence_level": "Unverified", "verification_status": "not_assessed",
            "location_mentions": [{"name": name, "provenance": "text-mentioned", "confidence": 1.0,
                                   "meaning": "exact text match; not confirmed incident location"}
                                  for name in matches.get("geography", [])]}
