import platform
import subprocess

SYSTEM = platform.system()


def get_clipboard():
    """Return clipboard text."""

    try:
        if SYSTEM == "Darwin":
            return subprocess.check_output(["pbpaste"]).decode()

        elif SYSTEM == "Linux":
            # Wayland first
            try:
                return subprocess.check_output(["wl-paste"]).decode()
            except Exception:
                return subprocess.check_output(["xclip", "-selection", "clipboard", "-o"]).decode()

        elif SYSTEM == "Windows":
            import pyperclip
            return pyperclip.paste()

    except Exception:
        return ""


def set_clipboard(text):
    """Copy text to clipboard."""

    if SYSTEM == "Darwin":
        p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        p.communicate(text.encode())

    elif SYSTEM == "Linux":
        try:
            p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
        except Exception:
            p = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE
            )

        p.communicate(text.encode())

    elif SYSTEM == "Windows":
        import pyperclip
        pyperclip.copy(text)