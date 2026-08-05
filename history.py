import json
import os
import shutil
from datetime import datetime

_FILE_CWD = "data.json"
_FILE_HOME = os.path.expanduser("~/.clippy_history.json")
FILE = _FILE_CWD if os.path.exists(_FILE_CWD) else _FILE_HOME
MAX_ITEMS = 500


def _now():
    return datetime.now().isoformat(timespec="seconds")


def load():
    if not os.path.exists(FILE):
        return []
    with open(FILE) as f:
        data = json.load(f)
    if not data:
        return data
    migrated = isinstance(data[0], str) or "count" not in data[0] or "favorite" not in data[0]
    items = []
    for entry in data:
        if isinstance(entry, str):
            entry = {"text": entry}
        entry.setdefault("count", 1)
        entry.setdefault("favorite", False)
        items.append(entry)
    if migrated:
        save(items)
    return items


def save(items):
    with open(FILE, "w") as f:
        json.dump(items, f, indent=2)


def add(text):
    if not text:
        return load()
    items = load()
    now = _now()
    for i, item in enumerate(items):
        if item["text"] == text:
            item["count"] = item.get("count", 1) + 1
            item["time"] = now
            items.pop(i)
            items.insert(0, item)
            save(items)
            return items
    items.insert(0, {"text": text, "time": now, "count": 1, "favorite": False})
    items = items[:MAX_ITEMS]
    save(items)
    return items


def remove(index):
    items = load()
    if 0 <= index < len(items):
        del items[index]
        save(items)
    return items


def delete_indices(indices):
    items = load()
    for index in sorted(set(indices), reverse=True):
        if 0 <= index < len(items):
            del items[index]
    save(items)
    return items


def update(index, text):
    items = load()
    if 0 <= index < len(items) and text:
        items[index]["text"] = text
        items[index]["time"] = _now()
        save(items)
    return items


def toggle_favorite(index):
    items = load()
    if 0 <= index < len(items):
        items[index]["favorite"] = not items[index].get("favorite", False)
        save(items)
    return items


def get_favorites():
    return [i for i, item in enumerate(load()) if item.get("favorite")]


def clear():
    save([])


def search(query):
    items = load()
    q = query.lower()
    return [(i, item) for i, item in enumerate(items) if q in item["text"].lower()]


def get(index):
    items = load()
    if 0 <= index < len(items):
        return items[index]
    return None


def count():
    return len(load())


def dedupe():
    items = load()
    seen = set()
    out = []
    for item in items:
        if item["text"] not in seen:
            seen.add(item["text"])
            out.append(item)
    save(out)
    return out


def truncate(n):
    items = load()[:max(0, n)]
    save(items)
    return items


def backup():
    if not os.path.exists(FILE):
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = f"clippy_backup_{stamp}.json"
    shutil.copy(FILE, path)
    return path


def export_json(items):
    return json.dumps(items, indent=2)


def export_text(items):
    lines = [f"{i + 1}. {item['text']}" for i, item in enumerate(items)]
    return "\n".join(lines) + "\n"


def export_markdown(items):
    lines = ["# clippy history", ""]
    for i, item in enumerate(items, 1):
        star = "★" if item.get("favorite") else " "
        text = item["text"].replace("\n", "\n> ")
        lines.append(f"{i}. {star} `{text}`")
    return "\n".join(lines) + "\n"


def export_history(fmt="json"):
    items = load()
    if fmt == "json":
        return "json", export_json(items)
    if fmt in ("md", "markdown"):
        return "md", export_markdown(items)
    return "txt", export_text(items)


def import_file(path):
    if not os.path.exists(path):
        return 0
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, list):
        return 0
    items = load()
    known = {i["text"] for i in items}
    added = 0
    for entry in data:
        text = entry["text"] if isinstance(entry, dict) else entry
        if text and text not in known:
            items.append({"text": text, "time": "", "count": 1, "favorite": False})
            known.add(text)
            added += 1
    save(items)
    return added


def stats():
    items = load()
    total = len(items)
    if total == 0:
        return {"total": 0}
    total_chars = sum(len(i["text"]) for i in items)
    total_lines = sum(i["text"].count("\n") + 1 for i in items)
    total_copies = sum(i.get("count", 1) for i in items)
    longest = max(items, key=lambda i: len(i["text"]))
    most_copied = max(items, key=lambda i: i.get("count", 1))
    favorites = sum(1 for i in items if i.get("favorite"))
    times = [i.get("time", "") for i in items if i.get("time")]
    return {
        "total": total,
        "total_chars": total_chars,
        "total_lines": total_lines,
        "total_copies": total_copies,
        "avg_len": round(total_chars / total, 1),
        "longest": len(longest["text"]),
        "most_copied": most_copied.get("count", 1),
        "most_copied_preview": most_copied["text"].replace("\n", " ")[:40],
        "favorites": favorites,
        "first_time": times[-1] if times else "",
        "last_time": times[0] if times else "",
    }


def top(n=10):
    return sorted(load(), key=lambda i: i.get("count", 1), reverse=True)[:n]
