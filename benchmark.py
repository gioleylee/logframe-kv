"""Measure compaction on a small, repeatable update-heavy workload."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from store import Store


def run():
    keys = [f"key:{index}".encode() for index in range(100)]
    with TemporaryDirectory() as directory:
        path = Path(directory) / "benchmark.lfkv"
        with Store(path) as store:
            start = perf_counter()
            for revision in range(10):
                for key in keys:
                    store.put(key, bytes([revision]) * 256)
            write_seconds = perf_counter() - start
            before = path.stat().st_size
            start = perf_counter()
            store.compact()
            compact_seconds = perf_counter() - start
            after = path.stat().st_size
        with Store(path) as store:
            if any(store.get(key) != bytes([9]) * 256 for key in keys):
                raise RuntimeError("reopened database lost a live value")
        return {"writes": 1000, "live_keys": len(keys), "before_bytes": before,
                "after_bytes": after, "write_seconds": round(write_seconds, 3),
                "compaction_seconds": round(compact_seconds, 3)}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
