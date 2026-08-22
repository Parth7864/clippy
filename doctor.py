import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import warnings

from . import core
from .clipboard import ClipboardManager


def _check(status, msg, fix_msg=None, fixed=False):
    return {"status": status, "message": msg, "fix": fix_msg, "fixed": fixed}


def check_python():
    v = sys.version_info
    if v < (3, 9):
        return _check("error", f"Python {v.major}.{v.minor} too old — clippy needs 3.9+", "Install Python 3.9+")
    if v < (3, 11):
        return _check("warning", f"Python {v.major}.{v.minor} works but 3.11+ is recommended")
    return _check("ok", f"Python {v.major}.{v.minor}.{v.micro} OK")


def check_platform():
    s = platform.system()
    if s in ("Darwin", "Linux", "Windows"):
        return _check("ok", f"Platform {s} {platform.release()} supported")
    return _check("warning", f"Platform {s} not officially tested — may work via fallback")


def check_data_file(fix=False):
    path = core.get_data_file() if hasattr(core, "get_data_file") else core.FILE
    env = os.environ.get("CLIPPY_DATA")
    results = []
    results.append(_check("ok", f"Data file: {path}" + (f" (CLIPPY_DATA={env})" if env else "")))
    parent = os.path.dirname(path) or "."
    if not os.path.exists(parent):
        if fix:
            try:
                os.makedirs(parent, exist_ok=True)
                results.append(_check("ok", f"Created missing directory {parent}", fixed=True))
            except Exception as e:
                results.append(_check("error", f"Cannot create directory {parent}: {e}", f"mkdir -p {parent}"))
        else:
            results.append(_check("error", f"Directory {parent} does not exist", f"mkdir -p {parent}"))
    else:
        results.append(_check("ok", f"Directory {parent} exists"))
        try:
            ok = os.access(parent, os.W_OK)
            if not ok:
                if fix:
                    try:
                        os.chmod(parent, stat.S_IRWXU)
                        results.append(_check("warning", f"Fixed permissions on {parent}", fixed=True))
                    except Exception as e:
                        results.append(_check("error", f"Directory not writable: {parent}: {e}", f"chmod u+w {parent}"))
                else:
                    results.append(_check("error", f"Directory not writable: {parent}", f"chmod u+w {parent}"))
            else:
                results.append(_check("ok", "Directory writable"))
        except Exception as e:
            results.append(_check("warning", f"Permission check failed: {e}"))

    if os.path.exists(path):
        try:
            st = os.stat(path)
            size = st.st_size
            if size > 10 * 1024 * 1024:
                results.append(_check("warning", f"History file large ({size//1024} KiB) — consider truncating", "clippy truncate 500"))
            elif size == 0:
                results.append(_check("warning", "History file is empty"))
            else:
                results.append(_check("ok", f"History file {size} bytes"))
            if not os.access(path, os.R_OK):
                results.append(_check("error", "History file not readable", f"chmod 600 {path}"))
            if not os.access(path, os.W_OK):
                if fix:
                    try:
                        os.chmod(path, 0o600)
                        results.append(_check("warning", f"Fixed permissions on {path}", fixed=True))
                    except Exception as e:
                        results.append(_check("error", f"History file not writable: {e}", f"chmod 600 {path}"))
                else:
                    results.append(_check("error", "History file not writable", f"chmod 600 {path}"))
            else:
                results.append(_check("ok", "History file readable/writable"))
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    results.append(_check("error", f"History JSON is {type(data).__name__}, expected list", "clippy doctor --fix will reset"))
                    if fix:
                        core.save([])
                        results.append(_check("ok", "Reset corrupt history to empty", fixed=True))
                else:
                    bad = 0
                    for i, e in enumerate(data):
                        if isinstance(e, dict):
                            if "text" not in e:
                                bad += 1
                        elif not isinstance(e, str):
                            bad += 1
                    if bad:
                        msg = f"{bad} malformed entries in history"
                        if fix:
                            try:
                                core.repair() if hasattr(core, "repair") else core.load()
                                results.append(_check("warning", f"{msg} — repaired", fixed=True))
                            except Exception as ex:
                                results.append(_check("error", f"{msg}: {ex}"))
                        else:
                            results.append(_check("warning", msg, "clippy doctor --fix"))
                    else:
                        results.append(_check("ok", f"JSON valid, {len(data)} items"))
                    if len(data) > core.MAX_ITEMS:
                        results.append(_check("warning", f"{len(data)} items exceeds MAX_ITEMS={core.MAX_ITEMS}", "clippy truncate 500 / clippy doctor --fix"))
                        if fix:
                            try:
                                core.truncate(core.MAX_ITEMS)
                                results.append(_check("ok", f"Truncated to {core.MAX_ITEMS}", fixed=True))
                            except Exception as e:
                                results.append(_check("error", f"Truncate failed: {e}"))
            except json.JSONDecodeError as e:
                if fix:
                    try:
                        corrupt = path + ".corrupt"
                        if os.path.exists(path):
                            shutil.copy(path, corrupt)
                        core.save([])
                        results.append(_check("error", f"JSON corrupt at line {e.lineno}: {e.msg} — backed up to {corrupt} and reset", fixed=True))
                    except Exception as ex:
                        results.append(_check("error", f"JSON corrupt: {e} (repair failed: {ex})"))
                else:
                    results.append(_check("error", f"JSON corrupt at line {e.lineno}: {e.msg}", "clippy doctor --fix"))
            except OSError as e:
                results.append(_check("error", f"Cannot read history: {e}"))
        except OSError as e:
            results.append(_check("error", f"Cannot stat history file: {e}"))
    else:
        results.append(_check("ok", "No history file yet — will be created on first copy"))
        legacy = os.path.join(os.getcwd(), "data.json")
        if os.path.exists(legacy):
            results.append(_check("warning", f"Legacy data.json found at {legacy} — will be migrated on next load"))
    return results


