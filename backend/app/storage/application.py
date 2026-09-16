"""Additive application persistence. Existing raw records and audit IDs are preserved."""
import json
import uuid
from app.config.profile import DIMENSIONS
from app.normalization.models import now


SCHEMA = '''
CREATE TABLE IF NOT EXISTS monitoring_values (
 id TEXT PRIMARY KEY, category TEXT NOT NULL, value TEXT NOT NULL,
 canonical TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
 UNIQUE(category,canonical));
CREATE TABLE IF NOT EXISTS source_state (
 platform TEXT, source_id TEXT, last_seen_at TEXT, last_collected_at TEXT,
 last_item_id TEXT, last_successful_run TEXT, last_success TEXT,
 failure_count INTEGER NOT NULL DEFAULT 0, rate_limit_count INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(platform,source_id));
CREATE TABLE IF NOT EXISTS queries (
 run_id TEXT, platform TEXT, ordinal INTEGER, payload TEXT NOT NULL,
 PRIMARY KEY(run_id,platform,ordinal));
CREATE TABLE IF NOT EXISTS collection_attempts (
 id TEXT PRIMARY KEY, run_id TEXT, platform TEXT, query_text TEXT,
 started_at TEXT, finished_at TEXT, status TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS incident_events (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES audit_runs(id), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS incident_sources (
 incident_id TEXT REFERENCES incident_events(id), record_identity TEXT REFERENCES events(id),
 PRIMARY KEY(incident_id,record_identity));
CREATE TABLE IF NOT EXISTS analysis_revisions (
 id TEXT PRIMARY KEY, run_id TEXT, created_at TEXT, snapshot TEXT, results TEXT);
CREATE INDEX IF NOT EXISTS idx_incident_run ON incident_events(run_id);
CREATE INDEX IF NOT EXISTS idx_record_platform ON source_records(platform,run_id);
CREATE INDEX IF NOT EXISTS idx_normalized_item ON events(platform,item_id);
CREATE INDEX IF NOT EXISTS idx_normalized_published ON events(json_extract(normalized,'$.published_at'));
CREATE INDEX IF NOT EXISTS idx_normalized_source ON events(json_extract(normalized,'$.source_id'));
CREATE INDEX IF NOT EXISTS idx_normalized_url ON events(json_extract(normalized,'$.url'));
INSERT OR REPLACE INTO schema_version (version) VALUES (2);
'''


