import argparse
import sys
from pathlib import Path

from store import Store


def main():
    parser = argparse.ArgumentParser(description="Read or modify a LogFrame database.")
    parser.add_argument("database", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    put = commands.add_parser("put")
    put.add_argument("key")
    put.add_argument("value")
    commands.add_parser("get").add_argument("key")
    commands.add_parser("delete").add_argument("key")
    commands.add_parser("compact")
    args = parser.parse_args()
    try:
        with Store(args.database) as store:
            if args.command == "compact":
                store.compact()
            else:
                key = args.key.encode()
                if args.command == "put":
                    store.put(key, args.value.encode())
                elif args.command == "get":
                    value = store.get(key)
                    if value is None:
                        return 1
                    sys.stdout.buffer.write(value)
                elif not store.delete(key):
                    return 1
    except (ValueError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