def check_clipboard():
    results = []
    sysname = platform.system()
    mgr = ClipboardManager()
    try:
        cur = mgr.get()
        results.append(_check("ok", f"Clipboard read OK ({len(cur)} chars)" if cur else "Clipboard read OK (empty)"))
    except Exception as e:
        results.append(_check("error", f"Clipboard read failed on {sysname}: {e}", _clipboard_hint(sysname)))
        warnings.warn(f"clipboard read failed: {e}", RuntimeWarning)
    try:
        test = "__clippy_doctor_test__"
        mgr.set(test)
        back = mgr.get()
        if back == test:
            results.append(_check("ok", "Clipboard write/read round-trip OK"))
            try:
                mgr.set(cur if 'cur' in locals() else "")
            except Exception:
                pass
        else:
            results.append(_check("warning", f"Clipboard write succeeded but read-back mismatch (wrote {test!r}, got {back!r})"))
    except Exception as e:
        results.append(_check("error", f"Clipboard write failed: {e}", _clipboard_hint(sysname)))
        warnings.warn(f"clipboard write failed: {e}", RuntimeWarning)

    if sysname == "Linux":
        has_wl = shutil.which("wl-copy") and shutil.which("wl-paste")
        has_xclip = shutil.which("xclip")
        has_xsel = shutil.which("xsel")
        if not any([has_wl, has_xclip, has_xsel]):
            results.append(_check("error", "No Linux clipboard backend found (need wl-clipboard, xclip, or xsel)",
                                  "sudo apt install wl-clipboard xclip  /  sudo pacman -S wl-clipboard"))
        else:
            backends = []
            if has_wl: backends.append("wl-clipboard")
            if has_xclip: backends.append("xclip")
            if has_xsel: backends.append("xsel")
            results.append(_check("ok", f"Clipboard backends: {', '.join(backends)}"))
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            results.append(_check("warning", "No DISPLAY/WAYLAND_DISPLAY — clipboard may fail in headless session"))
    elif sysname == "Darwin":
        if not shutil.which("pbcopy"):
            results.append(_check("error", "pbcopy not found — broken macOS install"))
        else:
            results.append(_check("ok", "pbcopy/pbpaste available"))
    elif sysname == "Windows":
        try:
            import tkinter
            results.append(_check("ok", "tkinter available for Windows clipboard"))
        except ImportError:
            try:
                import ctypes
                results.append(_check("warning", "tkinter missing but ctypes fallback available", "pip install tkinter or use python-tk"))
            except Exception:
                results.append(_check("error", "No Windows clipboard backend", "reinstall Python with tkinter"))
    return results


