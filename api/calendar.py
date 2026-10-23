from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import os

from ff_calendar import main


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            os.environ["MODE"] = params.get("mode", ["today"])[0]
            main()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"calendar completed")
        except Exception as exc:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(exc).encode())
