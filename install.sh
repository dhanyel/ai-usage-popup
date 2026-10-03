#!/usr/bin/env bash
# Installs AI Usage Popup for the current user (no sudo):
#   ~/.local/bin/ai-usage-popup, its launcher and its icon.
# Usage: ./install.sh            install or update
#        ./install.sh --uninstall
set -euo pipefail

here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
prefix="${PREFIX:-$HOME/.local}"
data="${XDG_DATA_HOME:-$prefix/share}"
bin="$prefix/bin/ai-usage-popup"
desktop="$data/applications/ai-usage-popup.desktop"
icon="$data/icons/hicolor/scalable/apps/ai-usage-popup.svg"

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -f "$bin" "$desktop" "$icon"
  echo "Removed AI Usage Popup."
  exit 0
fi

python3 - <<'PY' || { echo "Python 3.11+ with PyGObject and GTK 3 is required (Debian/Ubuntu: sudo apt install python3-gi gir1.2-gtk-3.0)." >&2; exit 1; }
import sys
assert sys.version_info >= (3, 11), "Python 3.11+ required"
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: F401
PY

install -Dm755 "$here/ai-usage-popup" "$bin"
install -Dm644 "$here/icons/ai-usage-popup.svg" "$icon"
mkdir -p "$(dirname "$desktop")"
# Absolute Exec path: a launcher does not always see the PATH set by the shell profile.
sed "s|^Exec=.*|Exec=$bin|" "$here/ai-usage-popup.desktop" > "$desktop"
command -v update-desktop-database >/dev/null && update-desktop-database -q "$(dirname "$desktop")" || true

echo "Installed $bin"
if ! command -v ai-usagebar >/dev/null && [[ ! -x "$prefix/bin/ai-usagebar" ]]; then
  echo "Note: ai-usagebar was not found. Install it from https://github.com/akitaonrails/ai-usagebar" >&2
fi
