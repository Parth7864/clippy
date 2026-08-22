import argparse
import json
import logging
import os
import platform
import shlex
import subprocess
import sys
import tempfile
import threading
import warnings
from datetime import datetime
from queue import Queue, Empty

from .clipboard import ClipboardManager, ClipboardError
from .core import (
    add, load, remove, clear, search, delete_indices, update, toggle_favorite,
    dedupe, truncate, backup, export_history, import_file, stats, top, count,
    plural, parse_range, fail,
)


def cmd_watch(args):
    manager = ClipboardManager()

    def on_change(text):
        add(text)
        print(f"  copied: {text.replace(chr(10), ' ')[:50]}")

    manager.watch(on_change)
    print("clippy: watching clipboard... (Ctrl+C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        manager.stop()
        print("\nclippy: stopped.")


def cmd_history(args):
    items = load()
    if args.json is not None:
        print(json.dumps(_numbered_items(items)))
        return
    if not items:
        print("No clipboard history.")
        return
    for i, item in enumerate(items, 1):
        star = "★" if item.get("favorite") else " "
        preview = item["text"].replace("\n", " ")[:52]
        ts = item.get("time", "")[:16]
        cnt = item.get("count", 1)
        print(f"{i:3d}. {star} [{ts}] ({cnt}x) {preview}")
    print(f"\n{len(items)} {plural(len(items), 'item')}")


def _numbered_items(items):
    return [{"index": n, **item} for n, item in enumerate(items)]


def cmd_search(args):
    items = load()
    q = (args.spec or "").lower()
    if not q:
        return fail("Usage: clippy search <query>")
    results = [(i, item) for i, item in enumerate(items) if q in item["text"].lower()]
    if args.json is not None:
        print(json.dumps({"query": args.spec,
                          "count": len(results),
                          "items": [{"index": i, **it} for i, it in results]}))
        return
    if not results:
        print(f'No matches for "{args.spec}".')
        return
    for idx, item in results:
        star = "★" if item.get("favorite") else " "
        print(f"{idx + 1:3d}. {star} {item['text'].replace(chr(10), ' ')[:60]}")
    print(f"\n{len(results)} {plural(len(results), 'match')}")


def cmd_top(args):
    try:
        n = int(args.spec or "10")
    except ValueError:
        n = 10
    ranked = top(n)
    if args.json is not None:
        print(json.dumps({"items": [{"rank": i, **it} for i, it in enumerate(ranked, 1)]}))
        return
    if not ranked:
        print("No clipboard history.")
        return
    print(f"top {len(ranked)} most copied:")
    for i, item in enumerate(ranked, 1):
        star = "★" if item.get("favorite") else " "
        preview = item["text"].replace("\n", " ")[:50]
        print(f"{i:3d}. {star} {item.get('count', 1):4d}x  {preview}")


def cmd_stats(args):
    s = stats()
    if args.json is not None:
        print(json.dumps(s))
        return
    if not s.get("total"):
        print("No clipboard history.")
        return
    print("clippy stats")
    print(f"  items stored:       {s['total']}")
    print(f"  favorites:          {s['favorites']}")
    print(f"  copies captured:    {s['total_copies']}")
    print(f"  total characters:   {s['total_chars']}")
    print(f"  total lines:        {s['total_lines']}")
    print(f"  average length:     {s['avg_len']}")
    print(f"  longest item:       {s['longest']} chars")
    print(f"  most copied:        {s['most_copied_preview']} ({s['most_copied']}x)")
    if s.get("first_time"):
        print(f"  first capture:      {s['first_time'][:16]}")
        print(f"  last capture:       {s['last_time'][:16]}")


def cmd_get(args):
    idx = get_index(args)
    if idx is None:
        warnings.warn("clippy get: invalid index argument", UserWarning)
        return fail("Usage: clippy get <index>  (or 1 for the most recent)\n  Hint: `clippy history` to see indices; indices are 1-based (1 = most recent)")
    try:
        items = load()
    except Exception as e:
        warnings.warn(f"clippy get: load failed: {e}", RuntimeWarning)
        return fail(f"Cannot load history: {e} — try `clippy doctor --fix`")
    if not items:
        warnings.warn("clippy get: history is empty", UserWarning)
        return fail("No clipboard history — copy something first, or `clippy set \"text\"`")
    if idx < 0 or idx >= len(items):
        warnings.warn(f"clippy get: index {idx+1} out of range (1..{len(items)})", UserWarning)
        return fail(f"Index {idx+1} out of range (1..{len(items)}). Try `clippy history` to see valid indices.")
    item = items[idx]
    if not isinstance(item, dict) or "text" not in item:
        warnings.warn(f"clippy get: item {idx+1} malformed: {item!r}", RuntimeWarning)
        return fail(f"Item {idx+1} is malformed — try `clippy doctor --fix`")
    out = item["text"].rstrip("\n")
    if args.json:
        print(json.dumps(item))
    else:
        print(out)
    return 0


def cmd_set(args):
    spec = args.spec or ""
    if args.file:
        if not os.path.exists(args.file):
            warnings.warn(f"clippy set: file not found: {args.file}", UserWarning)
            return fail(f"No such file: {args.file}")
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                spec = f.read()
            if not spec:
                warnings.warn(f"clippy set: file {args.file} is empty", UserWarning)
        except OSError as e:
            warnings.warn(f"clippy set: cannot read {args.file}: {e}", RuntimeWarning)
            return fail(f"Could not read file: {e} — check permissions")
        except UnicodeDecodeError as e:
            warnings.warn(f"clippy set: file {args.file} not utf-8: {e}", RuntimeWarning)
            return fail(f"File {args.file} is not valid UTF-8: {e}")
    elif args.stdin:
        try:
            spec = sys.stdin.read()
        except Exception as e:
            warnings.warn(f"clippy set: stdin read failed: {e}", RuntimeWarning)
            return fail(f"Cannot read stdin: {e}")
    if not spec:
        warnings.warn("clippy set: empty text — nothing to save", UserWarning)
        return fail("Usage: clippy set <text>  (or --stdin / --file <path>)\n  Examples: clippy set \"hello\"  |  echo hi | clippy set --stdin  |  clippy set --file notes.txt")
    if len(spec) > 100_000:
        warnings.warn(f"clippy set: text very large ({len(spec)} chars) — truncated", UserWarning)
    try:
        add(spec)
    except Exception as e:
        warnings.warn(f"clippy set: add() failed: {e}", RuntimeWarning)
        return fail(f"Failed to save: {e} — try `clippy doctor --fix`")
    try:
        ClipboardManager().set(spec.rstrip("\n"))
    except ClipboardError as e:
        warnings.warn(f"clippy set: clipboard write failed: {e}", RuntimeWarning)
        plat = platform.system()
        hint = {"Linux": "sudo apt install xclip wl-clipboard", "Darwin": "xcode-select --install", "Windows": "reinstall Python with tcl/tk"}.get(plat, "")
        return fail(f"Saved to history but clipboard copy failed: {e}\n  Hint: {hint}\n  Run `clippy doctor` for diagnostics.")
    except Exception as e:
        warnings.warn(f"clippy set: unexpected clipboard error: {e}", RuntimeWarning)
        return fail(f"Clipboard error: {e}")
    if args.json:
        print(json.dumps({"added": True, "copied": True}))
    else:
        print("added and copied to clipboard")
    return 0


def cmd_api(args):
    path = args.spec or "/api/history"
    port = args.port or 8765
    client = f"http://127.0.0.1:{port}{path}"

    import urllib.request
    from urllib.error import URLError, HTTPError

    method = args.method.upper()
    body = None
    headers = {}
    if method in ("POST", "PUT") and (args.json is True or args.data is not None):
        payload = args.data if args.data is not None else json.dumps({"text": args.extra or ""})
        body = payload.encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(client, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
            if args.json is not False:
                try:
                    print(json.dumps(json.loads(content), indent=2))
                except ValueError:
                    print(content)
            else:
                print(content)
    except HTTPError as e:
        return fail(f"HTTP {e.code}: {e.read().decode(errors='ignore')}")
    except URLError as e:
        return fail(f"Could not reach clippy server at {client}. Is `clippy serve` running? ({e.reason})")
    return 0


def get_index(args):
    try:
        return int(args.spec or "1") - 1
    except ValueError:
        return None


def cmd_dedupe(args):
    before = len(load())
    items = dedupe()
    removed = before - len(items)
    if args.json is not None:
        print(json.dumps({"removed": removed, "remaining": len(items)}))
        return
    print(f"Removed {removed} {plural(removed, 'duplicate')}. {len(items)} remain.")


def cmd_backup(args):
    path = backup()
    if args.json is not None:
        print(json.dumps({"backup": path, "created": bool(path)}))
        return
    if not path:
        print("Nothing to back up.")
    else:
        print(f"Backup saved to {path}")


def cmd_export(args):
    fmt = (args.spec or "json").lower()
    if fmt not in ("json", "txt", "md", "markdown"):
        warnings.warn(f"clippy export: unknown format '{fmt}'", UserWarning)
        return fail("Format must be json, txt, or md.\n  Usage: clippy export [json|txt|md] [file]")
    try:
        ext, content = export_history(fmt)
    except Exception as e:
        warnings.warn(f"clippy export: export_history failed: {e}", RuntimeWarning)
        return fail(f"Export failed: {e}")
    outfile = args.extra or f"clippy_export.{ext}"
    if os.path.exists(outfile) and not getattr(args, "fix", False):
        warnings.warn(f"clippy export: {outfile} already exists — will overwrite", UserWarning)
    try:
        with open(outfile, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        warnings.warn(f"clippy export: cannot write {outfile}: {e}", RuntimeWarning)
        return fail(f"Cannot write {outfile}: {e} — check permissions/disk space")
    except Exception as e:
        warnings.warn(f"clippy export: write failed: {e}", RuntimeWarning)
        return fail(f"Export write failed: {e}")
    try:
        c = count()
    except Exception:
        c = "?"
    print(f"Exported {c} items to {outfile}")
    return 0


def cmd_import(args):
    path = args.spec
    if not path:
        return fail("Usage: clippy import <file.json>")
    if not os.path.exists(path):
        return fail(f"No such file: {path}")
    try:
        added = import_file(path)
    except Exception as e:
        return fail(f"Import failed: {e}")
    print(f"Imported {added} new {plural(added, 'item')}.")


def cmd_favorite(args):
    items = load()
    try:
        idx = int(args.spec or "") - 1
    except ValueError:
        return fail("Usage: clippy favorite <index>")
    if not (0 <= idx < len(items)):
        return fail("Index out of range.")
    toggle_favorite(idx)
    items = load()
    if args.json is not None:
        print(json.dumps({"index": idx + 1, "favorite": items[idx].get("favorite")}))
        return
    state = "favorited ★" if items[idx].get("favorite") else "unfavorited"
    print(f"Item {idx + 1} {state}.")


def cmd_edit(args):
    items = load()
    try:
        idx = int(args.spec or "") - 1
    except ValueError:
        return fail("Usage: clippy edit <index>")
    if not (0 <= idx < len(items)):
        return fail("Index out of range.")
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    original = items[idx]["text"]
    fd, path = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w") as f:
        f.write(original)
    subprocess.call(shlex.split(editor) + [path])
    with open(path) as f:
        new_text = f.read()
    os.unlink(path)
    if new_text != original:
        update(idx, new_text)
        print(f"Item {idx + 1} updated.")
    else:
        print("No changes.")


def cmd_truncate(args):
    try:
        n = int(args.spec or "")
    except ValueError:
        return fail("Usage: clippy truncate <n>")
    items = truncate(n)
    if args.json is not None:
        print(json.dumps({"remaining": len(items)}))
        return
    print(f"Truncated to {len(items)} {plural(len(items), 'item')}.")


def cmd_delete(args):
    items = load()
    if not items:
        if args.json is not None:
            print(json.dumps({"deleted": 0}))
        else:
            print("No clipboard history.")
        return
    spec = args.spec or ""
    if spec.strip().lower() == "all":
        clear()
        if args.json is not None:
            print(json.dumps({"deleted": len(items), "cleared": True}))
        else:
            print(f"Cleared all {len(items)} {plural(len(items), 'item')}.")
        return
    indices = [i for i in parse_range(spec) if 0 <= i < len(items)]
    if not indices:
        return fail("Invalid range. Use e.g. 3, 3-10, 1,3,7 or all.")
    delete_indices(indices)
    if args.json is not None:
        print(json.dumps({"deleted": len(indices)}))
    else:
        print(f"Deleted {len(indices)} {plural(len(indices), 'item')}.")


def cmd_menu(args):
    try:
        import curses
    except ImportError as e:
        warnings.warn(f"clippy menu: curses unavailable on {platform.system()}: {e}", RuntimeWarning)
        if platform.system() == "Windows":
            return fail(
                "`clippy menu` is not available — Python on Windows has no built-in curses.\n"
                "  Fix:  pip install windows-curses\n"
                "  Then run `clippy menu` again, or use `clippy history` / `clippy gui` instead.\n"
                "  Diagnostics: clippy doctor"
            )
        return fail(
            f"`clippy menu` needs curses but it is not installed: {e}\n"
            "  Linux: sudo apt install python3-dev  |  macOS: curses is built-in\n"
            "  Diagnostics: clippy doctor"
        )

    mgr = ClipboardManager()
    new_items = Queue()

    def on_change(text):
        add(text)
        new_items.put({"text": text, "time": datetime.now().isoformat(timespec="seconds"),
                       "count": 1, "favorite": False})

    mgr.watch(on_change)

    def draw(stdscr):
        curses.curs_set(0)
        stdscr.nodelay(1)

        use_color = curses.has_colors()
        if use_color:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, 0)
            curses.init_pair(2, curses.COLOR_YELLOW, 0)
            curses.init_pair(3, curses.COLOR_MAGENTA, 0)
            GREEN = curses.color_pair(1)
            YELLOW = curses.color_pair(2)
            MAGENTA = curses.color_pair(3)
        else:
            GREEN = curses.A_NORMAL
            YELLOW = curses.A_BOLD
            MAGENTA = curses.A_BOLD

        items = load()
        favorites_only = False
        selected = 0
        scroll = 0
        search_mode = False
        search_query = ""
        status_msg = ""
        msg_ttl = 0
        flash_frames = 0

        def get_view():
            if favorites_only:
                return [(i, item) for i, item in enumerate(items) if item.get("favorite")]
            return [(i, item) for i, item in enumerate(items)]

        def put(y, text, attr=curses.A_NORMAL):
            try:
                stdscr.addstr(y, 0, text[:max(0, stdscr.getmaxyx()[1] - 1)], attr)
            except curses.error:
                pass

        def run_editor(real_idx):
            editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
            text = items[real_idx]["text"]
            fd, path = tempfile.mkstemp(suffix=".txt")
            with os.fdopen(fd, "w") as f:
                f.write(text)
            curses.def_prog_mode()
            curses.endwin()
            subprocess.call(shlex.split(editor) + [path])
            curses.reset_prog_mode()
            stdscr.refresh()
            with open(path) as f:
                new_text = f.read()
            os.unlink(path)
            if new_text != text:
                update(real_idx, new_text)
                return True
            return False

        while True:
            h, w = stdscr.getmaxyx()
            if h < 4 or w < 30:
                stdscr.erase()
                stdscr.addstr(0, 0, "Terminal too small")
                stdscr.refresh()
                curses.napms(500)
                continue

            if not search_mode:
                try:
                    while True:
                        items.insert(0, new_items.get_nowait())
                        selected = 0
                        scroll = 0
                        flash_frames = 8
                        status_msg = "new clipboard item"
                        msg_ttl = 20
                except Empty:
                    pass

            view = get_view()
            if not view:
                selected = 0
            else:
                selected = max(0, min(selected, len(view) - 1))

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
                    search_query = ""
                    curses.curs_set(0)
            elif search_mode:
                if key in (10, 13):
                    search_mode = False
                    curses.curs_set(0)
                    if search_query:
                        matches = [i for i, (ri, it) in enumerate(view)
                                   if search_query.lower() in it["text"].lower()]
                        if matches:
                            selected = matches[0]
                            status_msg = f"found {len(matches)} {plural(len(matches), 'match')}"
                            msg_ttl = 25
                        else:
                            status_msg = "no matches"
                            msg_ttl = 20
                    search_query = ""
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    search_query = search_query[:-1]
                elif 32 <= key <= 126:
                    search_query += chr(key)
            else:
                if key in (curses.KEY_DOWN, ord("j")):
                    selected += 1
                elif key in (curses.KEY_UP, ord("k")):
                    selected -= 1
                elif key in (curses.KEY_NPAGE, ord("f")):
                    selected += h - 4
                elif key in (curses.KEY_PPAGE, ord("b")):
                    selected -= h - 4
                elif key == ord("g"):
                    selected = 0
                elif key == ord("G"):
                    selected = len(view) - 1
                elif key in (10, 13):
                    if view:
                        ClipboardManager().set(view[selected][1]["text"])
                        status_msg = f"copied item {view[selected][0] + 1}"
                        msg_ttl = 20
                elif key == ord("c"):
                    clear()
                    items = []
                    selected = 0
                    scroll = 0
                    status_msg = "history cleared"
                    msg_ttl = 25
                elif key == ord("d"):
                    if view:
                        remove(view[selected][0])
                        items = load()
                        selected = min(selected, max(0, len(get_view()) - 1))
                        status_msg = "item deleted"
                        msg_ttl = 20
                elif key == ord("e"):
                    if view:
                        changed = run_editor(view[selected][0])
                        items = load()
                        status_msg = "item edited" if changed else "no changes"
                        msg_ttl = 20
                elif key == ord("f"):
                    if view:
                        toggle_favorite(view[selected][0])
                        items = load()
                        fav = items[view[selected][0]].get("favorite")
                        status_msg = "★ favorited" if fav else "unfavorited"
                        msg_ttl = 20
                elif key == ord("F"):
                    favorites_only = not favorites_only
                    selected = 0
                    scroll = 0
                    status_msg = "favorites only ★" if favorites_only else "all items"
                    msg_ttl = 20
                elif key == ord("n"):
                    if search_query:
                        matches = [i for i, (ri, it) in enumerate(view)
                                   if search_query.lower() in it["text"].lower()]
                        if matches:
                            cur = next((i for i, m in enumerate(matches) if m == selected), -1)
                            nxt = (cur + 1) % len(matches)
                            selected = matches[nxt]
                            status_msg = f"match {nxt + 1}/{len(matches)}"
                            msg_ttl = 20

            view = get_view()
            if not view:
                selected = 0
            else:
                selected = max(0, min(selected, len(view) - 1))
            list_height = h - 3
            if selected < scroll:
                scroll = selected
            elif selected >= scroll + list_height:
                scroll = min(len(view) - 1, selected - list_height + 1)

            stdscr.erase()

            header_left = " clippy · clipboard history "
            if favorites_only:
                header_left += "★ "
            header_right = f" ● {len(view)} {plural(len(view), 'item')} "
            right_x = w - len(header_right)
            left_w = max(0, right_x - 1)
            put(0, header_left[:left_w], curses.A_REVERSE)
            put(0, " " + header_right.strip() + " ", curses.A_REVERSE | GREEN)

            visible = view[scroll:scroll + list_height]
            for i, (ri, item) in enumerate(visible):
                idx = scroll + i
                ts = item.get("time", "")[5:16]
                text = item["text"].replace("\n", " ")
                num_lines = item["text"].count("\n") + 1
                tag = f" [{num_lines}L]" if num_lines > 1 else ""
                star = "★" if item.get("favorite") else " "
                cnt = item.get("count", 1)
                avail = max(10, w - 28)
                line = f" {ri + 1:3d} {star} {ts} {cnt:3d}x {text[:avail]}{tag}"
                attr = curses.A_NORMAL
                if idx == selected:
                    attr = curses.A_REVERSE
                    if flash_frames > 0 and idx == 0:
                        attr |= YELLOW
                elif item.get("favorite"):
                    attr = MAGENTA
                put(1 + i, line, attr)

            if flash_frames > 0:
                flash_frames -= 1

            sep_y = 1 + len(visible)
            if sep_y < h - 1 and sep_y >= 0:
                put(sep_y, "─" * (w - 1))

            preview_y = sep_y + 1
            if view and preview_y < h - 1 and 0 <= selected < len(view):
                text = view[selected][1]["text"]
                if text:
                    preview = text.replace("\n", " ↵ ")
                    if len(preview) > w:
                        preview = preview[:w - 3] + "..."
                    put(preview_y, " " + preview)

            if msg_ttl > 0:
                msg_ttl -= 1
                put(h - 1, f" {status_msg}")
            elif search_mode:
                count_txt = ""
                if search_query:
                    m = [i for i, (ri, it) in enumerate(view)
                         if search_query.lower() in it["text"].lower()]
                    count_txt = f" ({len(m)})"
                put(h - 1, f" search{count_txt}: {search_query}_")
            else:
                put(h - 1,
                    f" {selected + 1}/{len(view)}  /search n=next f=fav F=fav-only e=edit d=del c=clear enter=copy q=quit")

            stdscr.refresh()
            curses.napms(40)

    try:
        curses.wrapper(draw)
    except KeyboardInterrupt:
        pass
    except ImportError as e:
        warnings.warn(f"clippy menu: curses import failed at runtime: {e}", RuntimeWarning)
        return fail(f"curses error: {e} — try `pip install windows-curses` on Windows")
    except Exception as e:
        warnings.warn(f"clippy menu: curses error: {e} ({type(e).__name__})", RuntimeWarning)
        if "curses" in str(type(e)).lower() or "TERM" in str(e) or "setupterm" in str(e):
            plat = platform.system()
            if plat == "Windows":
                return fail(
                    "Terminal UI failed — Windows console without curses support.\n"
                    "  Fix: pip install windows-curses\n"
                    "  Fallback: clippy history / clippy search / clippy gui\n"
                    f"  Details: {e}"
                )
            return fail(f"Terminal not supported: {e} — try `TERM=xterm-256color clippy menu` or use `clippy history`")
        raise


def cmd_gui(args):
    try:
        import tkinter as tk
        import tkinter.font as tkfont
        from tkinter import messagebox
    except ImportError:
        fail("GUI needs tkinter.\n"
             "  macOS: brew install python-tk\n"
             "  Debian/Ubuntu: sudo apt install python3-tk\n"
             "  or run: python -m clippy gui")
        return 1

    W, H = 600, 560
    TRANS = "#000001"
    BG = "#1e1e2e"
    CARD = "#313244"
    SURFACE = "#45475a"
    TEXT = "#cdd6f4"
    MUTED = "#a6adc8"
    ACCENT = "#89b4fa"
    ACCENT_H = "#b4befe"
    DANGER = "#f38ba8"
    DANGER_H = "#eba0ac"
    GOLD = "#f9e2af"
    GREEN = "#a6e3a1"

    root = tk.Tk()
    root.title("clippy")
    root.geometry(f"{W}x{H}")
    root.minsize(520, 480)
    is_mac = sys.platform == "darwin"
    # Frameless + transparency only looks right on macOS — on Windows/Linux it glitches,
    # so use native chrome there (gives free minimize/maximize/resize).
    if is_mac:
        try:
            root.overrideredirect(True)
            root.configure(bg=TRANS)
            root.wm_attributes("-transparent", True)
        except Exception:
            root.overrideredirect(False)
            root.configure(bg=BG)
            is_mac = False
    if not is_mac:
        root.overrideredirect(False)
        root.configure(bg=BG)
        try:
            root.resizable(True, True)
        except Exception:
            pass

    mono = tkfont.nametofont("TkFixedFont")
    mono.configure(size=11)
    ui = tkfont.nametofont("TkDefaultFont")
    ui.configure(size=11)

    # Canvas is transparent on mac, solid on others; always fills window if resizable
    bg_canvas = TRANS if is_mac else BG
    canvas = tk.Canvas(root, width=W, height=H, bg=bg_canvas, highlightthickness=0, bd=0)
    if not is_mac:
        canvas.pack(fill="both", expand=True)
    else:
        canvas.pack()

    def rr(x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
               x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
               x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return canvas.create_polygon(pts, smooth=True, **kw)

    rr(0, 0, W, H, 24, fill=BG, outline="")

    class RButton:
        def __init__(self, x, y, w, h, text, command, fill, hover, fg=TEXT, r=16):
            self.canvas = canvas
            self.command = command
            self.fill, self.hover, self.fg = fill, hover, fg
            self.shape = rr(x, y, x + w, y + h, r, fill=fill, outline=fill)
            self.label = canvas.create_text(x + w / 2, y + h / 2, text=text, fill=fg, font=ui)
            tag = f"btn{id(self)}"
            canvas.addtag_withtag(tag, self.shape)
            canvas.addtag_withtag(tag, self.label)
            canvas.tag_bind(tag, "<Enter>", lambda e: self._paint(self.hover))
            canvas.tag_bind(tag, "<Leave>", lambda e: self._paint(self.fill))
            canvas.tag_bind(tag, "<Button-1>", lambda e: self.command())

        def _paint(self, color):
            canvas.itemconfig(self.shape, fill=color, outline=color)

    rr(20, 48, W - 20, 82, 14, fill=SURFACE, outline="")
    search_var = tk.StringVar()
    search_entry = tk.Entry(canvas, textvariable=search_var, font=mono, bg=SURFACE, fg=TEXT,
                            bd=0, relief="flat", insertbackground=TEXT, highlightthickness=0)
    canvas.create_window(34, 56, anchor="nw", width=W - 90, height=22, window=search_entry)
    canvas.create_text(W - 24, 65, text="search", fill=MUTED, font=ui)

    rr(20, 92, W - 20, 396, 16, fill=CARD, outline="")
    list_frame = tk.Frame(canvas, bg=CARD)
    scrollbar = tk.Scrollbar(list_frame, troughcolor=CARD, bg=CARD, bd=0,
                             relief="flat", activebackground=SURFACE, highlightthickness=0, width=8)
    scrollbar.pack(side="right", fill="y")
    listbox = tk.Listbox(list_frame, selectmode="extended", font=mono, bg=CARD, fg=TEXT,
                         selectbackground=ACCENT, selectforeground=BG, bd=0, relief="flat",
                         highlightthickness=0, yscrollcommand=scrollbar.set)
    scrollbar.config(command=listbox.yview)
    listbox.pack(side="left", fill="both", expand=True)
    canvas.create_window(34, 108, anchor="nw", width=W - 70, height=276, window=list_frame)

    preview_var = tk.StringVar()
    meta_var = tk.StringVar()
    preview_lbl = tk.Label(canvas, textvariable=preview_var, anchor="nw", justify="left",
                           bg=BG, fg=TEXT, font=mono, wraplength=W - 70)
    preview_lbl.place(x=30, y=402, width=W - 70, height=44)
    meta_lbl = tk.Label(canvas, textvariable=meta_var, anchor="nw", justify="left",
                        bg=BG, fg=MUTED, font=ui)
    meta_lbl.place(x=30, y=450, width=W - 70, height=16)

    rr(20, 470, W - 20, 504, 14, fill=SURFACE, outline="")
    range_entry = tk.Entry(canvas, font=mono, bg=SURFACE, fg=TEXT, bd=0, relief="flat",
                           insertbackground=TEXT, highlightthickness=0)
    canvas.create_window(34, 478, anchor="nw", width=W - 90, height=24, window=range_entry)
    canvas.create_text(W - 24, 487, text="range: 3-10, 1,5 or all", fill=MUTED, font=ui)

    items = load()
    visible_indices = []

    def repopulate(select_text=None):
        listbox.delete(0, tk.END)
        for i in visible_indices:
            item = items[i]
            star = "★" if item.get("favorite") else " "
            listbox.insert(tk.END, f"{i + 1:3d} {star} {item['text'].replace(chr(10), ' ')[:52]}")
        canvas.itemconfig(count_text, text=f"{len(visible_indices)}/{len(items)} items")
        if select_text is not None:
            for row, i in enumerate(visible_indices):
                if items[i]["text"] == select_text:
                    listbox.selection_set(row)
                    listbox.see(row)
                    break

    def apply_filter(select_text=None):
        nonlocal visible_indices
        q = search_var.get().lower()
        visible_indices = [i for i, item in enumerate(items) if q in item["text"].lower()]
        repopulate(select_text)

    def refresh(keep_selection=True):
        nonlocal items
        if keep_selection:
            sel = listbox.curselection()
            sel_text = items[visible_indices[sel[0]]]["text"] if sel and 0 <= sel[0] < len(visible_indices) else None
        else:
            sel_text = None
        items = load()
        apply_filter(sel_text)
        if not keep_selection and visible_indices:
            listbox.selection_set(0)

    def show_preview():
        sel = listbox.curselection()
        if sel and 0 <= sel[0] < len(visible_indices):
            it = items[visible_indices[sel[0]]]
            text = it["text"]
            preview_var.set(text if len(text) <= 220 else text[:220] + "…")
            star = "★" if it.get("favorite") else "☆"
            meta_var.set(f"{star}  item {visible_indices[sel[0]] + 1}  ·  {text.count(chr(10)) + 1} lines  ·  "
                         f"{len(text)} chars  ·  copied {it.get('count', 1)}x")
        else:
            preview_var.set("")
            meta_var.set("")

    def copy_selected():
        sel = listbox.curselection()
        if sel and 0 <= sel[0] < len(visible_indices):
            ClipboardManager().set(items[visible_indices[sel[0]]]["text"])

    def delete_selected():
        sel = list(listbox.curselection())
        if sel:
            delete_indices([visible_indices[s] for s in sel])
            refresh()
            show_preview()

    def toggle_fav():
        sel = listbox.curselection()
        if sel and 0 <= sel[0] < len(visible_indices):
            toggle_favorite(visible_indices[sel[0]])
            refresh()
            show_preview()

    def delete_range():
        spec = range_entry.get().strip().lower()
        if not spec:
            return
        if spec == "all":
            clear()
        else:
            indices = parse_range(spec)
            if not indices:
                return
            delete_indices(indices)
        range_entry.delete(0, tk.END)
        refresh()
        show_preview()

    def clear_all():
        if items and messagebox.askyesno("clippy", f"Clear all {len(items)} items?"):
            clear()
            refresh()
            show_preview()

    def auto_refresh():
        nonlocal items
        new = load()
        if new != items:
            sel = listbox.curselection()
            sel_text = items[visible_indices[sel[0]]]["text"] if sel and 0 <= sel[0] < len(visible_indices) else None
            items = new
            apply_filter(sel_text)
            show_preview()
        root.after(1500, auto_refresh)

    ClipboardManager().watch(add)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    listbox.bind("<<ListboxSelect>>", lambda e: show_preview())
    listbox.bind("<Double-Button-1>", lambda e: copy_selected())
    range_entry.bind("<Return>", lambda e: delete_range())
    search_var.trace_add("write", lambda *a: apply_filter())
    listbox.bind("<Return>", lambda e: copy_selected())
    listbox.bind("<space>", lambda e: copy_selected())
    listbox.bind("<Delete>", lambda e: delete_selected())
    listbox.bind("<f>", lambda e: toggle_fav())
    listbox.bind("<BackSpace>", lambda e: search_entry.focus_set())
    listbox.bind("/", lambda e: search_entry.focus_set())

    y = 512
    x0 = 20
    bw = 88
    gap = 6
    RButton(x0, y, bw, 34, "Copy", copy_selected, ACCENT, ACCENT_H, fg=BG)
    RButton(x0 + bw + gap, y, bw, 34, "Delete", delete_selected, DANGER, DANGER_H, fg=BG)
    RButton(x0 + 2 * (bw + gap), y, bw, 34, "★ Fav", toggle_fav, GOLD, ACCENT_H, fg=BG)
    RButton(x0 + 3 * (bw + gap), y, bw, 34, "Clear All", clear_all, SURFACE, ACCENT_H)
    RButton(x0 + 4 * (bw + gap), y, bw, 34, "Refresh", refresh, SURFACE, ACCENT_H)
    canvas.create_text(W - 16, y + 17, anchor="e", text="⏎ copy · ⌫ delete · f fav",
                       fill=MUTED, font=ui)

    # Header — draggable on mac (frameless), static on other platforms
    if is_mac:
        header_drag = canvas.create_rectangle(0, 0, W - 110, 40, fill=TRANS, outline="")
        drag_tag = "drag"
        canvas.addtag_withtag(drag_tag, header_drag)
        def start_drag(e):
            root._drag_off = (e.x_root - root.winfo_x(), e.y_root - root.winfo_y())
        def do_drag(e):
            root.geometry(f"+{e.x_root - root._drag_off[0]}+{e.y_root - root._drag_off[1]}")
        canvas.tag_bind(drag_tag, "<Button-1>", start_drag)
        canvas.tag_bind(drag_tag, "<B1-Motion>", do_drag)

    canvas.create_text(22, 22, anchor="w", text="clippy", fill=ACCENT, font=("TkDefaultFont", 13, "bold"))
    canvas.create_text(82, 22, anchor="w", text="· clipboard manager", fill=MUTED, font=ui)
    count_text = canvas.create_text(W - (156 if is_mac else 96), 22, anchor="e", text="", fill=MUTED, font=ui)

    pill = rr(W - (150 if is_mac else 90), 10, W - (100 if is_mac else 40), 34, 12, fill=SURFACE, outline="")
    canvas.create_text(W - (125 if is_mac else 65), 22, text="v2.3", fill=MUTED, font=ui)

    if is_mac:
        # Custom window chrome for frameless mac window: minimize / maximize / close
        def _make_chrome(x, w, glyph, bg, hover, cmd):
            s = rr(x, 8, x + w, 40, 12, fill=bg, outline="")
            t = canvas.create_text(x + w/2, 24, text=glyph, fill=MUTED, font=ui)
            tag = f"chrome{id(s)}"
            canvas.addtag_withtag(tag, s)
            canvas.addtag_withtag(tag, t)
            def _paint(c):
                canvas.itemconfig(s, fill=c, outline=c)
                canvas.itemconfig(t, fill=BG if c != bg else MUTED)
            canvas.tag_bind(tag, "<Enter>", lambda e: _paint(hover))
            canvas.tag_bind(tag, "<Leave>", lambda e: _paint(bg))
            canvas.tag_bind(tag, "<Button-1>", lambda e: cmd())
            return s, t
        _make_chrome(W - 110, 30, "—", CARD, SURFACE, lambda: root.iconify())
        _is_zoomed = {"v": False, "geom": f"{W}x{H}"}
        def _toggle_zoom():
            if not _is_zoomed["v"]:
                _is_zoomed["geom"] = root.geometry()
                try:
                    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
                    root.geometry(f"{sw}x{sh}+0+0")
                except Exception:
                    pass
                _is_zoomed["v"] = True
            else:
                try:
                    root.geometry(_is_zoomed["geom"])
                except Exception:
                    pass
                _is_zoomed["v"] = False
        _make_chrome(W - 76, 30, "☐", CARD, SURFACE, _toggle_zoom)
        close_shape = rr(W - 42, 8, W - 12, 40, 12, fill=CARD, outline="")
        close_text = canvas.create_text(W - 27, 24, text="✕", fill=MUTED, font=ui)
        close_tag = "close"
        canvas.addtag_withtag(close_tag, close_shape)
        canvas.addtag_withtag(close_tag, close_text)
        def _paint_close(color):
            canvas.itemconfig(close_shape, fill=color, outline=color)
            canvas.itemconfig(close_text, fill=BG if color == DANGER else MUTED)
        canvas.tag_bind(close_tag, "<Enter>", lambda e: _paint_close(DANGER))
        canvas.tag_bind(close_tag, "<Leave>", lambda e: _paint_close(CARD))
        canvas.tag_bind(close_tag, "<Button-1>", lambda e: root.destroy())
        # Resize grip — bottom-right corner for frameless window
        grip = canvas.create_text(W - 14, H - 14, text="◢", fill=MUTED, font=("TkDefaultFont", 10))
        canvas.tag_bind(grip, "<Button-1>", lambda e: setattr(root, "_resize_start", (e.x_root, e.y_root, root.winfo_width(), root.winfo_height())))
        def _do_resize(e):
            try:
                sx, sy, sw, sh = root._resize_start
                nw = max(520, sw + (e.x_root - sx))
                nh = max(480, sh + (e.y_root - sy))
                root.geometry(f"{nw}x{nh}")
            except Exception:
                pass
        canvas.tag_bind(grip, "<B1-Motion>", _do_resize)
        canvas.tag_bind(grip, "<Enter>", lambda e: canvas.itemconfig(grip, fill=ACCENT))
        canvas.tag_bind(grip, "<Leave>", lambda e: canvas.itemconfig(grip, fill=MUTED))
    else:
        # Native chrome — just need a close helper that matches the rounded bg
        close_shape = rr(W - 44, 8, W - 12, 40, 12, fill=CARD, outline="")
        close_text = canvas.create_text(W - 28, 24, text="✕", fill=MUTED, font=ui)
        close_tag = "close"
        canvas.addtag_withtag(close_tag, close_shape)
        canvas.addtag_withtag(close_tag, close_text)
        def _paint_close(color):
            canvas.itemconfig(close_shape, fill=color, outline=color)
            canvas.itemconfig(close_text, fill=BG if color == DANGER else MUTED)
        canvas.tag_bind(close_tag, "<Enter>", lambda e: _paint_close(DANGER))
        canvas.tag_bind(close_tag, "<Leave>", lambda e: _paint_close(CARD))
        canvas.tag_bind(close_tag, "<Button-1>", lambda e: root.destroy())
        # Native resize grip (visible hint, uses window manager)
        try:
            import tkinter.ttk as ttk
            grip = ttk.Sizegrip(root)
            grip.place(relx=1.0, rely=1.0, anchor="se")
        except Exception:
            pass

    refresh(keep_selection=False)
    auto_refresh()
    root.mainloop()


def cmd_doctor(args):
    import warnings as _w
    if getattr(args, "verbose", False):
        _w.simplefilter("always")
        logging.basicConfig(level=logging.DEBUG)
    else:
        _w.simplefilter("always")
    from .doctor import run_all, format_report
    fix = bool(getattr(args, "fix", False))
    as_json = getattr(args, "json", None) is not None
    sections, summary = run_all(fix=fix)
    if as_json:
        out = {"summary": summary, "sections": {name: checks for name, checks in sections}}
        print(json.dumps(out, indent=2))
    else:
        use_color = sys.stdout.isatty() and not getattr(args, "no_color", False)
        print(format_report(sections, summary, use_color=use_color))
        if summary["errors"] and not fix:
            print("\nHint: `clippy doctor --fix` will auto-repair data file, permissions, and truncation.", file=sys.stderr)
        plat = platform.system()
        if plat == "Linux" and summary["errors"]:
            print("Linux clipboard hint: sudo apt install wl-clipboard xclip xsel", file=sys.stderr)
        elif plat == "Darwin" and summary["errors"]:
            print("macOS hint: ensure Xcode CLT installed: xcode-select --install", file=sys.stderr)
        elif plat == "Windows" and summary["errors"]:
            print("Windows hint: reinstall Python with 'tcl/tk and IDLE' checked", file=sys.stderr)
    return 1 if summary["errors"] else 0


def cmd_serve(args):
    from .server import serve
    try:
        serve(host=args.host, port=args.port)
    except OSError as e:
        warnings.warn(f"clippy serve failed to bind {args.host}:{args.port}: {e}", RuntimeWarning)
        if "Address already in use" in str(e) or "already in use" in str(e).lower():
            print(f"clippy: port {args.port} already in use — try `clippy serve --port 0` for a free port, or `lsof -i :{args.port}` to find the owner", file=sys.stderr)
        else:
            print(f"clippy: serve failed: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nclippy: server stopped.", file=sys.stderr)
        return 0
    except Exception as e:
        warnings.warn(f"clippy serve unexpected error: {e}", RuntimeWarning)
        print(f"clippy: serve crashed: {e} ({type(e).__name__})", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="clippy", description="Clipboard History Manager")
    parser.add_argument("command", nargs="?", default="menu",
                        choices=["watch", "history", "search", "top", "stats", "dedupe",
                                 "backup", "export", "import", "favorite", "edit", "truncate",
                                 "delete", "menu", "gui", "serve", "get", "set", "api", "doctor", "repair"],
                        help="Command to run (default: menu)")
    parser.add_argument("spec", nargs="?",
                        help="Primary argument: query, index, range spec, file, or format")
    parser.add_argument("extra", nargs="?",
                        help="Secondary argument (export output file)")
    parser.add_argument("--json", nargs="?", const=True, default=None,
                        help="Output machine-readable JSON (details vary per command)")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress human-friendly status text")
    parser.add_argument("--host", default="127.0.0.1", help="Serve bind host (with serve)")
    parser.add_argument("--port", type=int, default=None, help="Port (serve) or server port (api)")
    parser.add_argument("--method", default="GET", help="HTTP method for the api command (default GET)")
    parser.add_argument("--data", default=None, help="JSON body for the api command (POST/PUT)")
    parser.add_argument("--stdin", action="store_true", help="Read input from stdin (set)")
    parser.add_argument("--file", default=None, help="Read input from a file (set)")
    parser.add_argument("--fix", action="store_true", help="Auto-fix issues (with doctor/repair)")
    parser.add_argument("--verbose", action="store_true", help="Show all warnings and debug logs")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")
    parser.add_argument("--version", action="version", version="clippy 2.3")
    args = parser.parse_args(argv)

    if getattr(args, "verbose", False):
        warnings.simplefilter("always")
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
    else:
        warnings.simplefilter("default")

    def _cmd_repair(a):
        return cmd_doctor(argparse.Namespace(fix=True, json=a.json, verbose=getattr(a, "verbose", False), no_color=getattr(a, "no_color", False)))

    commands = {
        "watch": cmd_watch,
        "history": cmd_history,
        "search": cmd_search,
        "top": cmd_top,
        "stats": cmd_stats,
        "dedupe": cmd_dedupe,
        "backup": cmd_backup,
        "export": cmd_export,
        "import": cmd_import,
        "favorite": cmd_favorite,
        "edit": cmd_edit,
        "truncate": cmd_truncate,
        "delete": cmd_delete,
        "menu": cmd_menu,
        "gui": cmd_gui,
        "serve": cmd_serve,
        "get": cmd_get,
        "set": cmd_set,
        "api": cmd_api,
        "doctor": cmd_doctor,
        "repair": _cmd_repair,
    }
    try:
        return commands[args.command](args) or 0
    except KeyboardInterrupt:
        print("\nclippy: interrupted", file=sys.stderr)
        return 130
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        try:
            sys.stderr.close()
        except Exception:
            pass
        return 0
    except Exception as e:
        warnings.warn(f"clippy: command '{args.command}' crashed: {e} ({type(e).__name__})", RuntimeWarning)
        print(f"clippy: unexpected error in '{args.command}': {e} ({type(e).__name__})", file=sys.stderr)
        print("Run `clippy doctor --fix` to diagnose, or `clippy doctor --verbose` for details.", file=sys.stderr)
        if getattr(args, "verbose", False):
            import traceback
            traceback.print_exc()
        else:
            print("Hint: re-run with --verbose for full traceback.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
