import os
import sys
import time
import json
import hashlib
import logging
import platform
import subprocess
import threading
from datetime import datetime



logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)

logger = logging.getLogger("clippy")



class ClipboardError(Exception):
    pass


class ClipboardManager:

    def __init__(
        self,
        max_size=1000000,
        check_interval=0.5
    ):
        self.system = platform.system()

        self.max_size = max_size
        self.check_interval = check_interval

        self.running = False
        self.thread = None

        self.last_text = ""
        self.last_hash = ""

        self.callbacks = []

        self.history = []


        logger.info(
            f"Clippy initialized on {self.system}"
        )




    def get(self):
        """
        Get current clipboard contents.
        """

        try:

            if self.system == "Darwin":
                return self._mac_get()

            elif self.system == "Linux":
                return self._linux_get()

            elif self.system == "Windows":
                return self._windows_get()

            else:
                raise ClipboardError(
                    "Unsupported operating system"
                )

        except Exception as e:

            logger.error(
                f"Clipboard read failed: {e}"
            )

            return ""


    def set(self, text):
        """
        Set clipboard contents.
        """

        if not isinstance(text, str):
            raise ClipboardError(
                "Clipboard only supports text currently"
            )


        if self.system == "Darwin":
            self._mac_set(text)

        elif self.system == "Linux":
            self._linux_set(text)

        elif self.system == "Windows":
            self._windows_set(text)

        else:
            raise ClipboardError(
                "Unsupported operating system"
            )


    def clear(self):
        """
        Clear clipboard.
        """

        self.set("")




    def watch(self):
        """
        Start clipboard watcher.
        """

        if self.running:
            return


        self.running = True

        self.thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True
        )

        self.thread.start()

        logger.info(
            "Clipboard watcher started"
        )


    def stop(self):

        self.running = False

        if self.thread:
            self.thread.join()

        logger.info(
            "Clipboard watcher stopped"
        )


    def on_change(self, callback):
        """
        Register clipboard event.
        """

        self.callbacks.append(callback)



    def _monitor_loop(self):

        while self.running:

            try:

                text = self.get()

                if text:

                    current_hash = (
                        self._hash(text)
                    )

                    if current_hash != self.last_hash:

                        self.last_hash = current_hash
                        self.last_text = text

                        self._process_change(
                            text
                        )


            except Exception as e:

                logger.error(
                    f"Watcher error: {e}"
                )


            time.sleep(
                self.check_interval
            )


    def _process_change(self, text):

        item = {
            "text": text,
            "time": datetime.now().isoformat(),
            "hash": self._hash(text)
        }


        self.history.insert(
            0,
            item
        )


        for callback in self.callbacks:

            try:
                callback(item)

            except Exception as e:

                logger.error(
                    f"Callback error: {e}"
                )



    def _hash(self, text):

        return hashlib.sha256(
            text.encode()
        ).hexdigest()



    def get_history(self):

        return self.history



    def save_history(self, filename):

        with open(
            filename,
            "w"
        ) as f:

            json.dump(
                self.history,
                f,
                indent=4
            )



    def load_history(self, filename):

        if not os.path.exists(filename):
            return


        with open(
            filename
        ) as f:

            self.history = json.load(f)



    def _mac_get(self):

        result = subprocess.check_output(
            ["pbpaste"]
        )

        return result.decode(
            "utf-8",
            errors="ignore"
        )



    def _mac_set(self, text):

        process = subprocess.Popen(
            ["pbcopy"],
            stdin=subprocess.PIPE
        )

        process.communicate(
            text.encode()
        )




    def _linux_get(self):

        commands = [

            [
                "wl-paste",
                "-n"
            ],

            [
                "xclip",
                "-selection",
                "clipboard",
                "-o"
            ]

        ]


        for cmd in commands:

            try:

                return subprocess.check_output(
                    cmd
                ).decode(
                    errors="ignore"
                )

            except Exception:
                continue


        raise ClipboardError(
            "Install wl-clipboard or xclip"
        )



    def _linux_set(self, text):

        commands = [

            [
                "wl-copy"
            ],

            [
                "xclip",
                "-selection",
                "clipboard"
            ]

        ]


        for cmd in commands:

            try:

                process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE
                )

                process.communicate(
                    text.encode()
                )

                return


            except Exception:
                continue



        raise ClipboardError(
            "No Linux clipboard backend found"
        )




    def _windows_get(self):

        import tkinter

        root = tkinter.Tk()
        root.withdraw()

        try:

            return root.clipboard_get()

        finally:

            root.destroy()



    def _windows_set(self, text):

        import tkinter

        root = tkinter.Tk()

        root.withdraw()

        root.clipboard_clear()

        root.clipboard_append(
            text
        )

        root.update()

        root.destroy()