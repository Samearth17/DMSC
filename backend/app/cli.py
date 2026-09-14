import argparse
import csv
import json
from pathlib import Path
import sys
from app.auditing.engine import AuditEngine
from app.config.profile import DIMENSIONS, PLATFORMS, Profile, load_profile
from app.connectors.news.connector import NewsConnector
from app.connectors.youtube.connector import YouTubeConnector
from app.connectors.instagram.connector import InstagramConnector
from app.connectors.web.connector import WebConnector
from app.connectors.meta.connector import MetaConnector
from app.discovery.queries import plan
from app.storage.repository import Repository
from app.connectors.reddit.connector import RedditConnector


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def registry():
    return {
        "youtube": YouTubeConnector(),
        "instagram": InstagramConnector(),
        "reddit": RedditConnector(),
        "news": NewsConnector(),
        "web": WebConnector(),
        "meta": MetaConnector(),
    }


def safe_cell(value):
    text = str(value or "")
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text


def main(argv=None):
    parser = argparse.ArgumentParser(description="Watchtower 0.3: local public-information audits and dashboard")
    parser.add_argument("--db", default="data/watchtower.sqlite3", help="Local SQLite path")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create a blank profile; never overwrite one")
    init.add_argument("--out", default="config.yaml")
    for name in ("plan", "run"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--config", default="config.yaml")
        cmd.add_argument("--platform", choices=PLATFORMS, help="Audit only this platform; saved profile is unchanged")
    sub.add_parser("doctor", help="Show installed connector capabilities without network requests")
    serve = sub.add_parser("serve", help="Start the local dashboard and scheduler")
    serve.add_argument("--port",type=int,default=8765)
    serve.add_argument("--open",action="store_true",help="Open the dashboard in your local browser")
    report = sub.add_parser("report")
    report.add_argument("--run-id")
    export = sub.add_parser("export")
    export.add_argument("--run-id")
    export.add_argument("--out", required=True, help="New .json or .csv path; does not overwrite")
    history = sub.add_parser("source-history")
    history.add_argument("platform", choices=PLATFORMS)
    history.add_argument("source_id")
    sub.add_parser("demo", help="Run explicit synthetic data offline; use a separate --db")
    args = parser.parse_args(argv)
    repo = None
    try:
        if args.command == "serve":
            from app.api.server import serve
            serve(args.db,args.port,args.open)
            return 0
        if args.command == "init":
            profile = Profile.parse({"dimensions": {k: {"enabled": False, "values": []} for k in DIMENSIONS},
                                     "platforms": {p: p in {"youtube", "news"} for p in PLATFORMS}})
            content = profile.snapshot()
            path = Path(args.out)
            if path.suffix.lower() == ".json":
                text = json.dumps(content, indent=2)
            else:
                import yaml
                text = yaml.safe_dump(content, sort_keys=False, allow_unicode=True)
            with path.open("x", encoding="utf-8") as handle:
                handle.write(text)
            print(f"Created {path}. Add your values and enable at least one dimension.")
            return 0
        if args.command == "doctor":
            connectors = registry()
            output({p: {"available": connectors[p].available()[0], "reason": connectors[p].available()[1]}
                    if p in connectors else {"available": False, "reason": "deferred_by_user"} for p in PLATFORMS})
            return 0
        if args.command in {"plan", "run"}:
            profile = load_profile(args.config)
            if args.platform:
                profile.platforms = {p: p == args.platform for p in PLATFORMS}
            if args.command == "plan":
                output({"profile": profile.name, "queries": plan(profile),
                        "semantics": "independent OR discovery lanes; selected terms are not mandatory AND filters"})
                return 0
        repo = Repository(args.db)
        if args.command == "run":
            result = AuditEngine(repo, registry()).run(profile)
            output(result)
            return 0 if result["status"] == "complete" else 2
        if args.command == "report":
            output(repo.report(args.run_id))
        elif args.command == "source-history":
            output(repo.source_history(args.platform, args.source_id))
        elif args.command == "demo":
            from app.demo import demo
            output(demo(repo))
        elif args.command == "export":
            path = Path(args.out)
            if path.suffix.lower() not in {".json", ".csv"}:
                raise ValueError("Export path must end in .json or .csv")
            data = repo.events(args.run_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8-sig" if path.suffix.lower() == ".csv" else "utf-8", newline="") as handle:
                if path.suffix.lower() == ".json":
                    json.dump(data, handle, ensure_ascii=False, indent=2)
                else:
                    writer = csv.writer(handle)
                    writer.writerow(["platform", "source", "url", "published_at", "content", "relevant", "evidence_level"])
                    for item in data:
                        e, a = item["event"], item["analysis"]
                        writer.writerow([safe_cell(v) for v in [e["platform"],e["source_id"],e["url"],
                                                               e["published_at"],e["content"],str(a["relevant"]),a["evidence_level"]]])
            print(f"Exported {len(data)} records to {path}")
        return 0
    except (ValueError, OSError, ImportError) as exc:
        print(f"Watchtower: {exc}", file=sys.stderr)
        return 1
    finally:
        if repo:
            repo.close()


if __name__ == "__main__":
    sys.exit(main())
