import json
import logging
import os
import platform
import shutil
import sys
import tempfile
import warnings
from datetime import datetime

MAX_ITEMS = 500
MAX_TEXT_LEN = 100_000
WARN_LARGE_FILE = 5 * 1024 * 1024

logger = logging.getLogger(__name__)


def get_data_file():
    env = os.environ.get("CLIPPY_DATA")
    if env:
        return os.path.expanduser(env)
    home = os.path.expanduser("~")
    sysname = platform.system()
    if sysname == "Windows":
        base = os.environ.get("APPDATA") or home
        cands = [os.path.join(base, "clippy", "history.json"), os.path.join(home, ".clippy_history.json")]
    elif sysname == "Darwin":
        cands = [os.path.join(home, "Library", "Application Support", "clippy", "history.json"), os.path.join(home, ".clippy_history.json")]
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
        cands = [os.path.join(xdg, "clippy", "history.json"), os.path.join(home, ".clippy_history.json")]
    for p in cands:
        if os.path.exists(p):
            return p
    return cands[0] if cands else os.path.join(home, ".clippy_history.json")


def _data_file():
    return get_data_file()


FILE = _data_file()


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _ensure_parent(path):
    parent = os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.exists(parent):
        try:
            os.makedirs(parent, exist_ok=True)
            warnings.warn(f"clippy: created missing directory {parent}", UserWarning)
        except OSError as e:
            warnings.warn(f"clippy: cannot create directory {parent}: {e}", RuntimeWarning)
            logger.error(f"ensure_parent failed {parent}: {e}")
            raise
    if not os.access(parent, os.W_OK):
        warnings.warn(f"clippy: directory not writable: {parent} — try chmod u+w {parent}", RuntimeWarning)
    return parent


def plural(count, word):
    if count == 1:
        return word
    if word.endswith("ch"):
        return word + "es"
    return word + "s"


def parse_range(spec):
    if not isinstance(spec, str):
        warnings.warn(f"clippy: parse_range expected str, got {type(spec).__name__}", UserWarning)
        return []
    if not spec.strip():
        warnings.warn("clippy: empty range spec", UserWarning)
        return []
    result = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                a, b = (int(x) for x in part.split("-", 1))
            except ValueError:
                warnings.warn(f"clippy: invalid range part '{part}' — expected like '3-10'", UserWarning)
                continue
            if a == 0 or b == 0:
                warnings.warn(f"clippy: range indices are 1-based, got '{part}' — did you mean 1-based?", UserWarning)
            if a > b:
                a, b = b, a
                warnings.warn(f"clippy: swapped reversed range '{part}' to {a}-{b}", UserWarning)
            if b - a > 1000:
                warnings.warn(f"clippy: very large range {a}-{b} ({b - a + 1} items)", UserWarning)
            result.extend(range(a - 1, b))
        else:
            try:
                v = int(part)
                if v <= 0:
                    warnings.warn(f"clippy: index {v} invalid — indices are 1-based", UserWarning)
                    continue
                result.append(v - 1)
            except ValueError:
                warnings.warn(f"clippy: invalid index '{part}' — expected integer", UserWarning)
                continue
    uniq = sorted(set(result), reverse=True)
    if len(uniq) != len(result):
        warnings.warn(f"clippy: range had {len(result) - len(uniq)} duplicate indices — deduped", UserWarning)
    return uniq


def fail(msg):
    print(msg, file=sys.stderr)
    logger.debug(msg)
    return 1


def _sanitize_entry(entry, idx=None):
    prefix = f" entry {idx}" if idx is not None else ""
    if isinstance(entry, str):
        warnings.warn(f"clippy: migrating legacy string{prefix} to dict", UserWarning)
        return {"text": entry, "time": "", "count": 1, "favorite": False}
    if not isinstance(entry, dict):
        warnings.warn(f"clippy: skipping malformed{prefix}: expected dict/str, got {type(entry).__name__}", RuntimeWarning)
        return None
    text = entry.get("text")
    if not isinstance(text, str):
        if text is None:
            warnings.warn(f"clippy: entry{prefix} missing 'text' — skipping", RuntimeWarning)
            return None
        warnings.warn(f"clippy: entry{prefix} 'text' is {type(text).__name__}, coercing to str", UserWarning)
        text = str(text)
    if len(text) > MAX_TEXT_LEN:
        warnings.warn(f"clippy: entry{prefix} text very long ({len(text)} chars) — truncating to {MAX_TEXT_LEN}", UserWarning)
        text = text[:MAX_TEXT_LEN]
    try:
        count = int(entry.get("count", 1))
    except Exception:
        warnings.warn(f"clippy: entry{prefix} bad 'count' {entry.get('count')!r} — resetting to 1", UserWarning)
        count = 1
    count = max(1, count)
    fav = bool(entry.get("favorite", False))
    t = entry.get("time", "")
    if t and not isinstance(t, str):
        t = str(t)
    return {"text": text, "time": t or "", "count": count, "favorite": fav}


