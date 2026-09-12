import csv
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from io import StringIO
import json
from pathlib import Path
import secrets
from urllib.parse import urlsplit,parse_qs
import webbrowser
from app.api.controller import Controller
from app.discovery.queries import plan
from app.api import routes

STATIC=Path(__file__).parent/'static'


def handler(controller,token,preview=False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass  # Do not log private queries or tokens.

        def send(self,data,status=200,ctype='application/json; charset=utf-8',download=None):
            body=(json.dumps(data,ensure_ascii=False).encode() if ctype.startswith('application/json') else data.encode() if isinstance(data,str) else data)
            self.send_response(status)
            self.send_header('Content-Type',ctype)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            if download:
                self.send_header('Content-Disposition','attachment; filename="'+download+'"')
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):
                pass

        def valid(self,api=True):
            port=self.server.server_port
            hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
            if preview:
                hosts.add(f'terminal.local:{port}')
            if self.headers.get('Host') not in hosts:
                self.send({'error':'Host not allowed'},403)
                return False
            origin=self.headers.get('Origin')
            if origin and origin not in {'http://'+host for host in hosts}:
                self.send({'error':'Origin not allowed'},403)
                return False
            if api and not hmac.compare_digest(self.headers.get('X-Watchtower-Token',''),token):
                self.send({'error':'Local session token required'},403)
                return False
            return True

        def do_GET(self):
            path=urlsplit(self.path)
            if not self.valid(api=path.path.startswith('/api/')):
                return
            query=parse_qs(path.query)
            rid=query.get('run_id',[None])[0]
            try:
                extra=routes.read(controller,path.path,{k:v[0] for k,v in query.items()}) if path.path.startswith('/api/') else routes.MISSING
                if extra is not routes.MISSING:
                    self.send(extra)
                elif path.path=='/':
                    self.send((STATIC/'index.html').read_text().replace('__SESSION_TOKEN__',token),ctype='text/html; charset=utf-8')
                elif path.path in {'/app.js','/style.css'}:
                    self.send((STATIC/path.path[1:]).read_bytes(),ctype='text/javascript; charset=utf-8' if path.path.endswith('.js') else 'text/css; charset=utf-8')
                elif path.path=='/api/status':
                    self.send(controller.status())
                elif path.path=='/api/profile':
                    with controller.lock:
                        self.send(controller.profile.snapshot())
                elif path.path=='/api/plan':
                    with controller.lock:
                        self.send(plan(controller.profile))
                else:
                    with controller.repository() as repo:
                        if path.path=='/api/runs':
                            self.send(repo.runs())
                        elif path.path=='/api/report':
                            self.send(repo.report(rid))
                        elif path.path=='/api/events':
                            self.send(repo.events(rid))
                        elif path.path=='/api/source-history':
                            self.send(repo.source_history(query.get('platform',[''])[0],query.get('source_id',[''])[0]))
                        elif path.path=='/api/evidence':
                            self.send(repo.evidence(query.get('event_id',[''])[0],rid))
                        elif path.path=='/api/export':
                            kind=query.get('kind',['normalized'])[0]
                            items=routes.export_data(repo,rid or repo.report()['id'],kind)
                            if query.get('format',['json'])[0]=='csv':
                                from app.cli import safe_cell
                                out=StringIO()
                                writer=csv.writer(out)
                                if kind=='normalized':
                                    items=[{**i['event'],**i['analysis']} for i in items]
                                fields=list(dict.fromkeys(k for i in items for k in i))
                                writer.writerow(fields)
                                for item in items:
                                    writer.writerow([safe_cell(json.dumps(item.get(k),ensure_ascii=False) if isinstance(item.get(k),(dict,list)) else item.get(k)) for k in fields])
                                self.send('\ufeff'+out.getvalue(),ctype='text/csv; charset=utf-8',download=f'watchtower-{kind}.csv')
                            else:
                                self.send(items,download=f'watchtower-{kind}.json')
                        else:
                            self.send({'error':'Not found'},404)
            except ValueError as exc:
                self.send({'error':str(exc)},404)
            except Exception:
                self.send({'error':'Could not read local data'},500)

        def do_POST(self):
            if not self.valid():
                return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<=size<=2*1024*1024:
                    raise ValueError('Request too large')
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    raise ValueError('JSON required')
                data=json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(data,dict):
                    raise ValueError('JSON object required')
                extra=routes.write(controller,self.path,data)
                if extra is not routes.MISSING:
                    self.send(extra)
                elif self.path=='/api/profile':
                    self.send(controller.save_profile(data))
                elif self.path=='/api/run':
                    self.send(controller.start(),202)
                elif self.path=='/api/schedule':
                    self.send(controller.configure_schedule(data))
                else:
                    self.send({'error':'Not found'},404)
            except (ValueError,TypeError) as exc:
                self.send({'error':str(exc)},400)
            except Exception:
                self.send({'error':'Could not update local state'},500)

        do_PUT=do_POST

        def do_DELETE(self):
            if not self.valid():
                return
            parts=urlsplit(self.path).path.strip('/').split('/')
            try:
                if len(parts)!=4 or parts[:2]!=['api','values']:
                    self.send({'error':'Not found'},404)
                    return
                self.send(controller.archive_value(parts[2].replace('-','_'),parts[3]))
            except ValueError as exc:
                self.send({'error':str(exc)},404)
    return Handler


def serve(path,port=8765,open_browser=False):
    from app.cli import registry
    if not 1024<=port<=65535:
        raise ValueError('Port must be between 1024 and 65535')
    controller=Controller(path,registry())
    server=ThreadingHTTPServer(('127.0.0.1',port),handler(controller,secrets.token_hex(32)))
    controller.scheduler.start()
    url=f'http://127.0.0.1:{port}/'
    print('Watchtower local dashboard: '+url,flush=True)
    print('Keep this window open for scheduled audits. Press Ctrl+C to stop.',flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop.set()
        server.server_close()
