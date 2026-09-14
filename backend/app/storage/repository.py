"""SQLite persistence boundary. A PostgreSQL implementation is a future adapter."""
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid
import threading
from app.normalization.models import now
from app.storage.application import ApplicationStorage, SCHEMA


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


class Repository(ApplicationStorage):
    def __init__(self, path="data/watchtower.sqlite3"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
        INSERT OR IGNORE INTO schema_version VALUES (1);
        CREATE TABLE IF NOT EXISTS monitoring_profiles
          (id TEXT PRIMARY KEY, name TEXT NOT NULL, snapshot TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_runs
          (id TEXT PRIMARY KEY, profile_id TEXT REFERENCES monitoring_profiles(id),
           started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, snapshot TEXT NOT NULL, report TEXT);
        CREATE TABLE IF NOT EXISTS platform_audits
          (run_id TEXT REFERENCES audit_runs(id), platform TEXT, report TEXT NOT NULL,
           PRIMARY KEY(run_id, platform));
        CREATE TABLE IF NOT EXISTS sources
          (id TEXT PRIMARY KEY, platform TEXT NOT NULL, source_id TEXT NOT NULL, source_type TEXT NOT NULL,
           last_audited TEXT NOT NULL, UNIQUE(platform,source_id));
        CREATE TABLE IF NOT EXISTS source_audits
          (run_id TEXT REFERENCES audit_runs(id), source_key TEXT REFERENCES sources(id), report TEXT NOT NULL,
           PRIMARY KEY(run_id,source_key));
        CREATE TABLE IF NOT EXISTS source_records
          (id TEXT PRIMARY KEY, run_id TEXT REFERENCES audit_runs(id), platform TEXT NOT NULL,
           query_text TEXT NOT NULL, payload TEXT NOT NULL, content_hash TEXT NOT NULL,
           collected_at TEXT NOT NULL, event_id TEXT, error TEXT);
        CREATE INDEX IF NOT EXISTS idx_record_hash ON source_records(platform,content_hash);
        CREATE TABLE IF NOT EXISTS events
          (id TEXT PRIMARY KEY, platform TEXT NOT NULL, item_id TEXT NOT NULL, normalized TEXT NOT NULL,
           UNIQUE(platform,item_id));
        CREATE TABLE IF NOT EXISTS event_sources
          (event_id TEXT REFERENCES events(id), record_id TEXT REFERENCES source_records(id),
           normalized TEXT NOT NULL, PRIMARY KEY(event_id,record_id));
        CREATE TABLE IF NOT EXISTS analysis_results
          (run_id TEXT REFERENCES audit_runs(id), event_id TEXT REFERENCES events(id),
           result TEXT NOT NULL, PRIMARY KEY(run_id,event_id));
        CREATE TABLE IF NOT EXISTS query_cache
          (cache_key TEXT PRIMARY KEY, created_at REAL NOT NULL, batch TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS discovery_responses
          (id TEXT PRIMARY KEY, run_id TEXT REFERENCES audit_runs(id), platform TEXT NOT NULL,
           query_text TEXT NOT NULL, raw_response TEXT NOT NULL, collected_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS alerts
          (id TEXT PRIMARY KEY, event_id TEXT REFERENCES events(id), payload TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_runs_started_at ON audit_runs(started_at);
        CREATE INDEX IF NOT EXISTS idx_records_event_run ON source_records(event_id,run_id,collected_at);
        ''')
        self.db.executescript(SCHEMA)
        self.db.commit()

    def begin(self, profile):
        snapshot = profile.snapshot()
        pid, rid = digest(snapshot), str(uuid.uuid4())
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO monitoring_profiles VALUES (?,?,?)", (pid, profile.name, encode(snapshot)))
            self.db.execute("INSERT INTO audit_runs VALUES (?,?,?,?,?,?,?)", (rid,pid,now(),None,"running",encode(snapshot),None))
        return rid

    def save_report(self, report):
        with self.lock, self.db:
            self.db.execute("UPDATE audit_runs SET status=?,finished_at=?,report=? WHERE id=?",
                            (report["status"], report.get("finished_at"), encode(report), report["id"]))
            for platform, audit in report["platforms"].items():
                for ordinal, query in enumerate(audit['queries']):
                    self.db.execute('INSERT OR REPLACE INTO queries VALUES (?,?,?,?)',
                                    (report['id'],platform,ordinal,encode(query)))
                self.db.execute("INSERT OR REPLACE INTO platform_audits VALUES (?,?,?)", (report["id"],platform,encode(audit)))
                for sid, source in audit["sources"].items():
                    skey = digest([platform, sid])
                    self.db.execute("INSERT INTO sources VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET last_audited=excluded.last_audited",
                                    (skey,platform,sid,source["source_type"],source["last_audited"]))
                    self.db.execute("INSERT OR REPLACE INTO source_audits VALUES (?,?,?)", (report["id"],skey,encode(source)))

    def store_raw(self, run_id, platform, query, raw):
        fingerprint = digest(raw)
        with self.lock:
            cached = self.db.execute("SELECT 1 FROM source_records WHERE platform=? AND content_hash=? AND event_id IS NOT NULL LIMIT 1",
                                     (platform,fingerprint)).fetchone() is not None
            rid = str(uuid.uuid4())
            with self.db:
                self.db.execute("INSERT INTO source_records VALUES (?,?,?,?,?,?,?,?,?)",
                                (rid,run_id,platform,query,encode(raw),fingerprint,now(),None,None))
            return rid, cached

    def raw_error(self, record_id, code):
        with self.db:
            self.db.execute("UPDATE source_records SET error=? WHERE id=?", (code,record_id))

    def store_event(self, run_id, record_id, event, analysis):
        eid = digest([event.platform,event.item_id])
        normalized = encode(event.to_dict())
        with self.lock, self.db:
            self.db.execute("INSERT INTO events VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET normalized=excluded.normalized",
                            (eid,event.platform,event.item_id,normalized))
            self.db.execute("INSERT INTO event_sources VALUES (?,?,?)", (eid,record_id,normalized))
            self.db.execute("UPDATE source_records SET event_id=? WHERE id=?", (eid,record_id))
            self.db.execute("INSERT OR REPLACE INTO analysis_results VALUES (?,?,?)", (run_id,eid,encode(analysis)))
        return eid

    def response(self, run_id, platform, query, raw):
        if raw is not None:
            with self.db:
                self.db.execute("INSERT INTO discovery_responses VALUES (?,?,?,?,?,?)",
                                (str(uuid.uuid4()),run_id,platform,query,raw,now()))

    def cache_get(self, key, timestamp, ttl):
        row = self.db.execute("SELECT * FROM query_cache WHERE cache_key=?", (key,)).fetchone()
        return json.loads(row["batch"]) if row and ttl > 0 and 0 <= timestamp-row["created_at"] < ttl else None

    def cache_put(self, key, timestamp, batch):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO query_cache VALUES (?,?,?)", (key,timestamp,encode(batch)))

    def report(self, rid=None):
        row = (self.db.execute("SELECT * FROM audit_runs WHERE id=?", (rid,)) if rid else
               self.db.execute("SELECT * FROM audit_runs ORDER BY started_at DESC LIMIT 1")).fetchone()
        if row is None:
            raise ValueError("No matching audit run")
        return json.loads(row["report"]) if row["report"] else dict(row)

    def events(self, rid=None):
        if rid is None:
            rid = self.report()["id"]
        rows = self.db.execute('''SELECT e.id, es.normalized, a.result FROM analysis_results a
          JOIN events e ON e.id=a.event_id
          JOIN event_sources es ON es.record_id=(SELECT sr.id FROM source_records sr
            WHERE sr.event_id=e.id AND sr.run_id=a.run_id ORDER BY sr.collected_at DESC LIMIT 1)
          WHERE a.run_id=?''', (rid,))
        return [{"id": r["id"], "event": json.loads(r["normalized"]), "analysis": json.loads(r["result"])} for r in rows]

    def source_history(self, platform, source_id):
        rows = self.db.execute("SELECT run_id,report FROM source_audits WHERE source_key=? ORDER BY rowid DESC",
                               (digest([platform,source_id]),))
        return [{"run_id": r["run_id"], **json.loads(r["report"])} for r in rows]

    def close(self):
        self.db.close()

    def setting(self,key,default=None):
        row=self.db.execute("SELECT value FROM app_settings WHERE key=?",(key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self,key,value):
        with self.db:
            self.db.execute("INSERT INTO app_settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,encode(value)))

    def runs(self,limit=50):
        rows=self.db.execute("SELECT id,started_at,finished_at,status,snapshot FROM audit_runs ORDER BY started_at DESC LIMIT ?",(limit,))
        return [{"id":r['id'],"started_at":r['started_at'],"finished_at":r['finished_at'],
                 "status":r['status'],"profile_name":json.loads(r['snapshot']).get('name')} for r in rows]

    def evidence(self,event_id,run_id):
        rows=self.db.execute("SELECT id,query_text,payload,collected_at,error FROM source_records WHERE event_id=? AND run_id=? ORDER BY collected_at",(event_id,run_id))
        return [{"record_id":r['id'],"query":r['query_text'],"raw":json.loads(r['payload']),
                 "collected_at":r['collected_at'],"error":r['error']} for r in rows]
