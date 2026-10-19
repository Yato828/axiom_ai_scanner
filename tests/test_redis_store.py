"""Exercise the production Redis commands/Lua against a shared Redis emulator."""

import json
import unittest
from concurrent.futures import ThreadPoolExecutor

try:
    import fakeredis
except ImportError:
    fakeredis = None

from axiom_scanner.web_store import RedisStore


@unittest.skipUnless(
    fakeredis, "Install requirements-dev.txt for Redis integration checks"
)
class RedisStoreTests(unittest.TestCase):
    def setUp(self):
        server = fakeredis.FakeServer()
        self.stores = []
        for _ in range(2):
            store = RedisStore.__new__(RedisStore)
            store.client = fakeredis.FakeRedis(server=server, decode_responses=True)
            self.stores.append(store)

    def test_sessions_and_single_use_challenges_are_shared_between_instances(self):
        first, second = self.stores
        first.set("session:test", json.dumps({"wallet": "test"}), 60)
        self.assertEqual(json.loads(second.get("session:test")), {"wallet": "test"})
        first.set("challenge:test", "proof", 60)
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(
                pool.map(lambda n: self.stores[n % 2].take("challenge:test"), range(20))
            )
        self.assertEqual(results.count("proof"), 1)

    def test_distributed_rate_limit_is_atomic(self):
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(
                pool.map(lambda n: self.stores[n % 2].rate("limit", 7, 60), range(30))
            )
        self.assertEqual(sum(results), 7)

    def test_old_lease_owner_cannot_release_a_new_lock(self):
        first, second = self.stores
        self.assertTrue(first.set("lock", "old", 60, nx=True))
        self.assertFalse(second.set("lock", "new", 60, nx=True))
        first.take("lock")
        self.assertTrue(second.set("lock", "new", 60, nx=True))
        first.release("lock", "old")
        self.assertEqual(first.get("lock"), "new")

    def test_queue_is_shared_bounded_and_idempotent(self):
        first, second = self.stores
        self.assertTrue(first.enqueue("one", {"wallet": "a"}, limit=1))
        self.assertTrue(second.enqueue("one", {"wallet": "a"}, limit=1))
        self.assertFalse(second.enqueue("two", {"wallet": "b"}, limit=1))
        self.assertEqual(second.dequeue(), "one")
        self.assertIsNone(first.dequeue())
        self.assertIsNotNone(second.get("job:one"))


if __name__ == "__main__":
    unittest.main()
