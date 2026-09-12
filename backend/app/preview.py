"""Supervised dashboard QA entry point; normal use remains ``app.cli serve``."""
import argparse
import secrets
from http.server import ThreadingHTTPServer

from app.api.controller import Controller
from app.api.server import handler
from app.cli import registry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1', choices=('127.0.0.1', '0.0.0.0'))
    parser.add_argument('--port', type=int, default=4173)
    parser.add_argument('--strictPort', action='store_true')
    args = parser.parse_args()
    controller = Controller('data/preview.sqlite3', registry())
    server = ThreadingHTTPServer((args.host, args.port), handler(controller, secrets.token_hex(32), preview=True))
    controller.scheduler.start()
    try:
        server.serve_forever()
    finally:
        controller.stop.set()
        server.server_close()


if __name__ == '__main__':
    main()
