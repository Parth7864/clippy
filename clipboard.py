import hashlib
import logging
import platform
import subprocess
import threading
import time

logger = logging.getLogger(__name__)


class ClipboardError(Exception):
    pass


class ClipboardManager:
    def __init__(self, check_interval=0.5):
        self.system = platform.system()
        self.check_interval = check_interval
        self.running = False
        self.thread = None
        self.last_hash = ""
        self.callbacks = []
        self._error_streak = 0

    def get(self):
        try:
            return self._get()
        except Exception as e:
            logger.error(f"Clipboard read failed: {e}")
            return ""

    def set(self, text):
        if not isinstance(text, str):
            raise ClipboardError("Clipboard only supports text")
        try:
            self._set(text)
        except Exception as e:
            logger.error(f"Clipboard write failed: {e}")

    def clear(self):
        self.set("")

    def watch(self, callback=None):
        if self.running:
            return
        if callback:
            self.callbacks.append(callback)
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)

    def _get(self):
        system = self.system
        if system == "Darwin":
            return subprocess.check_output(["pbpaste"]).decode("utf-8", errors="ignore")
        elif system == "Linux":
            for cmd in (["wl-paste", "-n"], ["xclip", "-selection", "clipboard", "-o"]):
                try:
                    return subprocess.check_output(cmd).decode(errors="ignore")
                except Exception:
                    continue
            raise ClipboardError("Install wl-clipboard or xclip")
        elif system == "Windows":
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            try:
                return root.clipboard_get()
            finally:
                root.destroy()
        raise ClipboardError(f"Unsupported system: {system}")

    def _set(self, text):
        system = self.system
        if system == "Darwin":
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(text.encode())
        elif system == "Linux":
            for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
                try:
                    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                    p.communicate(text.encode())
                    return
                except Exception:
                    continue
            raise ClipboardError("No Linux clipboard backend found")
        elif system == "Windows":
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()
            root.destroy()
        else:
            raise ClipboardError(f"Unsupported system: {system}")

    def _monitor_loop(self):
        while self.running:
            try:
                text = self._get()
                if text:
                    h = hashlib.sha256(text.encode()).hexdigest()
                    if h != self.last_hash:
                        self.last_hash = h
                        self._error_streak = 0
                        for cb in self.callbacks:
                            try:
                                cb(text)
                            except Exception as e:
                                logger.error(f"Callback error: {e}")
                else:
                    self._error_streak = 0
            except Exception as e:
                self._error_streak += 1
                logger.error(f"Monitor error ({self._error_streak}): {e}")
            sleep = self.check_interval * min(2 ** self._error_streak, 30)
            time.sleep(sleep)
