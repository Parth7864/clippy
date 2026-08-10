#!/bin/sh

PREFIX="${CLIPPY_PREFIX:-$HOME/.local}"
BINDIR="$PREFIX/bin"
LIBDIR="$PREFIX/lib/clippy"
SRC="$(cd "$(dirname "$0")" && pwd)"

usage() {
    cat <<EOF
Usage: ./install.sh [--user | --system | --pip | --uninstall]

  --user       install to ~/.local/bin (default)
  --system     install to /usr/local/bin (needs sudo)
  --pip        install via pip instead of copying files
  --uninstall  remove a previous install
EOF
}

install_files() {
    mkdir -p "$BINDIR" "$LIBDIR"
    cp -f "$SRC/main.py" "$SRC/clipboard.py" "$SRC/history.py" "$LIBDIR/"
    cat > "$LIBDIR/clippy" <<'EOF'
#!/bin/sh
py=python3
if [ "$1" = "gui" ]; then
    for c in python3 /usr/local/bin/python3 /usr/bin/python3; do
        if "$c" -c 'import tkinter' 2>/dev/null; then
            py=$c
            break
        fi
    done
fi
exec "$py" "__LIBDIR__/main.py" "$@"
EOF
    sed -i.bak "s|__LIBDIR__|$LIBDIR|g" "$LIBDIR/clippy"
    rm -f "$LIBDIR/clippy.bak"
    chmod +x "$LIBDIR/clippy" "$LIBDIR"/*.py
    ln -sf "$LIBDIR/clippy" "$BINDIR/clippy"
}

install_pip() {
    python3 -m venv "$SRC/venv"
    "$SRC/venv/bin/pip" install --upgrade pip
    "$SRC/venv/bin/pip" install "$SRC"
    mkdir -p "$BINDIR"
    ln -sf "$SRC/venv/bin/clippy" "$BINDIR/clippy"
}

uninstall() {
    rm -f "$BINDIR/clippy"
    rm -rf "$LIBDIR"
    rm -rf "$SRC/venv"
    rmdir "$(dirname "$LIBDIR")" "$BINDIR" "$PREFIX" 2>/dev/null || true
}

case "${1:---user}" in
    --user)
        install_files
        ;;
    --system)
        mkdir -p "$BINDIR" 2>/dev/null || true
        install_files
        ;;
    --pip)
        install_pip
        ;;
    --uninstall)
        uninstall
        echo "clippy removed"
        exit 0
        ;;
    *)
        usage
        exit 1
        ;;
esac

echo "clippy installed to $BINDIR/clippy"
case ":$PATH:" in
    *":$BINDIR:"*) ;;
    *) echo "add $BINDIR to your PATH: export PATH=\"\$PATH:$BINDIR\"" ;;
esac
echo "run: clippy"