def _clipboard_hint(sysname):
    if sysname == "Linux":
        return "Install: sudo apt install xclip wl-clipboard  |  sudo dnf install xclip wl-clipboard"
    if sysname == "Darwin":
        return "Ensure pbcopy/pbpaste in PATH (Xcode CLT: xcode-select --install)"
    if sysname == "Windows":
        return "Reinstall Python with tcl/tk enabled"
    return None


def check_dependencies():
    results = []
    for mod in ("json", "sqlite3"):
        try:
            __import__(mod)
            results.append(_check("ok", f"Module {mod} available"))
        except ImportError as e:
            results.append(_check("error", f"Module {mod} missing: {e}"))
    try:
        import tkinter
        results.append(_check("ok", f"tkinter {tkinter.TkVersion} available — GUI will work"))
    except ImportError:
        results.append(_check("warning", "tkinter not available — `clippy gui` will fail",
                              "macOS: brew install python-tk@3.14  |  Debian/Ubuntu: sudo apt install python3-tk"))
    try:
        import curses
        results.append(_check("ok", "curses available — `clippy menu` will work"))
    except ImportError:
        if platform.system() == "Windows":
            results.append(_check("warning", "curses not available on Windows — `clippy menu` unavailable",
                                  "pip install windows-curses"))
        else:
            results.append(_check("warning", "curses not available — `clippy menu` will fail"))
    return results


def check_server():
    results = []
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        results.append(_check("ok", f"Can bind localhost (tested port {port})"))
    except OSError as e:
        results.append(_check("error", f"Cannot bind localhost: {e}", "Check firewall / localhost config"))
    finally:
        s.close()
    return results


def check_disk():
    results = []
    path = core.get_data_file() if hasattr(core, "get_data_file") else core.FILE
    parent = os.path.dirname(os.path.abspath(path)) or "."
    try:
        usage = shutil.disk_usage(parent)
        free_mb = usage.free // (1024 * 1024)
        if free_mb < 10:
            results.append(_check("warning", f"Low disk space: {free_mb} MiB free on {parent}"))
        else:
            results.append(_check("ok", f"Disk space OK ({free_mb} MiB free)"))
    except Exception as e:
        results.append(_check("warning", f"Cannot check disk space: {e}"))
    return results


def run_all(fix=False):
    sections = [
        ("Python", [check_python()]),
        ("Platform", [check_platform()]),
        ("Data file", check_data_file(fix=fix)),
        ("Clipboard", check_clipboard()),
        ("Dependencies", check_dependencies()),
        ("Server", check_server()),
        ("Disk", check_disk()),
    ]
    flat = []
    for name, checks in sections:
        for c in checks:
            c["section"] = name
            flat.append(c)
    errors = sum(1 for c in flat if c["status"] == "error")
    warnings_cnt = sum(1 for c in flat if c["status"] == "warning")
    ok = sum(1 for c in flat if c["status"] == "ok")
    summary = {"errors": errors, "warnings": warnings_cnt, "ok": ok, "total": len(flat), "fix": fix}
    return sections, summary


def format_report(sections, summary, use_color=True):
    colors = {"ok": "\033[32m", "warning": "\033[33m", "error": "\033[31m", "reset": "\033[0m"} if use_color and sys.stdout.isatty() else {"ok": "", "warning": "", "error": "", "reset": ""}
    icons = {"ok": "✓", "warning": "⚠", "error": "✗"}
    lines = []
    for name, checks in sections:
        lines.append(f"\n{name}:")
        for c in checks:
            icon = icons.get(c["status"], "?")
            col = colors.get(c["status"], "")
            rst = colors["reset"]
            fixed = " [FIXED]" if c.get("fixed") else ""
            lines.append(f"  {col}{icon} {c['message']}{fixed}{rst}")
            if c.get("fix") and c["status"] in ("error", "warning"):
                lines.append(f"      → fix: {c['fix']}")
    lines.append("")
    if summary["errors"] == 0 and summary["warnings"] == 0:
        lines.append(f"{colors['ok']}All checks passed ({summary['ok']}/{summary['total']}){colors['reset']}")
    else:
        lines.append(f"Summary: {summary['ok']} ok, {summary['warnings']} warnings, {summary['errors']} errors")
        if summary["errors"] and not summary["fix"]:
            lines.append("Run `clippy doctor --fix` to auto-fix what we can.")
    return "\n".join(lines)
