# clippy

A clipboard manager that lives in your terminal. I built it because I kept losing that one URL or code block I copied twenty minutes ago. It watches what you copy, keeps a searchable history, and lets you pull anything back in seconds. No extra dependencies — just the Python standard library. Works on macOS, Linux, and Windows.

## Install

The fastest way to get a `clippy` that works from anywhere:

```sh
./install.sh
```

That puts the code in `~/.local/lib/clippy` and drops a launcher in `~/.local/bin`. If `~/.local/bin` is not on your PATH yet:

```sh
echo 'export PATH="$PATH:$HOME/.local/bin"' >> ~/.zshrc
# then restart your shell, or run `source ~/.zshrc`
```

### As a Python package

You can also install it like any other package. From the repo itself:

```sh
pip install .                  # normal install
pipx install .                 # isolated, recommended if you use pipx
```

Once it is on PyPI, the name there is `clippy-clipboard`:

```sh
pip install clippy-clipboard
pipx install clippy-clipboard
```

Using it from Python is straightforward:

```python
from clippy import ClipboardManager, add, search, stats, top

add("hello world")
print(search("hello"))
print(stats())
```

Need a different backend in a script? The clipboard manager is there too:

```python
from clippy import ClipboardManager
cm = ClipboardManager()
cm.set("new clipboard value")
print(cm.get())
```

### Other install options

```sh
./install.sh --pip       # install via pip into a private venv under ~/.local/lib/clippy
./install.sh --system    # system-wide to /usr/local/bin (run with sudo)
./install.sh --uninstall # remove everything the installer created
```

No install at all — just run it from the checkout:

```sh
python -m clippy
python -m clippy history
python -m clippy serve
```

## Where your history lives

By default there is one file for your whole machine:

* macOS and Linux: `~/.clippy_history.json`
* Linux with XDG: `$XDG_DATA_HOME/clippy/history.json` if that exists, otherwise `~/.local/share/clippy/history.json`
* Windows: `%APPDATA%\clippy\history.json`
* Fallback everywhere: `~/.clippy_history.json`

It is the same no matter which directory you run `clippy` from. If you are coming from a very old checkout that used `data.json` in the repo root, clippy will copy it over the first time it runs.

Want to keep a project-specific history or keep tests isolated? Point it somewhere else:

```sh
CLIPPY_DATA=/tmp/try.json clippy watch
CLIPPY_DATA=/tmp/project.json clippy set "$(pwd)"
CLIPPY_DATA=./demo.json clippy history --json
```

Each item stores `text`, `time` (ISO seconds), `count` (how many times you copied it), and `favorite` (true/false). The file is capped at 500 items — the oldest drops off when a new one comes in. If the file gets corrupted (bad JSON, bad permissions, truncated write), clippy moves it to `~/.clippy_history.json.corrupt` and starts fresh. Run `clippy doctor --fix` to repair or truncate it.

## Using it

Run it with no arguments and you get the interactive menu. Everything you copy while it is open is saved automatically.

```sh
clippy
```

If you just want to log to the terminal without the menu:

```sh
clippy watch
# watching clipboard... (Ctrl+C to stop)
#   copied: git diff --stat
#   copied: https://example.com/very/long/url
```

### Commands

All commands work as `clippy <command>`. `clippy --help` shows them, here is the short version:

| Command | What it does |
| --- | --- |
| `menu` | Interactive fullscreen menu. This is the default if you run `clippy` with no args. |
| `watch` | Watch the clipboard and print new copies as they arrive. |
| `history` | List everything saved, oldest last. `history --json` for JSON. |
| `search <query>` | Case-insensitive search. `search "deploy" --json` for scripts. |
| `top [n]` | Most-copied items. Defaults to top 10. |
| `stats` | Totals, average length, longest item, most-copied, first/last time. |
| `favorite <index>` | Toggle the star on an item. |
| `edit <index>` | Open an item in `$EDITOR` (falls back to `vi`), save your edit back. |
| `delete <range>` | Delete by index. Examples: `delete 3`, `delete 3-10`, `delete 1,3,7`, `delete all`. |
| `truncate <n>` | Keep only the first `n` items, drop the rest. |
| `dedupe` | Remove duplicate texts, keep the most recent copy. |
| `backup` | Make a timestamped copy next to your current file (`clippy_backup_20250101-120000.json`). |
| `export [json|txt|md] [file]` | Dump history. Defaults to `clippy_export.json` if you do not give a file. |
| `import <file.json>` | Merge items from another JSON file, skips duplicates. |
| `get <index>` | Print one item’s text (1 is the most recent). Good for piping. |
| `set <text>` | Save text to history and copy it to the clipboard. Supports `--stdin` and `--file <path>`. |
| `gui` | Small desktop window with search and live updates. See GUI section below. |
| `serve` | Start a local web dashboard + REST API on `127.0.0.1`. |
| `api <path>` | Call the running server’s API without curl. Examples below. |
| `doctor` | Diagnose clipboard, data file, permissions, dependencies, and disk. |
| `repair` | Same as `doctor --fix` — repair the history file in place. |

