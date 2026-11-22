import math
import struct
import unittest

from bots.lily import protocol as p


class TestLilyWire(unittest.TestCase):
    def test_command(self):
        body = dict(sample_id=42, revision=8, steps=[dict(duration_ms=100, forward=0.75, strafe=-0.5, buttons=3)])
        self.assertEqual(p.encode_command(p.MOTOR,body,9), struct.pack("<dIIBHbbbbBBB",9,42,8,1,100,75,-50,0,0,3,0,0))
        for field, value in (("forward", math.nan), ("duration_ms", True), ("buttons",32), ("force",3), ("oops",1)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                p.encode_command(p.MOTOR,dict(body, steps=[dict(body["steps"][0], **{field:value})]),9)
        with self.assertRaises(ValueError):
            p.encode_command(p.MOTOR,dict(body, steps=body["steps"]*6),9)
        with self.assertRaises(ValueError):
            p.encode_command(p.MOTOR,body,math.inf)

    def test_events(self):
        record = struct.pack("<IiBB3fff",17,5,1,11,1,2,3,4,9)
        payload = struct.pack("<IIB",8,6,1)+record
        data = p.decode_event(p.OFFERS,payload)
        self.assertEqual(data["choices"][0]["class"],"item")
        self.assertEqual(data["choices"][0]["position"], [1,2,3])
        for bad in (payload[:-1],payload+b"!",payload[:-4]+struct.pack("<f",math.nan),payload*24,4):
            self.assertIsNone(p.decode_event(p.OFFERS,bad))
        progress = struct.pack("<IIIBBBBIi",43,7,9,1,4,0,1,500,17)
        self.assertEqual(p.decode_event(p.PROGRESS,progress)["outcome"],"arrived")
