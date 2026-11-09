"""Minecraft (Source) RCON client, standard library only.

Protocol: little-endian packets of
  int32 length | int32 request id | int32 type | body | 0x00 0x00
type 3 = login, type 2 = command, type 0 = response value.
"""
from __future__ import annotations

import socket
import struct


class RconError(Exception):
    pass


def encode_packet(request_id: int, packet_type: int, body: str) -> bytes:
    payload = struct.pack("<ii", request_id, packet_type) + body.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(payload)) + payload


def decode_packet(data: bytes):
    if len(data) < 14:
        raise RconError("packet too short")
    length = struct.unpack("<i", data[:4])[0]
    request_id, packet_type = struct.unpack("<ii", data[4:12])
    body = data[12:4 + length - 2].decode("utf-8", "replace")
    return request_id, packet_type, body


class RconClient:
    def __init__(self, host: str, port: int, password: str, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._sock = None
        self._next_id = 1

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def connect(self) -> None:
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        rid = self._alloc_id()
        self._send(rid, 3, self.password)
        resp_id, _type, _body = self._recv()
        if resp_id == -1:
            raise RconError("authentication failed")

    def command(self, cmd: str) -> str:
        rid = self._alloc_id()
        self._send(rid, 2, cmd)
        _id, _type, body = self._recv()
        return body

    def close(self) -> None:
        try:
            if self._sock is not None:
                self._sock.close()
        finally:
            self._sock = None

    def _alloc_id(self) -> int:
        rid = self._next_id
        self._next_id += 1
        return rid

    def _send(self, rid: int, packet_type: int, body: str) -> None:
        self._sock.sendall(encode_packet(rid, packet_type, body))

    def _recv(self):
        header = self._read_exact(4)
        length = struct.unpack("<i", header)[0]
        data = header + self._read_exact(length)
        return decode_packet(data)

    def _read_exact(self, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise RconError("connection closed")
            buf += chunk
        return bytes(buf)
