from http.server import BaseHTTPRequestHandler

from ff_alerts import main


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            main()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"alerts completed")
        except Exception as exc:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(exc).encode())
