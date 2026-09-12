from datetime import datetime
import hashlib
import re


def group_reports(items):
    """Only exact text matches or similar dated headlines within 24 hours.

    Groups are candidates for review, never inferred independent corroboration.
    """
    groups=[]
    for item in items:
        event=item['event']
        title=event['metadata'].get('title') or event['content'][:180]
        words=set(re.findall(r'\w{3,}',title.casefold()))
        normalized=' '.join(event['content'].casefold().split())
        fingerprint=hashlib.sha256(normalized.encode()).hexdigest()
        matched=None
        for group in groups[-500:]:
            exact=bool(normalized) and fingerprint==group['_fingerprint']
            similar=False
            try:
                a,b=event.get('published_at'),group['_published_at']
                if a and b and abs((datetime.fromisoformat(a)-datetime.fromisoformat(b)).total_seconds())<=86400:
                    similar=len(words)>=5 and len(words & group['_words'])/max(1,len(words | group['_words']))>=.78
                elif a and b:
                    exact=False
            except (ValueError,TypeError):
                pass
            if exact or similar:
                matched=group
                break
        if matched is None:
            matched={'id':item['id'],'title':title,'event_ids':[], 'platforms':[], 'source_ids':[],
                     'evidence_level':'Unverified','grouping_reason':'single report','_fingerprint':fingerprint,
                     '_words':words,'_published_at':event.get('published_at')}
            groups.append(matched)
        else:
            matched['grouping_reason']='similar dated headlines or exact text; review required'
        matched['event_ids'].append(item['id'])
        for key,value in [('platforms',event['platform']),('source_ids',event['source_id'])]:
            if value not in matched[key]:
                matched[key].append(value)
    return [{k:v for k,v in g.items() if not k.startswith('_')} for g in groups]
