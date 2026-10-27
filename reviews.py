"""reviews: product ratings for the storefront, kept in the app's Postgres.

The global deployment creates the database next to this landscape (a standalone managed service of the app) and
passes REVIEWS_DB_HOST, REVIEWS_DB_PORT and REVIEWS_DB_USER_PASSWORD.

Every call adds a review, so the count shows that the data moved along when the app migrates to another
data center: the oldest review still names the data center it was written in.
"""
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pgclient import Connection, PgError

PORT = 3000
DB_NAME = "app"
DB_USER = "app"
DATA_CENTER = os.environ.get("GLOBAL_DEPLOYMENT_DATA_CENTER", "?")
# Only a number or "?" is ever written into the SQL below.
DATA_CENTER_LABEL = DATA_CENTER if DATA_CENTER.isdigit() else "?"
NEW_REVIEW_STARS = 5


def rate():
    db = Connection(os.environ["REVIEWS_DB_HOST"], int(os.environ["REVIEWS_DB_PORT"]), DB_USER,
                    os.environ["REVIEWS_DB_USER_PASSWORD"], DB_NAME)
    try:
        db.query("CREATE TABLE IF NOT EXISTS reviews ("
                 " id SERIAL PRIMARY KEY, stars INTEGER NOT NULL,"
                 " written_in_dc TEXT NOT NULL, written_at TIMESTAMPTZ NOT NULL DEFAULT now())")
        db.query(f"INSERT INTO reviews (stars, written_in_dc) VALUES ({NEW_REVIEW_STARS}, '{DATA_CENTER_LABEL}')")
        count, average = db.query("SELECT count(*), round(avg(stars), 1) FROM reviews")[0]
        first_dc, first_at = db.query("SELECT written_in_dc, to_char(written_at, 'HH24:MI') FROM reviews ORDER BY id LIMIT 1")[0]
    finally:
        db.close()
    return {
        "rating": f"{average} of 5 from {count} reviews",
        "data": f"first review written in data center {first_dc} at {first_at} UTC",
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = {
            "service": "reviews",
            "app": "reviews",
            "data_center": DATA_CENTER,
            "pod": socket.gethostname(),
        }
        status = 200
        if self.path != "/healthz":
            try:
                body.update(rate())
            except (OSError, PgError) as error:  # the storefront shows why
                body["error"] = f"reviews-db: {error}"
                status = 503
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *args):
        pass


# Threaded: a slow call must not hold up health checks or other visitors.
ThreadingHTTPServer(("", PORT), Handler).serve_forever()
