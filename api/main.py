import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8000


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({"status": "ok", "service": "synapseshop-api"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, fmt, *args):
        print(
            f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}",
            flush=True,
        )


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"SynapseShop API listening on 0.0.0.0:{PORT} (health: /health)", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()