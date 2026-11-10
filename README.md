# LogFrame KV

A single-writer binary key/value store built on an append-only file. It rebuilds a key-to-offset index on open, recovers from incomplete tail writes, and compacts obsolete records. Values are read from disk on demand.

```sh
python cli.py demo.lfkv put project LogFrame
python cli.py demo.lfkv get project
python cli.py demo.lfkv compact
python -m unittest -v
python benchmark.py
```

Use Python 3.11+. The library works with byte keys and byte values. The CLI encodes arguments as UTF-8 and writes raw value bytes.

## Format and recovery

The file begins with a version marker. Each frame contains a big-endian payload length, payload CRC32, header CRC32, and payload. The payload stores a one-byte operation, a key length, a key, and any value bytes. One frame is limited to 16 MiB.

Writes append a frame and sync it before updating the in-memory index. Opening scans forward, checking both checksums. A partial final header or a short payload after a valid header is truncated at the start of the incomplete frame. A checksum mismatch raises an error and preserves the file for inspection. The test suite reopens a log after every possible partial write of one fixture frame.

Compaction writes the live values to a new file in the same directory, syncs it, and replaces the original. The store syncs directory metadata on POSIX. Durability still depends on filesystem and platform guarantees, particularly around the directory entry on Windows. Use one process and one active store handle per file. Startup scans the full log and the index retains one key and pointer per live entry.

## Measured workload

The benchmark writes ten 256-byte revisions for each of 100 keys. Compaction reduces the file from 278,906 bytes to 27,896 bytes, about 90%, and the benchmark verifies all 100 latest values after reopening.
