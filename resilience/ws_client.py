"""Minimal WebSocket (RFC 6455) client built on the standard library only.

Supports what the EEW routes need: wss/ws connect, text frames (including
fragmentation), ping/pong, close. No third-party dependency, so the
receiver runs on a stock Python 3 installation.
"""
from __future__ import annotations

import base64
import os
import socket
import ssl
import struct
import urllib.request
from urllib.parse import unquote, urlparse

OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG, OP_CONT = 0x1, 0x2, 0x8, 0x9, 0xA, 0x0


def encode_frame(payload: bytes, opcode: int = OP_TEXT, mask_key: bytes | None = None) -> bytes:
    if mask_key is None:
        mask_key = os.urandom(4)
    header = bytearray([0x80 | opcode])
    n = len(payload)
    if n < 126:
        header.append(0x80 | n)
    elif n <= 0xFFFF:
        header.append(0x80 | 126)
        header += struct.pack(">H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", n)
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return bytes(header) + mask_key + masked


def decode_frame_header(first: int, second: int):
    """Return (fin, opcode, masked, length_code) from the first two bytes."""
    fin = bool(first & 0x80)
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    return fin, opcode, masked, second & 0x7F


class WsError(Exception):
    pass


def parse_proxy_url(proxy_url: str):
    """Split a proxy URL into (host, port, authorization header or None)."""
    u = urlparse(proxy_url if "://" in proxy_url else "http://" + proxy_url)
    host = u.hostname
    port = u.port or 3128
    auth = None
    if u.username:
        user = unquote(u.username)
        password = unquote(u.password or "")
        auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    return host, port, auth


def connect_via_proxy(proxy_url: str, target_host: str, target_port: int,
                       timeout: float) -> socket.socket:
    """Open a TCP tunnel to the target through an HTTP CONNECT proxy."""
    proxy_host, proxy_port, auth = parse_proxy_url(proxy_url)
    sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    lines = [f"CONNECT {target_host}:{target_port} HTTP/1.1",
             f"Host: {target_host}:{target_port}"]
    if auth:
        lines.append(f"Proxy-Authorization: {auth}")
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    buf = bytearray()
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            sock.close()
            raise WsError("proxy closed during CONNECT")
        buf += chunk
        if len(buf) > 65536:
            sock.close()
            raise WsError("proxy response too large")
    status = bytes(buf).split(b"\r\n", 1)[0].decode("latin1")
    if " 200" not in status:
        sock.close()
        raise WsError(f"proxy CONNECT failed: {status}")
    return sock


class WsConnection:
    def __init__(self, url: str, timeout: float = 90.0):
        self.url = url
        self.timeout = timeout
        self._sock = None
        self._buf = bytearray()
        self._fragments = bytearray()
        self._fragment_opcode = None

    def connect(self) -> None:
        u = urlparse(self.url)
        if u.scheme not in ("ws", "wss"):
            raise WsError(f"unsupported scheme: {u.scheme}")
        host = u.hostname
        port = u.port or (443 if u.scheme == "wss" else 80)
        path = u.path or "/"
        if u.query:
            path += "?" + u.query
        # Honour the standard proxy environment (http_proxy/https_proxy/
        # no_proxy), as other standard tooling does. Direct connection is
        # used when no proxy applies.
        proxies = urllib.request.getproxies()
        proxy_url = proxies.get("https" if u.scheme == "wss" else "http")
        if proxy_url and not urllib.request.proxy_bypass(host):
            raw = connect_via_proxy(proxy_url, host, port, self.timeout)
        else:
            raw = socket.create_connection((host, port), timeout=self.timeout)
        if u.scheme == "wss":
            ctx = ssl.create_default_context()
            raw = ctx.wrap_socket(raw, server_hostname=host)
        raw.settimeout(self.timeout)
        self._sock = raw
        key = base64.b64encode(os.urandom(16)).decode()
        host_header = host if (u.port is None) else f"{host}:{port}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "User-Agent: toro-resilience/0.1\r\n"
            "\r\n"
        )
        raw.sendall(request.encode())
        response = self._read_until(b"\r\n\r\n", limit=65536)
        status_line = response.split(b"\r\n", 1)[0].decode("latin1")
        if " 101" not in status_line:
            raise WsError(f"handshake failed: {status_line}")

    def _fill(self, need: int) -> None:
        while len(self._buf) < need:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise WsError("connection closed")
            self._buf += chunk

    def _read_exact(self, n: int) -> bytes:
        self._fill(n)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def _read_until(self, sep: bytes, limit: int) -> bytes:
        while sep not in self._buf:
            if len(self._buf) > limit:
                raise WsError("header too large")
            chunk = self._sock.recv(4096)
            if not chunk:
                raise WsError("connection closed during handshake")
            self._buf += chunk
        idx = self._buf.index(sep) + len(sep)
        out = bytes(self._buf[:idx])
        del self._buf[:idx]
        return out

    def recv_message(self) -> str | None:
        """Return the next complete text message, or None on clean close."""
        while True:
            head = self._read_exact(2)
            fin, opcode, masked, length = decode_frame_header(head[0], head[1])
            if length == 126:
                length = struct.unpack(">H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exact(8))[0]
            mask_key = self._read_exact(4) if masked else None
            payload = self._read_exact(length) if length else b""
            if mask_key:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
            if opcode == OP_CLOSE:
                return None
            if opcode == OP_PING:
                self._send_frame(payload, OP_PONG)
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CONT:
                self._fragments += payload
                if fin:
                    data = bytes(self._fragments)
                    self._fragments = bytearray()
                    return data.decode("utf-8", "replace")
                continue
            if opcode in (OP_TEXT, OP_BINARY):
                if fin:
                    return payload.decode("utf-8", "replace")
                self._fragments = bytearray(payload)
                self._fragment_opcode = opcode
                continue
            # Unknown opcode: ignore the frame.

    def _send_frame(self, payload: bytes, opcode: int) -> None:
        self._sock.sendall(encode_frame(payload, opcode))

    def send_text(self, text: str) -> None:
        self._send_frame(text.encode("utf-8"), OP_TEXT)

    def send_ping(self) -> None:
        self._send_frame(b"", OP_PING)

    def close(self) -> None:
        try:
            if self._sock is not None:
                self._send_frame(b"", OP_CLOSE)
        except Exception:
            pass
        try:
            if self._sock is not None:
                self._sock.close()
        except Exception:
            pass
        self._sock = None
