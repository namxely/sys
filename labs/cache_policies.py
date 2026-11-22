"""Zero-dependency O(1) LRU & LFU Cache Policies with workload simulator."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Generic, Iterable, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class _LRUNode(Generic[K, V]):
    __slots__ = ("key", "value", "prev", "next")

    def __init__(self, key: K | None = None, value: V | None = None) -> None:
        self.key = key
        self.value = value
        self.prev: _LRUNode[K, V] | None = None
        self.next: _LRUNode[K, V] | None = None


class LRUCache(Generic[K, V]):
    """O(1) Least Recently Used cache backed by a hash map and doubly-linked list."""

    def __init__(self, capacity: int) -> None:
        if capacity < 0:
            raise ValueError("capacity must be non-negative")
        self.capacity = capacity
        self._items: dict[K, _LRUNode[K, V]] = {}
        self._head: _LRUNode[K, V] = _LRUNode()
        self._tail: _LRUNode[K, V] = _LRUNode()
        self._head.next = self._tail
        self._tail.prev = self._head

    def _remove(self, node: _LRUNode[K, V]) -> None:
        assert node.prev is not None and node.next is not None
        node.prev.next = node.next
        node.next.prev = node.prev

    def _insert_front(self, node: _LRUNode[K, V]) -> None:
        first = self._head.next
        assert first is not None
        node.prev = self._head
        node.next = first
        self._head.next = node
        first.prev = node

    def get(self, key: K) -> V | None:
        node = self._items.get(key)
        if node is None:
            return None
        self._remove(node)
        self._insert_front(node)
        return node.value

    def put(self, key: K, value: V) -> None:
        if self.capacity == 0:
            return
        existing = self._items.get(key)
        if existing is not None:
            existing.value = value
            self._remove(existing)
            self._insert_front(existing)
            return

        if len(self._items) >= self.capacity:
            lru = self._tail.prev
            assert lru is not None and lru is not self._head and lru.key is not None
            self._remove(lru)
            del self._items[lru.key]

        node = _LRUNode(key, value)
        self._items[key] = node
        self._insert_front(node)

    def __len__(self) -> int:
        return len(self._items)


class LFUCache(Generic[K, V]):
    """O(1) Least Frequently Used cache with LRU tie-breaking per frequency bucket."""

    def __init__(self, capacity: int) -> None:
        if capacity < 0:
            raise ValueError("capacity must be non-negative")
        self.capacity = capacity
        self._vals: dict[K, tuple[V, int]] = {}
        self._buckets: dict[int, OrderedDict[K, None]] = {}
        self._min_freq = 0

    def _bump(self, key: K, new_value: V | None = None) -> V:
        val, freq = self._vals[key]
        if new_value is not None:
            val = new_value
        bucket = self._buckets[freq]
        del bucket[key]
        if not bucket:
            del self._buckets[freq]
            if self._min_freq == freq:
                self._min_freq = freq + 1

        next_freq = freq + 1
        self._vals[key] = (val, next_freq)
        if next_freq not in self._buckets:
            self._buckets[next_freq] = OrderedDict()
        self._buckets[next_freq][key] = None
        return val

    def get(self, key: K) -> V | None:
        if key not in self._vals:
            return None
        return self._bump(key)

    def put(self, key: K, value: V) -> None:
        if self.capacity == 0:
            return
        if key in self._vals:
            self._bump(key, value)
            return

        if len(self._vals) >= self.capacity:
            victim_bucket = self._buckets[self._min_freq]
            victim_key, _ = victim_bucket.popitem(last=False)
            if not victim_bucket:
                del self._buckets[self._min_freq]
            del self._vals[victim_key]

        self._vals[key] = (value, 1)
        self._min_freq = 1
        if 1 not in self._buckets:
            self._buckets[1] = OrderedDict()
        self._buckets[1][key] = None

    def __len__(self) -> int:
        return len(self._vals)


@dataclass(frozen=True)
class SimulationStats:
    """Hit/miss statistics recorded over an access trace."""

    policy: str
    capacity: int
    requests: int
    hits: int
    misses: int

    @property
    def hit_rate(self) -> float:
        return (self.hits / self.requests) if self.requests else 0.0


def evaluate_trace(
    cache: LRUCache[str, str] | LFUCache[str, str],
    policy_name: str,
    keys: Iterable[str],
) -> SimulationStats:
    """Replay a sequence of keys through a cache and compute hit/miss metrics."""
    hits = 0
    misses = 0
    for key in keys:
        if cache.get(key) is not None:
            hits += 1
        else:
            misses += 1
            cache.put(key, key)
    return SimulationStats(
        policy=policy_name,
        capacity=cache.capacity,
        requests=hits + misses,
        hits=hits,
        misses=misses,
    )


if __name__ == "__main__":
    # Hot working set ("k0".."k2") interrupted by a sequential scan ("scan_0".."scan_7")
    trace = ["k0", "k1", "k2"] * 4 + [f"scan_{i}" for i in range(8)] + ["k0", "k1", "k2"] * 3
    for policy_cls, label in ((LRUCache, "LRU"), (LFUCache, "LFU")):
        stats = evaluate_trace(policy_cls(capacity=4), label, trace)
        print(
            f"{stats.policy} (cap={stats.capacity}): "
            f"hits={stats.hits}/{stats.requests} ({stats.hit_rate:.1%})"
        )
