__version__ = "2.3"

from .clipboard import ClipboardManager, ClipboardError
from .core import (
    FILE, MAX_ITEMS,
    add, load, save, remove, delete_indices, update, toggle_favorite,
    get_favorites, clear, search, get, count, dedupe, truncate, backup,
    export_history, import_file, stats, top, plural, parse_range,
)

__all__ = [
    "ClipboardManager", "ClipboardError",
    "FILE", "MAX_ITEMS",
    "add", "load", "save", "remove", "delete_indices", "update",
    "toggle_favorite", "get_favorites", "clear", "search", "get", "count",
    "dedupe", "truncate", "backup", "export_history", "import_file",
    "stats", "top", "plural", "parse_range", "get_data_file", "repair",
]

from .server import serve, ClippyServer, ClippyRequestHandler
from . import doctor as doctor_module
from .core import get_data_file, repair

