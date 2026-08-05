import argparse
import os
import shlex
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from queue import Queue, Empty

from clipboard import ClipboardManager
from history import (
    add, load, remove, clear, search, delete_indices, update, toggle_favorite,
    dedupe, truncate, backup, export_history, import_file, stats, top, count,
)


def parse_range(spec):
    result = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                a, b = (int(x) for x in part.split("-", 1))
            except ValueError:
                continue
            if a > b:
                a, b = b, a
            result.extend(range(a - 1, b))
        else:
            try:
                result.append(int(part) - 1)
            except ValueError:
                continue
    return sorted(set(result), reverse=True)


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
    if not items:
        print("No clipboard history.")
        return
    for i, item in enumerate(items, 1):
        star = "★" if item.get("favorite") else " "
        preview = item["text"].replace("\n", " ")[:52]
        ts = item.get("time", "")[:16]
        cnt = item.get("count", 1)
        print(f"{i:3d}. {star} [{ts}] ({cnt}x) {preview}")
    print(f"\n{len(items)} item{'s' if len(items) != 1 else ''}")


def cmd_search(args):
    items = load()
    q = (args.spec or "").lower()
    if not q:
        print("Usage: clippy search <query>")
        return
    results = [i for i, item in enumerate(items) if q in item["text"].lower()]
    if not results:
        print(f'No matches for "{args.spec}".')
        return
    for idx in results:
        item = items[idx]
        star = "★" if item.get("favorite") else " "
        print(f"{idx + 1:3d}. {star} {item['text'].replace(chr(10), ' ')[:60]}")
    print(f"\n{len(results)} match{'es' if len(results) != 1 else ''}")


def cmd_top(args):
    try:
        n = int(args.spec or "10")
    except ValueError:
        n = 10
    ranked = top(n)
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


def cmd_dedupe(args):
    before = len(load())
    items = dedupe()
    removed = before - len(items)
    print(f"Removed {removed} duplicate{'s' if removed != 1 else ''}. {len(items)} remain.")


def cmd_backup(args):
    path = backup()
    if not path:
        print("Nothing to back up.")
    else:
        print(f"Backup saved to {path}")


def cmd_export(args):
    fmt = (args.spec or "json").lower()
    if fmt not in ("json", "txt", "md", "markdown"):
        print("Format must be json, txt, or md.")
        return
    ext, content = export_history(fmt)
    outfile = args.extra or f"clippy_export.{ext}"
    with open(outfile, "w") as f:
        f.write(content)
    print(f"Exported {count()} items to {outfile}")


def cmd_import(args):
    path = args.spec
    if not path:
        print("Usage: clippy import <file.json>")
        return
    if not os.path.exists(path):
        print(f"No such file: {path}")
        return
    try:
        added = import_file(path)
    except Exception as e:
        print(f"Import failed: {e}")
        return
    print(f"Imported {added} new item{'s' if added != 1 else ''}.")


def cmd_favorite(args):
    items = load()
    try:
        idx = int(args.spec or "") - 1
    except ValueError:
        print("Usage: clippy favorite <index>")
        return
    if not (0 <= idx < len(items)):
        print("Index out of range.")
        return
    toggle_favorite(idx)
    items = load()
    state = "favorited ★" if items[idx].get("favorite") else "unfavorited"
    print(f"Item {idx + 1} {state}.")


def cmd_edit(args):
    items = load()
    try:
        idx = int(args.spec or "") - 1
    except ValueError:
        print("Usage: clippy edit <index>")
        return
    if not (0 <= idx < len(items)):
        print("Index out of range.")
        return
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
        print("Usage: clippy truncate <n>")
        return
    items = truncate(n)
    print(f"Truncated to {len(items)} item{'s' if len(items) != 1 else ''}.")


def cmd_delete(args):
    items = load()
    if not items:
        print("No clipboard history.")
        return
    spec = args.spec or ""
    if spec.strip().lower() == "all":
        clear()
        print(f"Cleared all {len(items)} item{'s' if len(items) != 1 else ''}.")
        return
    indices = [i for i in parse_range(spec) if 0 <= i < len(items)]
    if not indices:
        print("Invalid range. Use e.g. 3, 3-10, 1,3,7 or all.")
        return
    delete_indices(indices)
    print(f"Deleted {len(indices)} item{'s' if len(indices) != 1 else ''}.")


def cmd_menu(args):
    import curses

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
                            status_msg = f"found {len(matches)} match{'es' if len(matches) != 1 else ''}"
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
            header_right = f" ● {len(view)} item{'s' if len(view) != 1 else ''} "
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

    curses.wrapper(draw)


