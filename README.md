# clippy

A clipboard manager for the terminal. Watches your OS clipboard, keeps a searchable
history, and lets you copy, favorite, edit, and export past items.

Pure standard library, no dependencies. Works on macOS, Linux, and Windows.

## Data

History is stored in `data.json` in the current directory if it exists, otherwise
`~/.clippy_history.json`. Override with the `CLIPPY_DATA` environment variable to
point at a specific file.

Each entry keeps the text, a timestamp, a copy count, and an optional favorite flag.
History is capped at 500 items (oldest dropped first on new copies).

## Usage

Run with no arguments to open the interactive menu (TUI):

    python3 main.py

### Commands

| Command | Description |
| --- | --- |
| `menu` | Interactive TUI (default) |
| `watch` | Watch the clipboard and log new copies |
| `history` | List saved items |
| `search <query>` | Search saved text |
| `top [n]` | Show the most-copied items |
| `stats` | Show aggregate statistics |
| `favorite <index>` | Toggle favorite on an item |
| `edit <index>` | Edit an item in `$EDITOR` |
| `delete <range>` | Delete by index, `3-10`, `1,3,7`, or `all` |
| `truncate <n>` | Keep the first `n` items |
| `dedupe` | Remove duplicate text entries |
| `backup` | Copy the data file with a timestamp |
| `export [format] [file]` | Export text as `json`, `txt`, or `md` |
| `import <file.json>` | Import entries from a JSON file |
| `gui` | Windowed GUI (requires tkinter) |
| `stats` | Print aggregate statistics |
| `--version` | Show version |

## TUI keys

```
↑/↓ or j/k      move
PgUp/PgDn or f/b page
g / G           top / bottom
enter           copy to clipboard
/               search (enter to lock, n for next match)
e               edit in $EDITOR
f               toggle favorite
F               show favorites only
d               delete item
c               clear history
q               quit
```

## GUI

Requires Python with tkinter (macOS: `brew install python-tk@3.14`; Linux:
`sudo apt install python3-tk`). Frameless, draggable by the header, rounded corners,
live-refreshing list, search box, range delete (e.g. `3-10` or `all`), and click/double-click
to copy.
