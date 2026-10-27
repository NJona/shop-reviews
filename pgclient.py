"""A minimal PostgreSQL client: TLS if the server offers it, SCRAM-SHA-256 login, simple queries.

The workspace image has Python but no Postgres driver and no pip, so the demo carries its own.
Only what reviews.py needs; values come back as text.
"""
import base64
import hashlib
import hmac
import os
import socket
import ssl
import struct

PROTOCOL_VERSION = 196608  # 3.0
SSL_REQUEST_CODE = 80877103
AUTH_OK, AUTH_CLEARTEXT, AUTH_SASL, AUTH_SASL_CONTINUE, AUTH_SASL_FINAL = 0, 3, 10, 11, 12
TIMEOUT_SECONDS = 10


class PgError(Exception):
    pass


def _error_text(body):
    fields = dict((part[:1], part[1:].decode()) for part in body.split(b"\0") if part)
    return fields.get(b"M", "unknown error")


class Connection:
    def __init__(self, host, port, user, password, database):
        sock = socket.create_connection((host, port), timeout=TIMEOUT_SECONDS)
        sock.sendall(struct.pack("!II", 8, SSL_REQUEST_CODE))
        if sock.recv(1) == b"S":
            context = ssl.create_default_context()
            # The service is only reachable inside the cluster; the demo does not check its certificate.
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            sock = context.wrap_socket(sock)
        self.sock = sock
        params = b"".join(k.encode() + b"\0" + v.encode() + b"\0"
                          for k, v in (("user", user), ("database", database))) + b"\0"
        startup = struct.pack("!I", PROTOCOL_VERSION) + params
        sock.sendall(struct.pack("!I", len(startup) + 4) + startup)
        self._authenticate(password)
        self._until_ready()

    def _recv(self, n):
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise PgError("connection closed by the server")
            data += chunk
        return data

    def _read(self):
        header = self._recv(5)
        length = struct.unpack("!I", header[1:])[0]
        return header[:1], self._recv(length - 4)

    def _send(self, kind, payload):
        self.sock.sendall(kind + struct.pack("!I", len(payload) + 4) + payload)

    def _authenticate(self, password):
        kind, body = self._read()
        if kind == b"E":
            raise PgError(_error_text(body))
        code = struct.unpack("!I", body[:4])[0]
        if code == AUTH_OK:
            return
        if code == AUTH_CLEARTEXT:
            self._send(b"p", password.encode() + b"\0")
        elif code == AUTH_SASL:
            self._scram(password)
        else:
            raise PgError(f"unsupported authentication method {code}")
        kind, body = self._read()
        if kind == b"E":
            raise PgError(_error_text(body))

    def _scram(self, password):
        nonce = base64.b64encode(os.urandom(18)).decode()
        first_bare = f"n=,r={nonce}"
        first = ("n,," + first_bare).encode()
        self._send(b"p", b"SCRAM-SHA-256\0" + struct.pack("!I", len(first)) + first)
        kind, body = self._read()
        if kind == b"E" or struct.unpack("!I", body[:4])[0] != AUTH_SASL_CONTINUE:
            raise PgError(_error_text(body) if kind == b"E" else "unexpected SCRAM answer")
        server_first = body[4:].decode()
        attrs = dict(part.split("=", 1) for part in server_first.split(","))
        salted = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(attrs["s"]), int(attrs["i"]))
        client_key = hmac.digest(salted, b"Client Key", "sha256")
        stored_key = hashlib.sha256(client_key).digest()
        final_without_proof = f"c=biws,r={attrs['r']}"
        auth_message = f"{first_bare},{server_first},{final_without_proof}".encode()
        signature = hmac.digest(stored_key, auth_message, "sha256")
        proof = base64.b64encode(bytes(a ^ b for a, b in zip(client_key, signature))).decode()
        self._send(b"p", f"{final_without_proof},p={proof}".encode())
        kind, body = self._read()
        if kind == b"E" or struct.unpack("!I", body[:4])[0] != AUTH_SASL_FINAL:
            raise PgError(_error_text(body) if kind == b"E" else "SCRAM was not accepted")

    def _until_ready(self):
        while True:
            kind, body = self._read()
            if kind == b"E":
                raise PgError(_error_text(body))
            if kind == b"Z":
                return

    def query(self, sql):
        """Runs one statement and returns its rows as tuples of text (None for NULL)."""
        self._send(b"Q", sql.encode() + b"\0")
        rows, error = [], None
        while True:
            kind, body = self._read()
            if kind == b"D":
                count, offset, row = struct.unpack("!H", body[:2])[0], 2, []
                for _ in range(count):
                    length = struct.unpack("!i", body[offset:offset + 4])[0]
                    offset += 4
                    row.append(None if length < 0 else body[offset:offset + length].decode())
                    offset += max(length, 0)
                rows.append(tuple(row))
            elif kind == b"E":
                error = _error_text(body)
            elif kind == b"Z":
                if error:
                    raise PgError(error)
                return rows

    def close(self):
        self._send(b"X", b"")
        self.sock.close()