class ApplicationStorage:
    def reconcile_incomplete_runs(self):
        rows=list(self.db.execute("SELECT * FROM audit_runs WHERE status='running'"))
        if not rows:
            return 0
        finished=now()
        with self.db:
            for row in rows:
                if row['report']:
                    report=json.loads(row['report'])
                else:
                    report={'id':row['id'],'started_at':row['started_at'],
                            'snapshot':json.loads(row['snapshot']),'platforms':{},'metrics':{}}
                report.update(status='failed',finished_at=finished,
                              fatal_error='application_interrupted',
                              failure_explanation='Watchtower stopped before this audit finished; its coverage is incomplete.')
                for audit in report.get('platforms',{}).values():
                    if audit.get('status')=='running':
                        audit['status']='failed'
                        audit.setdefault('errors',[]).append('application_interrupted')
                    for query in audit.get('queries',[]):
                        if query.get('status')=='running':
                            query['status']='failed'
                            query.setdefault('errors',[]).append('application_interrupted')
                payload=json.dumps(report,ensure_ascii=False,sort_keys=True,allow_nan=False)
                self.db.execute('UPDATE audit_runs SET status=?,finished_at=?,report=? WHERE id=?',
                                ('failed',finished,payload,row['id']))
                for platform,audit in report.get('platforms',{}).items():
                    self.db.execute('INSERT OR REPLACE INTO platform_audits VALUES (?,?,?)',
                                    (row['id'],platform,json.dumps(audit,ensure_ascii=False,sort_keys=True,allow_nan=False)))
            self.db.execute("UPDATE collection_attempts SET status='failed',finished_at=?,payload=? WHERE status='running'",
                            (finished,json.dumps({'error':'application_interrupted'})))
        return len(rows)

    def values(self, category):
        if category not in DIMENSIONS:
            raise ValueError('Unknown monitoring category')
        return [dict(r) for r in self.db.execute(
            'SELECT id,category,value FROM monitoring_values WHERE category=? AND archived=0 ORDER BY canonical', (category,))]

    def add_value(self, category, value):
        if category not in DIMENSIONS or not isinstance(value, str) or not value.strip() or len(value) > 200:
            raise ValueError('Provide a category and a value of 1–200 characters')
        value = ' '.join(value.split())
        canonical = value.lstrip('#').casefold() if category == 'hashtags' else value.casefold()
        if not canonical:
            raise ValueError('Value cannot be empty')
        with self.db:
            self.db.execute('''INSERT INTO monitoring_values VALUES (?,?,?,?,0)
              ON CONFLICT(category,canonical) DO UPDATE SET archived=0''',
              (str(uuid.uuid4()),category,value,canonical))
        return dict(self.db.execute('SELECT id,category,value FROM monitoring_values WHERE category=? AND canonical=?',
                                   (category,canonical)).fetchone())

    def archive_value(self, category, ident):
        row = self.db.execute('SELECT value FROM monitoring_values WHERE category=? AND id=? AND archived=0', (category,ident)).fetchone()
        if not row:
            raise ValueError('Value not found')
        with self.db:
            self.db.execute('UPDATE monitoring_values SET archived=1 WHERE id=?', (ident,))
        return row['value']

    def source_states(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM source_state ORDER BY last_seen_at DESC')]

    def incremental_state(self, platform, target):
        row=self.db.execute('SELECT * FROM source_state WHERE platform=? AND source_id=?',(platform,target)).fetchone()
        if row:
            return dict(row)
        row=self.db.execute('''SELECT ss.* FROM source_state ss JOIN events e
          ON e.platform=ss.platform AND json_extract(e.normalized,'$.source_id')=ss.source_id
          WHERE ss.platform=? AND lower(json_extract(e.normalized,'$.account'))=lower(?)
          ORDER BY ss.last_seen_at DESC LIMIT 1''',(platform,target)).fetchone()
        return dict(row) if row else None

    def source_failure(self, platform, target, rate_limited=False):
        state=self.incremental_state(platform,target)
        source_id=state['source_id'] if state else target
        with self.db:
            self.db.execute('''INSERT INTO source_state(platform,source_id,last_seen_at,failure_count,rate_limit_count)
              VALUES(?,?,?,1,?) ON CONFLICT(platform,source_id) DO UPDATE SET
              last_seen_at=excluded.last_seen_at,failure_count=source_state.failure_count+1,
              rate_limit_count=source_state.rate_limit_count+excluded.rate_limit_count''',
              (platform,source_id,now(),int(rate_limited)))

    def update_source_state(self, run_id, platform, event, from_cache):
        with self.db:
            self.db.execute('''INSERT INTO source_state
              (platform,source_id,last_seen_at,last_collected_at,last_item_id,last_successful_run,last_success)
              VALUES (?,?,?,?,?,?,?) ON CONFLICT(platform,source_id) DO UPDATE SET
              last_seen_at=excluded.last_seen_at,
              last_collected_at=COALESCE(excluded.last_collected_at,source_state.last_collected_at),
              last_item_id=excluded.last_item_id,
              last_successful_run=COALESCE(excluded.last_successful_run,source_state.last_successful_run),
              last_success=COALESCE(excluded.last_success,source_state.last_success)''',
              (platform,event.source_id,now(),None if from_cache else now(),event.item_id,
               None if from_cache else run_id,None if from_cache else now()))

    def incidents(self, run_id=None):
        sql = 'SELECT payload FROM incident_events'
        rows = self.db.execute(sql+' WHERE run_id=?' if run_id else sql, (run_id,) if run_id else ())
        return [json.loads(r[0]) for r in rows]

    def alerts_list(self):
        return [{'id':r['id'],'record_id':r['event_id'],'created_at':r['created_at'],**json.loads(r['payload'])}
                for r in self.db.execute('SELECT * FROM alerts ORDER BY created_at DESC LIMIT 500')]

    def search_records(self, filters):
        # Parameterized run/platform/time SQL first; structured analysis filters next.
        sql = '''SELECT a.run_id, e.id, COALESCE(es.normalized, e.normalized) as normalized, a.result
          FROM analysis_results a
          JOIN events e ON e.id=a.event_id
          LEFT JOIN source_records sr ON sr.id=(SELECT s.id FROM source_records s
            WHERE s.event_id=e.id AND s.run_id=a.run_id ORDER BY s.collected_at DESC LIMIT 1)
          LEFT JOIN event_sources es ON es.record_id=sr.id AND es.event_id=e.id
          WHERE 1=1'''
        args=[]
        for key, column in [('run_id','a.run_id'),('platform','e.platform')]:
            if filters.get(key):
                sql += f' AND {column}=?'
                args.append(filters[key])
        for key, op in [('start_time','>='),('end_time','<=')]:
            if filters.get(key):
                from app.config.time_window import instant
                sql += f" AND julianday(json_extract(e.normalized,'$.published_at')) {op} julianday(?)"
                args.append(instant(filters[key]).isoformat())
        try:
            limit=max(1,min(1000,int(filters.get('limit',1000))))
        except (TypeError,ValueError):
            raise ValueError('Search limit must be a number from 1 to 1000') from None
        result=[]
        for row in self.db.execute(sql+' ORDER BY a.rowid DESC',args):
            e,a=json.loads(row['normalized']),json.loads(row['result'])
            meta = e.get('metadata') if isinstance(e.get('metadata'), dict) else {}
            combined = (e.get('content','')+' '+(e.get('title') or '')+' '+(meta.get('transcript_text') or '')).casefold()
            if filters.get('q'):
                from app.intelligence.boolean import is_boolean_query, eval_boolean_match
                q_val = filters['q'].strip()
                if is_boolean_query(q_val) or ' or ' in q_val.lower() or '|' in q_val:
                    if not eval_boolean_match(q_val, combined):
                        continue
                elif q_val.casefold() not in combined:
                    continue
            if filters.get('source') and filters['source'].casefold() not in (e['source_id']+' '+(e.get('account') or '')).casefold():
                continue
            if filters.get('classification') and a.get('time_classification') != filters['classification']:
                continue
            if filters.get('relevant') == 'true' and not a['relevant']:
                continue
            if filters.get('evidence_level') and a.get('evidence_level') != filters['evidence_level']:
                continue
            skip = False
            for k in DIMENSIONS:
                val = filters.get(k)
                if not val:
                    continue
                clean_val = val.strip()
                matched_dim = [str(v).casefold() for v in a.get('matches',{}).get(k,[])]
                from app.intelligence.boolean import is_boolean_query, eval_boolean_match
                if is_boolean_query(clean_val) or ' or ' in clean_val.lower() or '|' in clean_val or ',' in clean_val:
                    if not (eval_boolean_match(clean_val, " ".join(matched_dim)) or eval_boolean_match(clean_val, combined)):
                        skip = True
                        break
                else:
                    phrase = clean_val.strip('"\'').casefold()
                    if not (any(phrase in m for m in matched_dim) or phrase in combined):
                        skip = True
                        break
            if skip:
                continue
            result.append({'id':row['id'],'run_id':row['run_id'],'event':e,'analysis':a})
            if len(result)>=limit:
                break
        return result
