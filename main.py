import argparse
import sys
import threading

from clipboard import ClipboardManager
from history import add, load, remove, clear, search


def cmd_watch(args):
    manager = ClipboardManager()
    def on_change(text):
        add(text)
        preview = text.replace("\n", " ")[:50]
        print(f"  copied: {preview}")
    manager.watch(on_change)
    print("clippy: watching clipboard... (Ctrl+C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        manager.stop()
        print("\nclippy: stopped.")


def cmd_history(args):
    items = load()
    if not items:
        print("No clipboard history.")
        return
    for i, item in enumerate(items, 1):
        preview = item["text"].replace("\n", " ")[:60]
        ts = item.get("time", "")[:16]
        tag = "  "
        print(f"{i:3d}. [{ts}]{tag}{preview}")
    print(f"\n{len(items)} item{'s' if len(items) != 1 else ''}")


def cmd_menu(args):
    import curses

    def draw(stdscr):
        curses.curs_set(0)
        stdscr.nodelay(1)
        items = load()
        selected = 0
        scroll = 0
        search_mode = False
        search_query = ""
        status_msg = ""
        msg_ttl = 0
        prev_count = len(items)

        while True:
            h, w = stdscr.getmaxyx()
            if h < 4 or w < 20:
                stdscr.erase()
                stdscr.addstr(0, 0, "Terminal too small")
                stdscr.refresh()
                curses.napms(500)
                continue

            key = stdscr.getch()

            if key == ord("q"):
                break
            elif key == ord("/") and not search_mode:
                search_mode = True
                search_query = ""
                curses.curs_set(1)
            elif key == 27:
                if search_mode:
                    search_mode = False
                    curses.curs_set(0)
            elif search_mode:
                if key in (10, 13):
                    search_mode = False
                    curses.curs_set(0)
                    if search_query:
                        results = search(search_query)
                        if results:
                            selected = results[0][0]
                            status_msg = f"found {len(results)} match{'es' if len(results) != 1 else ''} for \"{search_query}\""
                            msg_ttl = 30
                        else:
                            status_msg = f"no matches for \"{search_query}\""
                            msg_ttl = 30
                    search_query = ""
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    search_query = search_query[:-1]
                elif 32 <= key <= 126:
                    search_query += chr(key)
            else:
                if key in (curses.KEY_DOWN, ord("j")):
                    if selected < len(items) - 1:
                        selected += 1
                elif key in (curses.KEY_UP, ord("k")):
                    if selected > 0:
                        selected -= 1
                elif key == ord("g"):
                    selected = 0
                elif key == ord("G"):
                    selected = len(items) - 1
                elif key in (10, 13):
                    if items:
                        text = items[selected]["text"]
                        ClipboardManager().set(text)
                        status_msg = f"copied item {selected + 1}"
                        msg_ttl = 20
                elif key == ord("n"):
                    if search_query:
                        results = search(search_query)
                        if results:
                            cur = next((i for i, (idx, _) in enumerate(results) if idx == selected), -1)
                            next_idx = (cur + 1) % len(results)
                            selected = results[next_idx][0]
                            status_msg = f"match {next_idx + 1}/{len(results)}"
                            msg_ttl = 20
                elif key == ord("d"):
                    if items:
                        remove(selected)
                        items = load()
                        selected = min(selected, max(0, len(items) - 1))
                        status_msg = f"deleted item {selected + 1}"
                        msg_ttl = 20
                elif key == ord("c"):
                    clear()
                    items = []
                    selected = 0
                    scroll = 0
                    status_msg = "history cleared"
                    msg_ttl = 30
                elif key in (ord("r"), ord("R")):
                    items = load()
                    selected = min(selected, max(0, len(items) - 1))
                    status_msg = "refreshed"
                    msg_ttl = 15

            list_height = h - 3
            selected = max(0, min(selected, max(0, len(items) - 1)))
            if selected < scroll:
                scroll = selected
            elif selected >= scroll + list_height:
                scroll = selected - list_height + 1

            stdscr.erase()
            title = " clippy - clipboard history "
            stdscr.addstr(0, max(0, w // 2 - len(title) // 2), title, curses.A_REVERSE)

            visible = items[scroll:scroll + list_height]
            for i, item in enumerate(visible):
                idx = scroll + i
                line = f" {idx + 1:3d}. {item['text'].replace(chr(10), ' ')[:w - 7]}"
                attr = curses.A_REVERSE if idx == selected else curses.A_NORMAL
                stdscr.addstr(1 + i, 0, line[:w - 1], attr)

            if items and 0 <= selected < len(items):
                text = items[selected]["text"]
                if text:
                    preview = text.replace("\n", "↵ ")
                    preview_y = max(1, h - 2)
                    if len(preview) > w:
                        preview = preview[:w - 3] + "..."
                    stdscr.addstr(preview_y, 0, preview[:w - 1])

            if msg_ttl > 0:
                msg_ttl -= 1
                stdscr.addstr(h - 1, 0, f" {status_msg}" + " " * (w - len(status_msg) - 3))
            elif search_mode:
                prompt = f" search: {search_query}_"
                stdscr.addstr(h - 1, 0, prompt + " " * (w - len(prompt)))
            else:
                nav = f" {selected + 1}/{len(items)}  /search  n=next  d=del  c=clear  enter=copy  q=quit"
                stdscr.addstr(h - 1, 0, nav[:w - 1])

            stdscr.refresh()
            curses.napms(40)

    curses.wrapper(draw)


def main():
    parser = argparse.ArgumentParser(prog="clippy", description="Clipboard History Manager")
    parser.add_argument("command", nargs="?", default="menu",
                        choices=["watch", "history", "menu"],
                        help="Command to run (default: menu)")
    parser.add_argument("--version", action="version", version="clippy 1.1")
    args = parser.parse_args()

    if args.command == "watch":
        cmd_watch(args)
    elif args.command == "history":
        cmd_history(args)
    else:
        cmd_menu(args)


if __name__ == "__main__":
    main()
