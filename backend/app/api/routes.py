"""Application APIs independent of the local HTTP transport."""
import json
from app.config.profile import PLATFORMS

MISSING=object()


def read(controller, path, query):
    rid=query.get('run_id')
    if path.startswith('/api/values/'):
        with controller.repository() as repo:
            return repo.values(path.rsplit('/',1)[-1].replace('-','_'))
    if path=='/api/instagram':
        return controller.instagram_status()
    if path=='/api/transcription':
        return controller.transcription_status()
    if path=='/api/platforms':
        return {p:{'deferred':p in {'x','reddit'},'search':p not in {'x','reddit'},
                   'profiles':p=='instagram','saved_sources':p in {'instagram','news'},
                   'transcript':False,'scope':'bounded accessible public content',
                   **controller.status()['capabilities'].get(p,{'installed':False,'note':'deferred'})}
                for p in PLATFORMS}
    with controller.repository() as repo:
        if path in {'/api/records','/api/search'}:
            return repo.search_records(query)
        if path in {'/api/incidents','/api/events'}:
            return repo.incidents(rid)
        if path.startswith('/api/incidents/') or path.startswith('/api/events/'):
            ident=path.rsplit('/',1)[-1]
            event=next((e for e in repo.incidents() if e['id']==ident),None)
            if event is None:
                raise ValueError('Event not found')
            return event
        if path=='/api/sources':
            return repo.source_states()
        if path=='/api/alerts':
            return repo.alerts_list()
        if path=='/api/revisions':
            return [json.loads(r[0]) for r in repo.db.execute('SELECT results FROM analysis_revisions WHERE run_id=? ORDER BY created_at DESC',(rid,))]
        if path=='/api/audits':
            return repo.runs()
        if path.startswith('/api/audits/'):
            parts=path.strip('/').split('/')
            report=repo.report(parts[2])
            if len(parts)==3:
                return report
            if parts[3]=='platforms':
                if len(parts)==4:
                    return report['platforms']
                if parts[4] not in report['platforms']:
                    raise ValueError('Platform not found')
                return {**report['platforms'][parts[4]],'time_window':report.get('time_window'),
                        'snapshot':report['snapshot'],'records':repo.search_records({'run_id':parts[2],'platform':parts[4]})}
            if parts[3]=='sources':
                return [{'platform':p,**s} for p,a in report['platforms'].items() for s in a['sources'].values()]
    return MISSING


def write(controller,path,data):
    if path.startswith('/api/values/'):
        with controller.repository() as repo:
            return repo.add_value(path.rsplit('/',1)[-1].replace('-','_'),data.get('value'))
    if path=='/api/instagram/configure':
        return controller.instagram_configure(data)
    if path=='/api/instagram/scrape':
        return controller.instagram_scrape(data)
    if path=='/api/transcription/configure':
        return controller.transcription_configure(data)
    if path=='/api/transcription/transcribe':
        return controller.transcribe_record(data)
    if path in {'/api/instagram/test','/api/instagram/search'}:
        return controller.instagram_operation(data,'test' if path.endswith('test') else 'profiles')
    if path=='/api/reprocess':
        from app.correlation.service import reprocess
        with controller.lock:
            if controller.running:
                raise ValueError('Wait for the current audit before reprocessing')
            with controller.repository() as repo:
                return reprocess(repo,data.get('run_id'),controller.profile)
    return MISSING


def export_data(repo, rid, kind):
    if kind=='events':
        return repo.incidents(rid)
    if kind=='platform_audits':
        return [{'platform':p,**a} for p,a in repo.report(rid)['platforms'].items()]
    if kind=='raw':
        return [{**dict(r),'payload':json.loads(r['payload'])} for r in repo.db.execute(
            'SELECT * FROM source_records WHERE run_id=?',(rid,))]
    if kind not in {'normalized',None}:
        raise ValueError('Choose raw, normalized, events or platform_audits')
    return repo.events(rid)
