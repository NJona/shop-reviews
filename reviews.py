"""reviews: product ratings for the storefront. Private to this landscape; other apps reach it only through a
connection in the global config."""
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 3000


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({
            "service": "reviews",
            "app": "reviews",
            "data_center": os.environ.get("GLOBAL_DEPLOYMENT_DATA_CENTER", "?"),
            "pod": socket.gethostname(),
            "rating": "4.6 of 5 from 128 reviews",
        })
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())


HTTPServer(("", PORT), Handler).serve_forever()
