"""Shared, expiring runtime state. Redis is mandatory in production."""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from functools import lru_cache


class MemoryStore:
    def __init__(self, capacity=10_000):
        self.lock = threading.RLock()
        self.values = {}
        self.queue = deque()
        self.capacity = capacity

    def _prune(self):
        now = time.monotonic()
        for key in [key for key, (_, expires) in self.values.items() if expires <= now]:
            del self.values[key]

    def get(self, key):
        with self.lock:
            value = self.values.get(key)
            if value and value[1] > time.monotonic():
                return value[0]
            self.values.pop(key, None)

    def set(self, key, value, ttl=600, nx=False):
        with self.lock:
            if nx and self.get(key) is not None:
                return False
            if key not in self.values and len(self.values) >= self.capacity:
                self._prune()
                if len(self.values) >= self.capacity:
                    raise RuntimeError("Runtime state capacity reached")
            self.values[key] = (value, time.monotonic() + ttl)
            return True

    def take(self, key):
        with self.lock:
            value = self.get(key)
            self.values.pop(key, None)
            return value

    def release(self, key, value):
        with self.lock:
            if self.get(key) == value:
                self.values.pop(key, None)

    def rate(self, key, limit, seconds):
        with self.lock:
            value = self.get(key)
            count = int(value or 0)
            if count >= limit:
                return False
            if value is None:
                self.set(key, "1", seconds)
            else:
                self.values[key] = (str(count + 1), self.values[key][1])
            return True

    def enqueue(self, job_id, record, limit=16):
        with self.lock:
            if self.get("job:" + job_id) is not None:
                return True
            if len(self.queue) >= limit:
                return False
            self.set("job:" + job_id, json.dumps(record), 3600)
            self.queue.append(job_id)
            return True

    def dequeue(self):
        with self.lock:
            return self.queue.popleft() if self.queue else None

    def ping(self):
        return True


class RedisStore:
    def __init__(self, url):
        import redis

        self.client = redis.Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=5,
            max_connections=32,
        )

    @staticmethod
    def key(key):
        return "degenmixer:{v1}:" + key

    def get(self, key):
        return self.client.get(self.key(key))

    def set(self, key, value, ttl=600, nx=False):
        return bool(self.client.set(self.key(key), value, ex=ttl, nx=nx))

    def take(self, key):
        return self.client.eval(
            "local v=redis.call('GET',KEYS[1]); redis.call('DEL',KEYS[1]); return v",
            1,
            self.key(key),
        )

    def release(self, key, value):
        self.client.eval(
            "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0",
            1,
            self.key(key),
            value,
        )

    def rate(self, key, limit, seconds):
        count = self.client.eval(
            "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end return n",
            1,
            self.key(key),
            seconds,
        )
        return count <= limit

    def enqueue(self, job_id, record, limit=16):
        return bool(
            self.client.eval(
                "if redis.call('EXISTS',KEYS[1])==1 then return 1 end "
                "if redis.call('LLEN',KEYS[2])>=tonumber(ARGV[3]) then return 0 end "
                "redis.call('SET',KEYS[1],ARGV[1],'EX',3600); redis.call('RPUSH',KEYS[2],ARGV[2]); return 1",
                2,
                self.key("job:" + job_id),
                self.key("queue"),
                json.dumps(record),
                job_id,
                limit,
            )
        )

    def dequeue(self):
        return self.client.lpop(self.key("queue"))

    def ping(self):
        return self.client.ping()


def production():
    return os.getenv("AXIOM_ENV", "development") == "production"


@lru_cache(maxsize=1)
def get_store():
    url = os.getenv("REDIS_URL", "").strip()
    if production() and not url:
        raise RuntimeError("REDIS_URL is required in production")
    return RedisStore(url) if url else MemoryStore()
