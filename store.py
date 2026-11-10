"""A single-writer, append-only binary key/value store."""

import os
import struct
import tempfile
import zlib
from pathlib import Path


MAGIC = b"LFKV1\n"
FRAME_FIELDS = struct.Struct(">II")
FRAME = struct.Struct(">III")
ENTRY = struct.Struct(">BI")
PUT, DELETE = 1, 2
LIMIT = 16 * 1024 * 1024


class CorruptLog(ValueError):
    pass


def sync(stream):
    stream.flush()
    os.fsync(stream.fileno())


def sync_directory(directory):
    if os.name == "posix":
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def encode(operation, key, value):
    if not isinstance(key, bytes) or not key or not isinstance(value, bytes):
        raise ValueError("expected a nonempty byte key and a byte value")
    if ENTRY.size + len(key) + len(value) > LIMIT:
        raise ValueError("entry exceeds the 16 MiB record limit")
    payload = ENTRY.pack(operation, len(key)) + key + value
    checksum = zlib.crc32(payload)
    fields = FRAME_FIELDS.pack(len(payload), checksum)
    return FRAME.pack(len(payload), checksum, zlib.crc32(fields)) + payload


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self._file = None
        self._index = {}
        self._open()

    def _open(self):
        try:
            self._file = self.path.open("r+b")
        except FileNotFoundError:
            self._file = self.path.open("x+b")
            try:
                self._file.write(MAGIC)
                sync(self._file)
                sync_directory(self.path.parent)
            except BaseException:
                self.close()
                raise
        try:
            self._scan()
        except BaseException:
            self.close()
            raise

    def _scan(self):
        stream = self._file
        self._index.clear()
        stream.seek(0)
        if stream.read(len(MAGIC)) != MAGIC:
            raise CorruptLog("missing or unrecognized file header")
        while True:
            offset = stream.tell()
            header = stream.read(FRAME.size)
            if not header:
                break
            if len(header) != FRAME.size:
                self._discard_tail(offset)
                break
            size, expected_crc, header_crc = FRAME.unpack(header)
            if zlib.crc32(header[:FRAME_FIELDS.size]) != header_crc:
                raise CorruptLog(f"frame header checksum mismatch at byte {offset}")
            if not ENTRY.size < size <= LIMIT:
                raise CorruptLog(f"invalid frame length at byte {offset}")
            data = stream.read(size)
            if len(data) != size:
                self._discard_tail(offset)
                break
            if zlib.crc32(data) != expected_crc:
                raise CorruptLog(f"checksum mismatch at byte {offset}")
            operation, key_size = ENTRY.unpack_from(data)
            value_start = ENTRY.size + key_size
            if not key_size or value_start > size:
                raise CorruptLog(f"invalid key length at byte {offset}")
            key = data[ENTRY.size:value_start]
            if operation == PUT:
                self._index[key] = (offset + FRAME.size + value_start, size - value_start)
            elif operation == DELETE and size == value_start:
                self._index.pop(key, None)
            else:
                raise CorruptLog(f"invalid operation at byte {offset}")

    def _discard_tail(self, offset):
        self._file.truncate(offset)
        sync(self._file)

    def _require_open(self):
        if self._file is None:
            raise ValueError("store is closed")
        return self._file

    def _append(self, operation, key, value):
        frame = encode(operation, key, value)
        stream = self._require_open()
        offset = stream.seek(0, os.SEEK_END)
        try:
            stream.write(frame)
            sync(stream)
        except OSError:
            self.close()
            raise
        return offset + FRAME.size + ENTRY.size + len(key)

    def put(self, key, value):
        offset = self._append(PUT, key, value)
        self._index[key] = (offset, len(value))

    def get(self, key):
        stream = self._require_open()
        pointer = self._index.get(key)
        if pointer is None:
            return None
        offset, length = pointer
        stream.seek(offset)
        result = stream.read(length)
        if len(result) != length:
            raise CorruptLog("unexpected end of value")
        return result

    def delete(self, key):
        self._require_open()
        if key not in self._index:
            return False
        self._append(DELETE, key, b"")
        del self._index[key]
        return True

    def compact(self):
        self._require_open()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(MAGIC)
                for key in self._index:
                    stream.write(encode(PUT, key, self.get(key)))
                sync(stream)
            self.close()
            try:
                os.replace(temporary, self.path)
                sync_directory(self.path.parent)
            finally:
                self._open()
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def close(self):
        if self._file is not None:
            stream, self._file = self._file, None
            stream.close()

    def __enter__(self):
        self._require_open()
        return self

    def __exit__(self, *_):
        self.close()
