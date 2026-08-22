import hashlib
import logging
import os
import platform
import shutil
import subprocess
import threading
import time
import warnings

logger = logging.getLogger(__name__)


class ClipboardError(Exception):
    pass


def _which(cmd):
    return shutil.which(cmd)


def _run(cmd, input_text=None, timeout=2):
    try:
        p = subprocess.run(cmd, input=input_text.encode() if input_text is not None else None, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        if p.returncode != 0:
            err = p.stderr.decode(errors="ignore").strip()
            raise ClipboardError(f"{' '.join(cmd)} failed ({p.returncode}): {err or 'no output'}")
        return p.stdout.decode("utf-8", errors="ignore")
    except FileNotFoundError:
        raise ClipboardError(f"command not found: {cmd[0]} — install it (Linux: sudo apt install wl-clipboard xclip xsel)")
    except subprocess.TimeoutExpired:
        raise ClipboardError(f"command timed out: {' '.join(cmd)} — clipboard backend hung")
    except ClipboardError:
        raise
    except Exception as e:
        raise ClipboardError(f"{' '.join(cmd)} error: {e}")


class ClipboardManager:
    def __init__(self, check_interval=0.5):
        self.system = platform.system()
        self.check_interval = check_interval
        self.running = False
        self.thread = None
        self.last_hash = ""
        self.callbacks = []
        self._error_streak = 0
        self._warned_no_backend = False

    def _warn(self, msg):
        warnings.warn(f"clippy clipboard [{self.system}]: {msg}", RuntimeWarning)
        logger.warning(msg)

    def get(self):
        try:
            text = self._get()
            self._error_streak = 0
            return text
        except ClipboardError as e:
            self._warn(f"read failed: {e}")
            logger.error(f"Clipboard read failed: {e}")
            return ""
        except Exception as e:
            self._warn(f"unexpected read error: {e} ({type(e).__name__}) — please report")
            logger.error(f"Clipboard read failed: {e}", exc_info=True)
            return ""

    def set(self, text):
        if not isinstance(text, str):
            warnings.warn(f"clippy: clipboard set expected str, got {type(text).__name__} — coercing", UserWarning)
            text = str(text)
        if len(text) > 500_000:
            warnings.warn(f"clippy: clipboard text very large ({len(text)} chars) — may be slow", UserWarning)
        try:
            self._set(text)
            self._error_streak = 0
        except ClipboardError as e:
            self._warn(f"write failed: {e}")
            logger.error(f"Clipboard write failed: {e}")
            raise
        except Exception as e:
            self._warn(f"unexpected write error: {e}")
            logger.error(f"Clipboard write failed: {e}", exc_info=True)
            raise ClipboardError(str(e))

    def clear(self):
        self.set("")

    def watch(self, callback=None):
        if self.running:
            warnings.warn("clippy: clipboard watch already running — ignoring duplicate watch()", UserWarning)
            if callback and callback not in self.callbacks:
                self.callbacks.append(callback)
            return
        if callback:
            self.callbacks.append(callback)
        if not self.callbacks:
            warnings.warn("clippy: watch called with no callbacks — will poll but do nothing", UserWarning)
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True, name="clippy-clipboard-watch")
        self.thread.start()
        logger.info(f"clipboard watch started on {self.system}")

    def stop(self):
        if not self.running:
            return
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                warnings.warn("clippy: clipboard watch thread did not stop in 2s — forcing", RuntimeWarning)
        logger.info("clipboard watch stopped")

    def diagnose(self):
        info = {"system": self.system, "backends": []}
        s = self.system
        if s == "Darwin":
            info["backends"].append({"cmd": "pbpaste/pbcopy", "found": bool(_which("pbcopy")), "hint": "xcode-select --install if missing"})
        elif s == "Linux":
            for name, cmds in [("wl-clipboard", ["wl-copy", "wl-paste"]), ("xclip", ["xclip"]), ("xsel", ["xsel"])]:
                found = all(_which(c) for c in cmds)
                info["backends"].append({"name": name, "cmds": cmds, "found": found})
            info["display"] = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or "(none)"
            if not info["display"] or info["display"] == "(none)":
                info["warning"] = "No DISPLAY/WAYLAND_DISPLAY — clipboard will fail in headless/SSH without X forwarding"
        elif s == "Windows":
            try:
                import tkinter
                info["backends"].append({"name": "tkinter", "found": True, "version": str(tkinter.TkVersion)})
            except ImportError:
                info["backends"].append({"name": "tkinter", "found": False, "hint": "reinstall Python with tcl/tk"})
            try:
                import ctypes
                info["backends"].append({"name": "ctypes.Win32", "found": True})
            except Exception as e:
                info["backends"].append({"name": "ctypes.Win32", "found": False, "error": str(e)})
        return info

    def _get(self):
        system = self.system
        if system == "Darwin":
            if not _which("pbpaste"):
                raise ClipboardError("pbpaste not found — install Xcode Command Line Tools: xcode-select --install")
            try:
                return subprocess.check_output(["pbpaste"], timeout=2).decode("utf-8", errors="ignore")
            except subprocess.TimeoutExpired:
                raise ClipboardError("pbpaste timed out — clipboard may be busy")
            except FileNotFoundError:
                raise ClipboardError("pbpaste not found")
            except Exception as e:
                raise ClipboardError(f"pbpaste failed: {e}")
        elif system == "Linux":
            errors = []
            candidates = [
                (["wl-paste", "-n"], "wl-clipboard (Wayland)"),
                (["xclip", "-selection", "clipboard", "-o"], "xclip (X11)"),
                (["xsel", "--clipboard", "--output"], "xsel (X11)"),
            ]
            for cmd, label in candidates:
                if not _which(cmd[0]):
                    errors.append(f"{label}: {cmd[0]} not installed")
                    continue
                try:
                    return _run(cmd, timeout=2)
                except ClipboardError as e:
                    errors.append(f"{label}: {e}")
                    continue
            if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                errors.append("No DISPLAY or WAYLAND_DISPLAY set — are you in SSH/headless? Try ssh -X or run with a desktop session")
            hint = "Install a backend: sudo apt install wl-clipboard xclip xsel  |  sudo dnf install wl-clipboard xclip xsel  |  sudo pacman -S wl-clipboard xclip xsel"
            raise ClipboardError("; ".join(errors) + f" — {hint}")
        elif system == "Windows":
            last_err = None
            try:
                import ctypes
                try:
                    user32 = ctypes.windll.user32
                    kernel32 = ctypes.windll.kernel32
                    CF_UNICODETEXT = 13
                    if user32.OpenClipboard(0):
                        try:
                            h = user32.GetClipboardData(CF_UNICODETEXT)
                            if h:
                                kernel32.GlobalLock.restype = ctypes.c_void_p
                                ptr = kernel32.GlobalLock(h)
                                if ptr:
                                    try:
                                        text = ctypes.wstring_at(ptr)
                                        return text or ""
                                    finally:
                                        kernel32.GlobalUnlock(h)
                                else:
                                    last_err = "GlobalLock failed"
                            else:
                                return ""
                        finally:
                            user32.CloseClipboard()
                    else:
                        last_err = "OpenClipboard failed — another app may be holding clipboard"
                except Exception as e:
                    last_err = f"ctypes failed: {e}"
            except Exception as e:
                last_err = str(e)
            try:
                import tkinter
                root = tkinter.Tk()
                root.withdraw()
                try:
                    return root.clipboard_get()
                except Exception as e:
                    raise ClipboardError(f"tkinter clipboard_get failed: {e} (ctypes also: {last_err})")
                finally:
                    try:
                        root.destroy()
                    except Exception:
                        pass
            except ImportError:
                raise ClipboardError(f"No Windows clipboard backend (tkinter missing, ctypes: {last_err}) — reinstall Python with tcl/tk")
            raise ClipboardError(f"Windows clipboard failed (ctypes: {last_err})")
        else:
            raise ClipboardError(f"Unsupported system: {system} — supported: Darwin, Linux, Windows. Got {platform.platform()}")

    def _set(self, text):
        system = self.system
        if system == "Darwin":
            if not _which("pbcopy"):
                raise ClipboardError("pbcopy not found — install Xcode Command Line Tools: xcode-select --install")
            try:
                p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                _, _ = p.communicate(text.encode("utf-8"), timeout=2)
                if p.returncode != 0:
                    raise ClipboardError(f"pbcopy exited {p.returncode}")
            except subprocess.TimeoutExpired:
                try:
                    p.kill()
                except Exception:
                    pass
                raise ClipboardError("pbcopy timed out")
            except FileNotFoundError:
                raise ClipboardError("pbcopy not found")
        elif system == "Linux":
            errors = []
            candidates = [
                (["wl-copy"], "wl-clipboard (Wayland)"),
                (["xclip", "-selection", "clipboard"], "xclip (X11)"),
                (["xsel", "--clipboard", "--input"], "xsel (X11)"),
            ]
            for cmd, label in candidates:
                if not _which(cmd[0]):
                    errors.append(f"{label}: {cmd[0]} not installed")
                    continue
                try:
                    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    _, err = p.communicate(text.encode("utf-8"), timeout=2)
                    if p.returncode == 0:
                        return
                    errors.append(f"{label}: exited {p.returncode}: {err.decode(errors='ignore').strip()}")
                except FileNotFoundError:
                    errors.append(f"{label}: not found")
                except subprocess.TimeoutExpired:
                    try:
                        p.kill()
                    except Exception:
                        pass
                    errors.append(f"{label}: timed out")
                except Exception as e:
                    errors.append(f"{label}: {e}")
            hint = "Install: sudo apt install wl-clipboard xclip xsel"
            raise ClipboardError("; ".join(errors) + f" — {hint}")
        elif system == "Windows":
            last_err = None
            try:
                import ctypes
                CF_UNICODETEXT = 13
                GMEM_MOVEABLE = 0x0002
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                if user32.OpenClipboard(0):
                    try:
                        user32.EmptyClipboard()
                        if text:
                            data = text.encode("utf-16-le") + b"\x00\x00"
                            h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                            if not h:
                                raise ClipboardError("GlobalAlloc failed — out of memory?")
                            kernel32.GlobalLock.restype = ctypes.c_void_p
                            ptr = kernel32.GlobalLock(h)
                            if not ptr:
                                kernel32.GlobalFree(h)
                                raise ClipboardError("GlobalLock failed")
                            try:
                                ctypes.memmove(ptr, data, len(data))
                            finally:
                                kernel32.GlobalUnlock(h)
                            if not user32.SetClipboardData(CF_UNICODETEXT, h):
                                kernel32.GlobalFree(h)
                                raise ClipboardError("SetClipboardData failed — clipboard may be locked by another app")
                        return
                    finally:
                        user32.CloseClipboard()
                else:
                    last_err = "OpenClipboard failed — clipboard locked by another app (try again)"
            except ClipboardError:
                raise
            except Exception as e:
                last_err = f"ctypes failed: {e}"
            try:
                import tkinter
                root = tkinter.Tk()
                root.withdraw()
                try:
                    root.clipboard_clear()
                    root.clipboard_append(text)
                    root.update()
                    return
                finally:
                    try:
                        root.destroy()
                    except Exception:
                        pass
            except ImportError:
                raise ClipboardError(f"No Windows clipboard backend (tkinter missing, ctypes: {last_err})")
            except Exception as e:
                raise ClipboardError(f"Windows clipboard failed: {e} (ctypes: {last_err})")
            raise ClipboardError(f"Windows clipboard failed (ctypes: {last_err})")
        else:
            raise ClipboardError(f"Unsupported system: {system}")

    def _monitor_loop(self):
        consecutive_empty = 0
        while self.running:
            try:
                text = self._get()
                if text:
                    consecutive_empty = 0
                    if len(text) > 500_000:
                        warnings.warn(f"clippy: clipboard very large ({len(text)} chars) — not saving to history", UserWarning)
                        self._error_streak = 0
                    else:
                        h = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
                        if h != self.last_hash:
                            self.last_hash = h
                            self._error_streak = 0
                            for cb in list(self.callbacks):
                                try:
                                    cb(text)
                                except Exception as e:
                                    warnings.warn(f"clippy: clipboard callback {cb.__name__ if hasattr(cb, '__name__') else cb} failed: {e}", RuntimeWarning)
                                    logger.error(f"Callback error: {e}", exc_info=True)
                else:
                    consecutive_empty += 1
                    self._error_streak = 0
                    if consecutive_empty > 100:
                        time.sleep(1)
            except ClipboardError as e:
                self._error_streak += 1
                if self._error_streak <= 3 or self._error_streak % 10 == 0:
                    warnings.warn(f"clippy: clipboard monitor error ({self._error_streak}): {e}", RuntimeWarning)
                logger.error(f"Monitor error ({self._error_streak}): {e}")
            except Exception as e:
                self._error_streak += 1
                warnings.warn(f"clippy: unexpected monitor error ({self._error_streak}): {e} ({type(e).__name__})", RuntimeWarning)
                logger.error(f"Monitor error ({self._error_streak}): {e}", exc_info=True)
            base = self.check_interval
            if self._error_streak:
                sleep = base * min(2 ** min(self._error_streak, 6), 30)
                if self._error_streak >= 5:
                    warnings.warn(f"clippy: backing off clipboard polling to {sleep:.1f}s after {self._error_streak} errors", UserWarning)
            else:
                sleep = base
            time.sleep(sleep)
