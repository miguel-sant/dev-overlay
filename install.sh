#!/bin/sh
# Instala o Overlay Dev: atalho global, entrada no menu de apps e início automático.
#   ./install.sh            instala (atalho padrão: Ctrl+Alt+Espaço)
#   ./install.sh "<Super>o" instala com outro atalho
#   ./install.sh --remove   desinstala
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
SHORTCUT="${1:-<Control><Alt>space}"
KEY_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/overlay-dev/"
SCHEMA="org.gnome.settings-daemon.plugins.media-keys"
APPS="$HOME/.local/share/applications/overlay-dev.desktop"
AUTOSTART="$HOME/.config/autostart/overlay-dev.desktop"

# Adiciona/remove nosso caminho na lista de atalhos personalizados do GNOME,
# preservando os que já existirem.
update_keybinding_list() {
    current="$(gsettings get "$SCHEMA" custom-keybindings)"
    new="$(python3 -c '
import ast, sys
cur = sys.argv[1].removeprefix("@as ")
items = [p for p in ast.literal_eval(cur) if p != sys.argv[2]]
if sys.argv[3] == "add":
    items.append(sys.argv[2])
print(str(items))
' "$current" "$KEY_PATH" "$1")"
    gsettings set "$SCHEMA" custom-keybindings "$new"
}

if [ "$1" = "--remove" ]; then
    pkill -f "$DIR/overlay.py" 2>/dev/null || true
    update_keybinding_list remove
    gsettings reset-recursively "$SCHEMA.custom-keybinding:$KEY_PATH" 2>/dev/null || true
    rm -f "$APPS" "$AUTOSTART"
    echo "Overlay Dev removido."
    exit 0
fi

chmod +x "$DIR/overlay.py" "$DIR/overlay-dev-toggle"
mkdir -p "$(dirname "$APPS")" "$(dirname "$AUTOSTART")"

cat > "$APPS" <<EOF
[Desktop Entry]
Type=Application
Name=Overlay Dev
Comment=Abrir projetos no VS Code rapidamente
Exec="$DIR/overlay-dev-toggle"
Icon=system-search
Terminal=false
Categories=Development;
EOF

cat > "$AUTOSTART" <<EOF
[Desktop Entry]
Type=Application
Name=Overlay Dev
Exec=python3 "$DIR/overlay.py" --hidden
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF

update_keybinding_list add
gsettings set "$SCHEMA.custom-keybinding:$KEY_PATH" name "Overlay Dev"
gsettings set "$SCHEMA.custom-keybinding:$KEY_PATH" command "'$DIR/overlay-dev-toggle'"
gsettings set "$SCHEMA.custom-keybinding:$KEY_PATH" binding "$SHORTCUT"

# Já deixa rodando em segundo plano.
if ! pgrep -f "$DIR/overlay.py" >/dev/null; then
    nohup python3 "$DIR/overlay.py" --hidden >/dev/null 2>&1 &
fi

echo "Overlay Dev instalado. Atalho: $SHORTCUT"