### Global flags

These work with any command:

```sh
--json        # machine-readable JSON (for history, search, stats, etc.)
              # for get/set/api, --json forces JSON output
--verbose     # show all warnings and debug logs
--fix         # with export/doctor, auto-fix or overwrite
--no-color    # plain output for doctor
--quiet       # suppress human-friendly status lines
--host, --port, --method, --data, --stdin, --file  # see --help for details
--version     # print clippy 2.3 and exit
```

Exit codes are `0` on success, `1` on error, `130` on Ctrl+C. That makes it easy to use in scripts:

```sh
CLIPPY_DATA=/tmp/demo.json clippy set "hello" --json
clippy history --json | jq '.[0].text'
clippy get 1 > /tmp/last.txt
```

## Menu keys

Inside `clippy` (and `clippy menu`):

```
j, k or arrows         move up / down
f, b or PgUp / PgDn    page down / up
g / G                  jump to top / bottom
enter                  copy the selected item back to the clipboard
/                      start search — type, then Enter to jump to the first match
n                      next match (after you have searched)
e                      edit the selected item in $EDITOR
f                      toggle favorite on the selected item
F                      show only favorites (press again to show all)
d                      delete the selected item
c                      clear the whole history
q or Esc               quit
```

If your terminal says `curses not available` on Windows, run `pip install windows-curses` and try again. On macOS and Linux, curses is built in.

## GUI

```sh
clippy gui
```

You get a draggable window with a search box, a live list, a preview of the selected item, a range field, and buttons for Copy, Delete, Favorite, Clear All, and Refresh. Double-click an item to copy it. It watches the clipboard in the background, so new copies appear without restarting.

The window is frameless on macOS (with its own close/minimize/zoom and a resize grip in the corner) and uses the normal window chrome on Windows and Linux so resizing and minimizing work as you would expect. It is resizable everywhere — drag the corner or the window edge.

You need a Python built with tkinter:

* macOS: `brew install python-tk@3.14` then reinstall clippy with that Python
* Debian/Ubuntu: `sudo apt install python3-tk`
* Fedora: `sudo dnf install python3-tkinter`
* Windows: make sure you checked “tcl/tk and IDLE” when you installed Python

If you installed with pipx and `clippy gui` complains:

```sh
pipx install --python /usr/bin/python3 .
# or
pipx install --python /opt/homebrew/bin/python3.14 .
```

Keyboard in the GUI: Enter or Space to copy, Delete to delete, `f` to toggle favorite, `/` or Backspace to jump to search.

## Local server and REST API

`clippy serve` is a tiny HTTP server with no extra dependencies. It binds to `127.0.0.1` only, so nothing is exposed to your network unless you ask it to.

```sh
clippy serve                     # picks a free port, prints the URL
clippy serve --port 8765         # fixed port
clippy serve --host 0.0.0.0      # listen on all interfaces — only on a trusted network
```

You will see something like:

```
clippy: serving on http://127.0.0.1:8765  (Ctrl+C to stop)
clippy: web page    http://127.0.0.1:8765/
clippy: data file   /Users/you/.clippy_history.json
```

Open that URL and you get a minimal dashboard — current clipboard, save box, search, history with copy/favorite/delete, and stats. There is a theme toggle in the corner. It refreshes every few seconds, so it stays in sync with the terminal.

For scripts, editor plugins, or a browser widget, talk to it over HTTP. All responses are JSON with `Access-Control-Allow-Origin: *`.

### API endpoints

| Method | Path | What it does |
| --- | --- | --- |
| `GET` | `/` | The dashboard |
| `GET` | `/api/status` | Version, item count, current clipboard, data file |
| `GET` | `/api/health` | Liveness probe — `{"status":"ok"}` |
| `GET` | `/api/docs` | Human-readable API reference |
| `GET` | `/api/openapi.json` | OpenAPI 3.0 spec for code generation |
| `GET` | `/api/clipboard` | `{"clipboard": "..."}` |
| `POST` | `/api/clipboard` | Set clipboard. Body: `{"text":"..."}` |
| `GET` | `/api/history` | `{"items": [{"index","text","time","count","favorite"}]}` |
| `POST` | `/api/history` | Add an item. Body: `{"text":"..."}` |
| `DELETE` | `/api/history` | Clear all |
| `GET` | `/api/history/<i>` | One item |
| `PUT` | `/api/history/<i>` | Update one item. Body: `{"text":"..."}` |
| `DELETE` | `/api/history/<i>` | Delete one item |
| `POST` | `/api/history/<i>/favorite` | Toggle favorite |
| `POST` | `/api/history/<i>/copy` | Copy that item to the clipboard |
| `GET` | `/api/search?q=<query>` | Search |
| `GET` | `/api/top?n=<count>` | Most-copied |
| `GET` | `/api/stats` | Same numbers as `clippy stats` |
| `GET` | `/api/favorites` | Only favorites |
| `GET` | `/api/count` | Number of items |
| `GET` | `/api/backup` | Create a timestamped backup |
| `GET` | `/api/export?format=json|txt|md` | Export as JSON, text, or markdown |