def load():
    fp = FILE
    if not os.path.exists(fp) and not os.environ.get("CLIPPY_DATA"):
        legacy = os.path.join(os.getcwd(), "data.json")
        if os.path.exists(legacy):
            try:
                _ensure_parent(fp)
                shutil.copy(legacy, fp)
                warnings.warn(f"clippy: migrated legacy {legacy} → {fp}", UserWarning)
            except Exception as e:
                warnings.warn(f"clippy: failed to migrate {legacy}: {e}", RuntimeWarning)
    if not os.path.exists(fp):
        return []
    try:
        st = os.stat(fp)
        if st.st_size > WARN_LARGE_FILE:
            warnings.warn(f"clippy: history file large ({st.st_size} bytes) — consider `clippy truncate` or `clippy dedupe`", UserWarning)
        if st.st_size == 0:
            warnings.warn(f"clippy: history file {fp} is empty", UserWarning)
            return []
    except OSError as e:
        warnings.warn(f"clippy: cannot stat {fp}: {e}", RuntimeWarning)
    try:
        with open(fp, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        warnings.warn(f"clippy: {fp} is corrupt JSON at line {e.lineno} col {e.colno}: {e.msg}", RuntimeWarning)
        corrupt = fp + ".corrupt"
        try:
            os.replace(fp, corrupt)
            print(f"clippy: {fp} unreadable (JSON error at line {e.lineno}), moved to {corrupt}", file=sys.stderr)
            warnings.warn(f"clippy: moved corrupt file to {corrupt} — will start fresh. Backup at {corrupt}", UserWarning)
        except OSError as ex:
            warnings.warn(f"clippy: failed to move corrupt file: {ex}", RuntimeWarning)
            print(f"clippy: failed to move corrupt file: {ex}", file=sys.stderr)
        return []
    except OSError as e:
        warnings.warn(f"clippy: cannot read {fp}: {e} — check permissions (chmod 600 {fp})", RuntimeWarning)
        print(f"clippy: cannot read {fp}: {e}", file=sys.stderr)
        return []
    except ValueError as e:
        warnings.warn(f"clippy: {fp} unreadable: {e}", RuntimeWarning)
        corrupt = fp + ".corrupt"
        try:
            os.replace(fp, corrupt)
        except OSError:
            pass
        print(f"clippy: {fp} unreadable, moved to {corrupt}", file=sys.stderr)
        return []
    if not isinstance(data, list):
        warnings.warn(f"clippy: {fp} contains {type(data).__name__}, expected list — resetting", RuntimeWarning)
        print(f"clippy: {fp} malformed (expected list), resetting", file=sys.stderr)
        return []
    if not data:
        return []
    items = []
    bad = 0
    for idx, entry in enumerate(data):
        sane = _sanitize_entry(entry, idx)
        if sane is None:
            bad += 1
            continue
        items.append(sane)
    if bad:
        warnings.warn(f"clippy: skipped {bad} malformed entries in {fp}", RuntimeWarning)
    migrated = any(isinstance(e, str) or "count" not in e or "favorite" not in e for e in data if isinstance(e, (dict, str)))
    needs_repair = bad > 0 or migrated or len(items) != len(data)
    if needs_repair:
        try:
            save(items)
            warnings.warn(f"clippy: auto-repaired history ({len(data)} → {len(items)} items)", UserWarning)
        except Exception as e:
            warnings.warn(f"clippy: auto-repair save failed: {e}", RuntimeWarning)
    if len(items) > MAX_ITEMS:
        warnings.warn(f"clippy: history has {len(items)} items, exceeds MAX_ITEMS={MAX_ITEMS} — truncating", UserWarning)
        items = items[:MAX_ITEMS]
        try:
            save(items)
        except Exception:
            pass
    return items


def save(items):
    fp = FILE
    try:
        _ensure_parent(fp)
    except Exception as e:
        warnings.warn(f"clippy: cannot ensure parent for {fp}: {e}", RuntimeWarning)
        raise
    if not isinstance(items, list):
        warnings.warn(f"clippy: save expected list, got {type(items).__name__}", RuntimeWarning)
        raise TypeError("save expects list")
    for i, it in enumerate(items):
        if not isinstance(it, dict) or "text" not in it:
            warnings.warn(f"clippy: save item {i} malformed: {it!r}", RuntimeWarning)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(fp)) or ".", prefix=".clippy-")
    except OSError as e:
        warnings.warn(f"clippy: cannot create temp file near {fp}: {e} — is disk full? permissions?", RuntimeWarning)
        logger.error(f"mkstemp failed: {e}")
        raise
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        try:
            os.replace(tmp, fp)
        except OSError as e:
            warnings.warn(f"clippy: cannot replace {fp}: {e} — check permissions/disk space", RuntimeWarning)
            try:
                os.chmod(os.path.dirname(os.path.abspath(fp)) or ".", 0o700)
                os.replace(tmp, fp)
                warnings.warn(f"clippy: fixed directory permissions and saved {fp}", UserWarning)
            except Exception as ex:
                warnings.warn(f"clippy: save failed even after chmod: {ex}", RuntimeWarning)
                raise
        tmp = None
    except Exception as e:
        warnings.warn(f"clippy: save failed: {e}", RuntimeWarning)
        logger.error(f"save failed: {e}")
        raise
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def repair():
    fp = FILE
    if not os.path.exists(fp):
        warnings.warn(f"clippy: nothing to repair — {fp} does not exist", UserWarning)
        return []
    try:
        with open(fp, encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        warnings.warn(f"clippy: repair found corrupt JSON at line {e.lineno}: {e.msg} — resetting", RuntimeWarning)
        bak = fp + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        try:
            shutil.copy(fp, bak)
            warnings.warn(f"clippy: backed up corrupt file to {bak}", UserWarning)
        except Exception:
            pass
        save([])
        return []
    except OSError as e:
        warnings.warn(f"clippy: repair cannot read {fp}: {e}", RuntimeWarning)
        return []
    if not isinstance(raw, list):
        warnings.warn(f"clippy: repair: expected list, got {type(raw).__name__} — resetting", RuntimeWarning)
        save([])
        return []
    items = []
    for idx, e in enumerate(raw):
        sane = _sanitize_entry(e, idx)
        if sane is not None:
            items.append(sane)
    seen = set()
    deduped = []
    dups = 0
    for it in items:
        if it["text"] not in seen:
            seen.add(it["text"])
            deduped.append(it)
        else:
            dups += 1
    if dups:
        warnings.warn(f"clippy: repair removed {dups} duplicates", UserWarning)
    if len(deduped) > MAX_ITEMS:
        warnings.warn(f"clippy: repair truncating {len(deduped)} → {MAX_ITEMS}", UserWarning)
        deduped = deduped[:MAX_ITEMS]
    save(deduped)
    return deduped


def add(text):
    if not isinstance(text, str):
        warnings.warn(f"clippy: add expected str, got {type(text).__name__} — coercing", UserWarning)
        text = str(text)
    if not text:
        warnings.warn("clippy: ignoring empty clipboard text", UserWarning)
        return
    if len(text) > MAX_TEXT_LEN:
        warnings.warn(f"clippy: text very long ({len(text)} chars) — truncating to {MAX_TEXT_LEN}", UserWarning)
        text = text[:MAX_TEXT_LEN]
    try:
        items = load()
    except Exception as e:
        warnings.warn(f"clippy: load failed in add(): {e} — starting fresh", RuntimeWarning)
        items = []
    now = _now()
    for i, item in enumerate(items):
        try:
            if item.get("text") == text:
                item["count"] = item.get("count", 1) + 1
                item["time"] = now
                items.pop(i)
                items.insert(0, item)
                try:
                    save(items)
                except Exception as e:
                    warnings.warn(f"clippy: save failed after bump: {e}", RuntimeWarning)
                    raise
                return
        except Exception as e:
            warnings.warn(f"clippy: error comparing item {i}: {e}", RuntimeWarning)
            continue
    items.insert(0, {"text": text, "time": now, "count": 1, "favorite": False})
    if len(items) > MAX_ITEMS:
        warnings.warn(f"clippy: history capped at {MAX_ITEMS} — dropping oldest", UserWarning)
    try:
        save(items[:MAX_ITEMS])
    except Exception as e:
        warnings.warn(f"clippy: save failed in add(): {e}", RuntimeWarning)
        raise


def remove(index):
    try:
        items = load()
    except Exception as e:
        warnings.warn(f"clippy: load failed in remove(): {e}", RuntimeWarning)
        return
    if not isinstance(index, int):
        warnings.warn(f"clippy: remove expected int, got {type(index).__name__}", UserWarning)
        return
    if 0 <= index < len(items):
        del items[index]
        try:
            save(items)
        except Exception as e:
            warnings.warn(f"clippy: save failed in remove(): {e}", RuntimeWarning)
    else:
        warnings.warn(f"clippy: remove index {index} out of range (0..{len(items)-1})", UserWarning)


def delete_indices(indices):
    if not indices:
        warnings.warn("clippy: delete_indices called with empty list", UserWarning)
        return
    try:
        items = load()
    except Exception as e:
        warnings.warn(f"clippy: load failed in delete_indices(): {e}", RuntimeWarning)
        return
    orig = len(items)
    valid = []
    for idx in sorted(set(indices), reverse=True):
        if not isinstance(idx, int):
            warnings.warn(f"clippy: skipping non-int index {idx!r}", UserWarning)
            continue
        if 0 <= idx < len(items):
            valid.append(idx)
            del items[idx]
        else:
            warnings.warn(f"clippy: index {idx} out of range (0..{orig-1}) — skipping", UserWarning)
    if not valid:
        warnings.warn("clippy: no valid indices to delete", UserWarning)
        return
    try:
        save(items)
    except Exception as e:
        warnings.warn(f"clippy: save failed in delete_indices(): {e}", RuntimeWarning)


def update(index, text):
    if not isinstance(text, str):
        warnings.warn(f"clippy: update text should be str, got {type(text).__name__}", UserWarning)
        text = str(text)
    if not text:
        warnings.warn("clippy: update with empty text — ignoring", UserWarning)
        return
    try:
        items = load()
    except Exception as e:
        warnings.warn(f"clippy: load failed in update(): {e}", RuntimeWarning)
        return
    if not isinstance(index, int) or not (0 <= index < len(items)):
        warnings.warn(f"clippy: update index {index} out of range (0..{len(items)-1})", UserWarning)
        return
    items[index]["text"] = text
    items[index]["time"] = _now()
    try:
        save(items)
    except Exception as e:
        warnings.warn(f"clippy: save failed in update(): {e}", RuntimeWarning)


def toggle_favorite(index):
    try:
        items = load()
    except Exception as e:
        warnings.warn(f"clippy: load failed in toggle_favorite(): {e}", RuntimeWarning)
        return
    if not isinstance(index, int) or not (0 <= index < len(items)):
        warnings.warn(f"clippy: toggle_favorite index {index} out of range", UserWarning)
        return
    items[index]["favorite"] = not items[index].get("favorite", False)
    try:
        save(items)
    except Exception as e:
        warnings.warn(f"clippy: save failed in toggle_favorite(): {e}", RuntimeWarning)


def get_favorites():
    try:
        items = load()
    except Exception as e:
        warnings.warn(f"clippy: load failed in get_favorites(): {e}", RuntimeWarning)
        return []
    return [i for i, item in enumerate(items) if item.get("favorite")]


def clear():
    try:
        save([])
    except Exception as e:
        warnings.warn(f"clippy: clear failed: {e}", RuntimeWarning)
        raise


def search(query):
    if not isinstance(query, str):
        warnings.warn(f"clippy: search query should be str, got {type(query).__name__}", UserWarning)
        query = str(query)
    try:
        items = load()
    except Exception as e:
        warnings.warn(f"clippy: load failed in search(): {e}", RuntimeWarning)
        return []
    q = query.lower()
    if not q:
        warnings.warn("clippy: empty search query — returning all", UserWarning)
    try:
        return [(i, item) for i, item in enumerate(items) if q in item.get("text", "").lower()]
    except Exception as e:
        warnings.warn(f"clippy: search failed: {e}", RuntimeWarning)
        return []


def get(index):
    try:
        items = load()
    except Exception as e:
        warnings.warn(f"clippy: load failed in get(): {e}", RuntimeWarning)
        return None
    if not isinstance(index, int):
        warnings.warn(f"clippy: get expected int, got {type(index).__name__}", UserWarning)
        return None
    if 0 <= index < len(items):
        return items[index]
    warnings.warn(f"clippy: get index {index} out of range (0..{len(items)-1})", UserWarning)
    return None


def count():
    try:
        return len(load())
    except Exception as e:
        warnings.warn(f"clippy: count failed: {e}", RuntimeWarning)
        return 0


def dedupe():
    try:
        items = load()
    except Exception as e:
        warnings.warn(f"clippy: load failed in dedupe(): {e}", RuntimeWarning)
        return []
    seen = set()
    out = []
    for item in items:
        t = item.get("text")
        if t not in seen:
            seen.add(t)
            out.append(item)
    removed = len(items) - len(out)
    if removed:
        warnings.warn(f"clippy: dedupe removed {removed} duplicates", UserWarning)
    else:
        warnings.warn("clippy: dedupe found no duplicates", UserWarning)
    try:
        save(out)
    except Exception as e:
        warnings.warn(f"clippy: save failed in dedupe(): {e}", RuntimeWarning)
    return out


def truncate(n):
    if not isinstance(n, int):
        warnings.warn(f"clippy: truncate expected int, got {type(n).__name__}", UserWarning)
        try:
            n = int(n)
        except Exception:
            warnings.warn("clippy: truncate invalid n — ignoring", UserWarning)
            return load()
    n = max(0, n)
    if n == 0:
        warnings.warn("clippy: truncate 0 will clear all history!", UserWarning)
    try:
        items = load()[:n]
    except Exception as e:
        warnings.warn(f"clippy: load failed in truncate(): {e}", RuntimeWarning)
        return []
    try:
        save(items)
    except Exception as e:
        warnings.warn(f"clippy: save failed in truncate(): {e}", RuntimeWarning)
    return items


def backup():
    fp = FILE
    if not os.path.exists(fp):
        warnings.warn(f"clippy: nothing to backup — {fp} does not exist", UserWarning)
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = f"clippy_backup_{stamp}.json"
    try:
        shutil.copy(fp, path)
        warnings.warn(f"clippy: backup created at {path}", UserWarning) if False else None
    except OSError as e:
        warnings.warn(f"clippy: backup failed: {e} — check permissions/disk space", RuntimeWarning)
        return None
    except Exception as e:
        warnings.warn(f"clippy: backup failed: {e}", RuntimeWarning)
        return None
    return path


def export_json(items):
    try:
        return json.dumps(items, indent=2, ensure_ascii=False)
    except Exception as e:
        warnings.warn(f"clippy: export_json failed: {e}", RuntimeWarning)
        raise


def export_text(items):
    try:
        lines = [f"{i + 1}. {item.get('text','')}" for i, item in enumerate(items)]
        return "\n".join(lines) + "\n"
    except Exception as e:
        warnings.warn(f"clippy: export_text failed: {e}", RuntimeWarning)
        raise


def export_markdown(items):
    try:
        lines = ["# clippy history", ""]
        for i, item in enumerate(items, 1):
            star = "★" if item.get("favorite") else " "
            text = item.get("text","").replace("\n", "\n> ")
            lines.append(f"{i}. {star} `{text}`")
        return "\n".join(lines) + "\n"
    except Exception as e:
        warnings.warn(f"clippy: export_markdown failed: {e}", RuntimeWarning)
        raise


def export_history(fmt="json"):
    if fmt not in ("json", "txt", "md", "markdown"):
        warnings.warn(f"clippy: unknown export format '{fmt}' — defaulting to json", UserWarning)
        fmt = "json"
    try:
        items = load()
    except Exception as e:
        warnings.warn(f"clippy: load failed in export_history(): {e}", RuntimeWarning)
        items = []
    if fmt == "json":
        return "json", export_json(items)
    if fmt in ("md", "markdown"):
        return "md", export_markdown(items)
    return "txt", export_text(items)


def import_file(path):
    if not path:
        warnings.warn("clippy: import_file empty path", UserWarning)
        return 0
    if not os.path.exists(path):
        warnings.warn(f"clippy: import file not found: {path}", UserWarning)
        return 0
    if os.path.getsize(path) > WARN_LARGE_FILE:
        warnings.warn(f"clippy: import file large ({os.path.getsize(path)} bytes) — may be slow", UserWarning)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        warnings.warn(f"clippy: import file {path} corrupt JSON at line {e.lineno}: {e.msg}", RuntimeWarning)
        return 0
    except OSError as e:
        warnings.warn(f"clippy: cannot read import file {path}: {e}", RuntimeWarning)
        return 0
    if not isinstance(data, list):
        warnings.warn(f"clippy: import file {path} expected list, got {type(data).__name__}", UserWarning)
        return 0
    try:
        items = load()
    except Exception as e:
        warnings.warn(f"clippy: load failed in import_file(): {e}", RuntimeWarning)
        items = []
    known = set()
    for it in items:
        t = it.get("text")
        if isinstance(t, str):
            known.add(t)
    added = 0
    for entry in data:
        try:
            text = entry["text"] if isinstance(entry, dict) else entry
            if not isinstance(text, str):
                text = str(text) if text is not None else ""
            if text and text not in known:
                items.append({"text": text, "time": "", "count": 1, "favorite": False})
                known.add(text)
                added += 1
        except Exception as e:
            warnings.warn(f"clippy: skipping bad import entry {entry!r}: {e}", UserWarning)
            continue
    if added == 0:
        warnings.warn(f"clippy: import {path} added nothing (all duplicates or empty)", UserWarning)
    try:
        save(items)
    except Exception as e:
        warnings.warn(f"clippy: save failed in import_file(): {e}", RuntimeWarning)
    return added


def stats():
    try:
        items = load()
    except Exception as e:
        warnings.warn(f"clippy: load failed in stats(): {e}", RuntimeWarning)
        return {"total": 0, "error": str(e)}
    total = len(items)
    if total == 0:
        return {"total": 0}
    try:
        total_chars = sum(len(i.get("text","")) for i in items)
        total_lines = sum(i.get("text","").count("\n") + 1 for i in items)
        total_copies = sum(int(i.get("count", 1)) for i in items)
        longest = max(items, key=lambda i: len(i.get("text","")))
        most_copied = max(items, key=lambda i: int(i.get("count", 1)))
        favorites = sum(1 for i in items if i.get("favorite"))
        times = [i.get("time", "") for i in items if i.get("time")]
        return {
            "total": total,
            "total_chars": total_chars,
            "total_lines": total_lines,
            "total_copies": total_copies,
            "avg_len": round(total_chars / total, 1) if total else 0,
            "longest": len(longest.get("text","")),
            "most_copied": int(most_copied.get("count", 1)),
            "most_copied_preview": most_copied.get("text","").replace("\n", " ")[:40],
            "favorites": favorites,
            "first_time": times[-1] if times else "",
            "last_time": times[0] if times else "",
        }
    except Exception as e:
        warnings.warn(f"clippy: stats computation failed: {e}", RuntimeWarning)
        logger.error(f"stats failed: {e}")
        return {"total": total, "error": str(e)}


def top(n=10):
    if not isinstance(n, int):
        warnings.warn(f"clippy: top n should be int, got {type(n).__name__}", UserWarning)
        try:
            n = int(n)
        except Exception:
            n = 10
    if n <= 0:
        warnings.warn(f"clippy: top n={n} invalid — returning empty", UserWarning)
        return []
    if n > 1000:
        warnings.warn(f"clippy: top n={n} very large — capping to 1000", UserWarning)
        n = 1000
    try:
        items = load()
    except Exception as e:
        warnings.warn(f"clippy: load failed in top(): {e}", RuntimeWarning)
        return []
    try:
        return sorted(items, key=lambda i: int(i.get("count", 1)), reverse=True)[:n]
    except Exception as e:
        warnings.warn(f"clippy: top sorting failed: {e}", RuntimeWarning)
        return items[:n]
