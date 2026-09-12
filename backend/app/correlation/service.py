"""Persist candidate incidents separately from normalized records and original audits."""
import json
import uuid
from app.correlation.groups import group_reports
from app.storage.repository import digest, encode
from app.normalization.models import now
from app.intelligence.rules import analyze
from app.config.time_window import TimeWindow


def build_events(items, run_id):
    current=[i for i in items if i['analysis']['relevant'] and i['analysis'].get('time_classification')=='CURRENT']
    by_id={i['id']:i for i in current}
    events=[]
    for group in group_reports(current):
        members=[by_id[ident] for ident in group['event_ids']]
        content={ ' '.join(i['event']['content'].casefold().split()) for i in members }
        sources={(i['event']['platform'],i['event']['source_id']) for i in members}
        times=sorted(i['event']['published_at'] for i in members)
        events.append({'id':digest([run_id,sorted(group['event_ids'])]),'run_id':run_id,
            'title':group['title'],'summary':members[0]['event']['content'][:600],
            'first_seen_at':times[0],'last_seen_at':times[-1], 'record_ids':group['event_ids'],
            'platforms':group['platforms'],'source_count':len(sources),'distinct_text_count':len(content),
            'location':[x for i in members for x in i['analysis'].get('location_mentions',[])],
            'entities':sorted({x for i in members for x in i['analysis'].get('matched_entities',[])}),
            'incident_types':sorted({x for i in members for x in i['analysis'].get('incident_types',[])}),
            'confidence':None,'evidence_level':'Single Source' if len(sources)==1 else 'Unverified',
            'status':'needs_review','verification_status':'not_assessed',
            'correlation_reason':group['grouping_reason'],
            'confidence_explanation':'Independent corroboration and contradictions have not been assessed. Repetition does not verify a claim.',
            'evidence':[{'record_id':i['id'],'platform':i['event']['platform'],'source':i['event']['source_id'],
                         'url':i['event']['url'],'published_at':i['event']['published_at']} for i in members]})
    return events


def persist_events(repo, run_id, items):
    events=build_events(items,run_id)
    with repo.db:
        for event in events:
            repo.db.execute('INSERT OR REPLACE INTO incident_events VALUES (?,?,?)',(event['id'],run_id,encode(event)))
            for ident in event['record_ids']:
                repo.db.execute('INSERT OR IGNORE INTO incident_sources VALUES (?,?)',(event['id'],ident))
    return events


def reprocess(repo, run_id, profile):
    from app.normalization.models import WatchtowerRecord
    report=repo.report(run_id)
    window=TimeWindow.parse(report['time_window'])
    items=repo.events(run_id)
    for item in items:
        record=WatchtowerRecord(**item['event'])
        result=analyze(record,profile)
        # Preserve original temporal eligibility, including uncertain day precision.
        result['time_classification']=item['analysis'].get('time_classification',window.classify(record.published_at))
        result['matched_objective']=result['relevant']
        result['relevant'] &= result['time_classification']=='CURRENT'
        item['analysis']=result
    revision={'id':uuid.uuid4().hex,'run_id':run_id,'created_at':now(),'snapshot':profile.snapshot(),
              'records':items,'events':build_events(items,run_id),'collection_requests':0}
    with repo.db:
        repo.db.execute('INSERT INTO analysis_revisions VALUES (?,?,?,?,?)',
            (revision['id'],run_id,revision['created_at'],encode(revision['snapshot']),encode(revision)))
    return revision
