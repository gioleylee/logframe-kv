from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from store import FRAME, MAGIC, PUT, CorruptLog, Store, encode


class StoreTests(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "test.lfkv"

    def test_overwrite_delete_and_compact_survive_reopen(self):
        with Store(self.path) as store:
            store.put(b"a", b"superseded")
            store.put(b"a", b"\x00\x01")
            store.put(b"b", b"")
            store.put(b"deleted", b"data")
            self.assertTrue(store.delete(b"deleted"))
            self.assertFalse(store.delete(b"deleted"))
            before = self.path.stat().st_size
            store.compact()
            self.assertLess(self.path.stat().st_size, before)
            self.assertEqual(store.get(b"b"), b"")
        with Store(self.path) as store:
            self.assertEqual(store.get(b"a"), b"\x00\x01")
            self.assertIsNone(store.get(b"deleted"))

    def test_reopens_every_partial_frame_prefix(self):
        first = encode(PUT, b"keep", b"kept")
        tail = encode(PUT, b"lost", b"uncommitted")
        for count in range(1, len(tail)):
            with self.subTest(bytes_written=count):
                self.path.write_bytes(MAGIC + first + tail[:count])
                with Store(self.path) as store:
                    self.assertEqual(store.get(b"keep"), b"kept")
                    self.assertIsNone(store.get(b"lost"))
                    self.assertEqual(self.path.read_bytes(), MAGIC + first)

    def test_checksum_failure_is_not_silently_truncated(self):
        broken = bytearray(encode(PUT, b"key", b"value"))
        broken[FRAME.size] ^= 1
        damaged = MAGIC + broken + encode(PUT, b"second", b"still present")
        self.path.write_bytes(damaged)
        with self.assertRaisesRegex(CorruptLog, "checksum mismatch"):
            Store(self.path)
        self.assertEqual(self.path.read_bytes(), damaged)

    def test_corrupted_length_cannot_be_mistaken_for_partial_payload(self):
        broken = bytearray(encode(PUT, b"key", b"value"))
        broken[1] ^= 1
        self.path.write_bytes(MAGIC + broken)
        with self.assertRaisesRegex(CorruptLog, "header checksum"):
            Store(self.path)
