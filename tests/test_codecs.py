import struct
import unittest

from resilience import rcon
from resilience.ws_client import decode_frame_header, encode_frame


class WsCodecTest(unittest.TestCase):
    def test_client_frame_round_trip(self):
        frame = encode_frame(b"ping", opcode=0x1, mask_key=b"\x01\x02\x03\x04")
        fin, opcode, masked, length = decode_frame_header(frame[0], frame[1])
        self.assertTrue(fin)
        self.assertEqual(opcode, 0x1)
        self.assertTrue(masked)
        self.assertEqual(length, 4)
        mask = frame[2:6]
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(frame[6:10]))
        self.assertEqual(payload, b"ping")

    def test_long_payload_header(self):
        frame = encode_frame(b"x" * 200, opcode=0x1, mask_key=b"\x00\x00\x00\x00")
        self.assertEqual(frame[1] & 0x7F, 126)
        self.assertEqual(struct.unpack(">H", frame[2:4])[0], 200)


class RconCodecTest(unittest.TestCase):
    def test_packet_round_trip(self):
        packet = rcon.encode_packet(7, 2, "save-all flush")
        rid, ptype, body = rcon.decode_packet(packet)
        self.assertEqual((rid, ptype, body), (7, 2, "save-all flush"))

    def test_short_packet_rejected(self):
        with self.assertRaises(rcon.RconError):
            rcon.decode_packet(b"\x01\x02")


if __name__ == "__main__":
    unittest.main()
