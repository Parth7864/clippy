import argparse
import time

from clipboard import get_clipboard
from history import add, show


def watch():
    print("Clippy is watching the clipboard...")
    print("Press Ctrl+C to stop.\n")

    last = ""

    try:
        while True:
            current = get_clipboard()

            if current != last:
                add(current)
                print("Copied:", current[:50])
                last = current

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\nStopped.")


def main():
    parser = argparse.ArgumentParser(
        prog="clippy",
        description="Simple Clipboard History Manager"
    )

    parser.add_argument(
        "command",
        choices=["watch", "history"],
        help="Command to run"
    )

    args = parser.parse_args()

    if args.command == "watch":
        watch()

    elif args.command == "history":
        show()


if __name__ == "__main__":
    main()