"""Run alongside the web service when REDIS_URL is configured."""

import logging
import os
import signal
import threading

from axiom_scanner.web_runtime import ROOT, generation_loop, heartbeat_loop, market_loop


def main():
    from axiom_dashboard import _load_env_file

    _load_env_file(ROOT / ".env")
    if not os.getenv("REDIS_URL"):
        raise SystemExit("Set REDIS_URL for the shared background worker.")
    logging.basicConfig(level=logging.INFO)
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    threads = [
        threading.Thread(target=market_loop, args=(stop,)),
        threading.Thread(target=heartbeat_loop, args=(stop,)),
    ]
    for _ in range(min(max(int(os.getenv("AXIOM_GENERATION_WORKERS", "2")), 1), 8)):
        threads.append(threading.Thread(target=generation_loop, args=(stop,)))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


if __name__ == "__main__":
    main()
