"""Unit tests for namxely/sys labs."""

import unittest

from labs.cache_policies import LFUCache, LRUCache, evaluate_trace
from labs.resp_protocol import (
    RespErrorValue,
    RespProtocolError,
    RespStreamDecoder,
    SimpleString,
    encode_resp,
)


class CachePolicyTests(unittest.TestCase):
    def test_lru_eviction_and_recency_update(self) -> None:
        cache: LRUCache[str, int] = LRUCache(capacity=2)
        cache.put("a", 1)
        cache.put("b", 2)
        self.assertEqual(cache.get("a"), 1)  # "a" becomes MRU; "b" becomes LRU
        cache.put("c", 3)
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("a"), 1)
        self.assertEqual(cache.get("c"), 3)

    def test_lfu_evicts_lowest_frequency_with_lru_tie_break(self) -> None:
        cache: LFUCache[str, int] = LFUCache(capacity=2)
        cache.put("a", 1)
        cache.put("b", 2)
        self.assertEqual(cache.get("a"), 1)  # freq("a")=2, freq("b")=1
        cache.put("c", 3)  # evicts "b"
        self.assertIsNone(cache.get("b"))
        self.assertEqual(cache.get("a"), 1)  # freq("a")=3
        self.assertEqual(cache.get("c"), 3)  # freq("c")=2

    def test_scan_resistance_lfu_beats_lru_on_hot_set(self) -> None:
        trace = ["hot0", "hot1", "hot2"] * 4 + [f"scan_{i}" for i in range(6)] + ["hot0", "hot1", "hot2"] * 2
        lru_stats = evaluate_trace(LRUCache(4), "LRU", trace)
        lfu_stats = evaluate_trace(LFUCache(4), "LFU", trace)
        self.assertGreater(lfu_stats.hits, lru_stats.hits)


class RespProtocolTests(unittest.TestCase):
    def test_round_trip_nested_and_special_types(self) -> None:
        samples = [
            SimpleString("PONG"),
            RespErrorValue("ERR unknown command"),
            -123,
            None,
            "Xin chào RESP2",
            ["SET", "k1", "v1"],
            ["MULTI", [1, None, SimpleString("QUEUED")]],
        ]
        wire = b"".join(encode_resp(item) for item in samples)
        decoder = RespStreamDecoder()
        for i in range(len(wire)):
            decoder.feed(wire[i : i + 1])  # 1-byte chunks
        self.assertEqual(decoder.pop_all(), samples)

    def test_null_array_and_binary_bulk(self) -> None:
        decoder = RespStreamDecoder()
        decoder.feed(b"*-1\r\n$3\r\n\xff\x00\xfe\r\n")
        frames = decoder.pop_all()
        self.assertEqual(frames[0], None)
        self.assertEqual(frames[1], b"\xff\x00\xfe")

    def test_malformed_prefix_raises(self) -> None:
        decoder = RespStreamDecoder()
        decoder.feed(b"!bad\r\n")
        with self.assertRaises(RespProtocolError):
            decoder.try_pop()


if __name__ == "__main__":
    unittest.main()