A couple of curl examples from any language:

```sh
curl -s http://127.0.0.1:8765/api/health
curl -s http://127.0.0.1:8765/api/history | jq
curl -s -X POST http://127.0.0.1:8765/api/history \
  -H 'Content-Type: application/json' -d '{"text":"pasted via curl"}'
curl -s -X POST http://127.0.0.1:8765/api/clipboard \
  -H 'Content-Type: application/json' -d '{"text":"new clipboard"}'
```

You do not need curl — clippy has `api` for that:

```sh
clippy api /api/history
clippy api /api/search?q=deploy
clippy api /api/health
clippy api /api/openapi.json
clippy api /api/history --method POST --data '{"text":"hello from a script"}'
clippy api /api/clipboard --method POST --data '{"text":"new clipboard value"}'
clippy api /api/history/3 --method DELETE
clippy api / --json=false    # raw HTML, no pretty-print
```

By default `api` talks to `127.0.0.1:8765`. If your server is on another port:

```sh
clippy api /api/history --port 8765
```

## Doctor and self-healing

If something feels off — copies not showing up, file errors, clipboard not working — run:

```sh
clippy doctor
clippy doctor --fix      # try to repair automatically
clippy doctor --json     # machine-readable, for scripts
clippy repair            # shorthand for doctor --fix
```

It checks Python version, platform, data file and its directory, permissions, JSON validity, size, clipboard backends, tkinter/curses, whether it can bind a local port, and free disk space. With `--fix` it will create a missing directory, fix permissions where it can, move a corrupt JSON file to `*.corrupt` and start fresh, remove malformed entries, and truncate an oversized history to 500.

Most core operations also warn rather than crash. If your history file is corrupt you will see a clear message telling you where the backup went and what to run next. If a clipboard backend is missing on Linux, you will get the exact `apt install` line for `wl-clipboard`, `xclip`, or `xsel`.

## Cross-platform notes

* **macOS** uses `pbcopy` / `pbpaste`. If those are missing, reinstall the Xcode Command Line Tools: `xcode-select --install`. Curses and the menu work out of the box. For the GUI, you need a Python with tkinter as noted above.

* **Linux** tries Wayland first (`wl-copy` / `wl-paste`), then `xclip`, then `xsel`. Install at least one:
  ```sh
  sudo apt install wl-clipboard xclip xsel   # Debian/Ubuntu
  sudo dnf install wl-clipboard xclip xsel   # Fedora
  sudo pacman -S wl-clipboard xclip xsel     # Arch
  ```
  If you are over SSH without `DISPLAY` or `WAYLAND_DISPLAY`, the clipboard will fail — that is expected. Use `ssh -X` or run on a desktop session.

* **Windows** tries the Win32 API via `ctypes` first, then falls back to `tkinter`. For the fullscreen menu you need `windows-curses`:
  ```sh
  pip install windows-curses
  ```
  The GUI needs the `tcl/tk` option checked when you install Python. Data lives under `%APPDATA%\clippy\history.json`.

In all cases `clippy doctor` will tell you what is missing and how to install it.

## Troubleshooting

* `No module named '_curses'` or `curses not available` — Windows without `windows-curses`. Fix: `pip install windows-curses`.
* `No module named '_tkinter'` or GUI fails to open — Python without tkinter. See GUI section for your OS.
* `clipboard read failed` / `No clipboard backend` on Linux — install `wl-clipboard` or `xclip`.
* `permission denied` on the history file — `chmod 600 ~/.clippy_history.json` or run `clippy doctor --fix`.
* `port already in use` from `clippy serve` — `clippy serve --port 0` for a free port, or `lsof -i :8765` to find what is using it.
* `history file large` warning — `clippy truncate 200` or `clippy dedupe`.

Re-run any failing command with `--verbose` to see the full warning and traceback.

## Development

```
clippy/
  core.py        history storage and helpers
  clipboard.py   cross-platform clipboard access
  server.py      local HTTP server, REST API, and dashboard
  cli.py         command-line interface, TUI, and GUI
  doctor.py      diagnostics and auto-repair
```

Run the tests:

```sh
python -m pytest
python -m pytest -v --tb=short   # more detail
```

Build the package:

```sh
python3 -m pip install --break-system-packages build twine
python3 -m build
python3 -m twine check dist/*
```

Install the wheel you just built in a clean venv to sanity-check it:

```sh
python3 -m venv /tmp/cvenv
/tmp/cvenv/bin/pip install dist/clippy_clipboard-*.whl
/tmp/cvenv/bin/clippy --version
/tmp/cvenv/bin/clippy doctor
```

The web dashboard is at `http://127.0.0.1:<port>/` when you run `clippy serve`, API docs at `/api/docs`, OpenAPI at `/api/openapi.json`.
