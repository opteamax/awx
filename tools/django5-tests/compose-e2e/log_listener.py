"""HTTP log receiver for the e2e logging check: stores POST bodies, GET /received returns them."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

received = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        received.append(self.rfile.read(int(self.headers.get('Content-Length', 0))).decode(errors='replace'))
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        body = json.dumps(received).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


ThreadingHTTPServer(('0.0.0.0', 8090), Handler).serve_forever()