def cmd_gui(args):
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import messagebox

    W, H = 560, 500
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

    root = tk.Tk()
    root.title("clippy")
    root.geometry(f"{W}x{H}")
    root.overrideredirect(True)
    root.configure(bg=TRANS)
    try:
        if sys.platform == "win32":
            root.wm_attributes("-transparentcolor", TRANS)
        else:
            root.wm_attributes("-transparent", True)
    except Exception:
        pass

    mono = tkfont.nametofont("TkFixedFont")
    mono.configure(size=11)
    ui = tkfont.nametofont("TkDefaultFont")
    ui.configure(size=11)

    canvas = tk.Canvas(root, width=W, height=H, bg=TRANS, highlightthickness=0, bd=0)
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

    rr(20, 92, W - 20, 392, 16, fill=CARD, outline="")
    list_frame = tk.Frame(canvas, bg=CARD)
    scrollbar = tk.Scrollbar(list_frame, troughcolor=CARD, bg=CARD, bd=0,
                             relief="flat", activebackground=SURFACE, highlightthickness=0, width=8)
    scrollbar.pack(side="right", fill="y")
    listbox = tk.Listbox(list_frame, selectmode="extended", font=mono, bg=CARD, fg=TEXT,
                         selectbackground=ACCENT, selectforeground=BG, bd=0, relief="flat",
                         highlightthickness=0, yscrollcommand=scrollbar.set)
    scrollbar.config(command=listbox.yview)
    listbox.pack(side="left", fill="both", expand=True)
    canvas.create_window(34, 108, anchor="nw", width=W - 70, height=272, window=list_frame)

    preview_var = tk.StringVar()
    tk.Label(canvas, textvariable=preview_var, anchor="w", justify="left", bg=BG, fg=MUTED,
             font=mono, wraplength=W - 60).place(x=26, y=400)

    rr(20, 418, W - 20, 452, 14, fill=SURFACE, outline="")
    range_entry = tk.Entry(canvas, font=mono, bg=SURFACE, fg=TEXT, bd=0, relief="flat",
                           insertbackground=TEXT, highlightthickness=0)
    canvas.create_window(34, 426, anchor="nw", width=W - 90, height=24, window=range_entry)
    canvas.create_text(W - 24, 435, text="range: 3-10, 1,5 or all", fill=MUTED, font=ui)

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
            preview_var.set(items[visible_indices[sel[0]]]["text"])
        else:
            preview_var.set("")

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
        if len(new) != len(items):
            sel = listbox.curselection()
            sel_text = items[visible_indices[sel[0]]]["text"] if sel and 0 <= sel[0] < len(visible_indices) else None
            items = new
            apply_filter(sel_text)
            show_preview()
        root.after(1500, auto_refresh)

    listbox.bind("<<ListboxSelect>>", lambda e: show_preview())
    listbox.bind("<Double-Button-1>", lambda e: copy_selected())
    range_entry.bind("<Return>", lambda e: delete_range())
    search_var.trace_add("write", lambda *a: apply_filter())

    y = 460
    x0 = 20
    RButton(x0, y, 84, 30, "Copy", copy_selected, ACCENT, ACCENT_H, fg=BG)
    RButton(x0 + 94, y, 84, 30, "Delete", delete_selected, DANGER, DANGER_H, fg=BG)
    RButton(x0 + 188, y, 84, 30, "★ Fav", toggle_fav, GOLD, ACCENT_H, fg=BG)
    RButton(x0 + 282, y, 84, 30, "Clear All", clear_all, SURFACE, ACCENT_H)
    RButton(x0 + 376, y, 84, 30, "Refresh", refresh, SURFACE, ACCENT_H)
    canvas.create_text(W - 16, y + 15, anchor="e", text="shift+click = range",
                       fill=MUTED, font=ui)

    header_drag = canvas.create_rectangle(0, 0, W - 48, 40, fill=TRANS, outline="")
    drag_tag = "drag"
    canvas.addtag_withtag(drag_tag, header_drag)
    canvas.tag_bind(drag_tag, "<Button-1>", lambda e: root._start_drag(e))
    canvas.tag_bind(drag_tag, "<B1-Motion>", lambda e: root._do_drag(e))
    root._start_drag = lambda e: setattr(root, "_drag_off", (e.x_root - root.winfo_x(), e.y_root - root.winfo_y()))
    root._do_drag = lambda e: root.geometry(f"+{e.x_root - root._drag_off[0]}+{e.y_root - root._drag_off[1]}")

    canvas.create_text(22, 22, anchor="w", text="clippy", fill=ACCENT, font=("TkDefaultFont", 13, "bold"))
    count_text = canvas.create_text(W - 100, 22, anchor="e", text="", fill=MUTED, font=ui)

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

    refresh(keep_selection=False)
    auto_refresh()
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(prog="clippy", description="Clipboard History Manager")
    parser.add_argument("command", nargs="?", default="menu",
                        choices=["watch", "history", "search", "top", "stats", "dedupe",
                                 "backup", "export", "import", "favorite", "edit", "truncate",
                                 "delete", "menu", "gui"],
                        help="Command to run (default: menu)")
    parser.add_argument("spec", nargs="?",
                        help="Primary argument: query, index, range spec, file, or format")
    parser.add_argument("extra", nargs="?",
                        help="Secondary argument (export output file)")
    parser.add_argument("--version", action="version", version="clippy 2.0")
    args = parser.parse_args()

    {
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
    }[args.command](args)


if __name__ == "__main__":
    main()
