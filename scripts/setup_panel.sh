#!/usr/bin/env bash
set -euo pipefail

WORKDIR="/root/MKP"
VENV_DIR="$WORKDIR/.venv"
REQUIREMENTS="$WORKDIR/requirements.txt"
SERVICE_FILE="/etc/systemd/system/mkp-panel.service"
SUDOERS_FILE="/etc/sudoers.d/mkp-panel"
DEFAULT_USER="sysadmin"
DEFAULT_PORT="9000"
DEFAULT_BASIC_USER="panel"
PBKDF_ITER="600000"

usage() {
  cat <<USAGE
Uso: sudo bash scripts/setup_panel.sh [usuario_panel] [puerto] [usuario_web] [password_web]
 - usuario_panel: usuario del sistema que ejecutará el panel (default: ${DEFAULT_USER})
 - puerto: puerto TCP del panel (default: ${DEFAULT_PORT})
 - usuario_web: usuario para autenticación básica (default: ${DEFAULT_BASIC_USER})
 - password_web: contraseña en texto plano (se solicitará si se omite)
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

PANEL_USER="${1:-$DEFAULT_USER}"
PANEL_PORT="${2:-$DEFAULT_PORT}"
BASIC_USER="${3:-$DEFAULT_BASIC_USER}"
BASIC_PASS="${4:-}"

if [[ "$EUID" -ne 0 ]]; then
  echo "Este script debe ejecutarse como root" >&2
  exit 1
fi

if ! id "$PANEL_USER" >/dev/null 2>&1; then
  echo "El usuario $PANEL_USER no existe" >&2
  exit 1
fi

if [[ ! -d "$WORKDIR" ]]; then
  echo "No se encontró $WORKDIR" >&2
  exit 1
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "No se encontró entorno virtual en $VENV_DIR" >&2
  exit 1
fi

if [[ -z "$BASIC_PASS" ]]; then
  read -s -p "Contraseña para el usuario web '$BASIC_USER': " BASIC_PASS
  echo
fi

if [[ -z "$BASIC_PASS" ]]; then
  echo "La contraseña web no puede estar vacía" >&2
  exit 1
fi

if [[ ${#BASIC_PASS} -lt 6 ]]; then
  echo "La contraseña debe tener al menos 6 caracteres" >&2
  exit 1
fi

require_cmd() {
  local cmd=$1
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Falta el comando $cmd" >&2
    exit 1
  fi
}

require_cmd setfacl
require_cmd visudo
require_cmd systemctl

# 1. Instalar dependencias del panel
"$VENV_DIR/bin/pip" install -r "$REQUIREMENTS"

# 2. ACLs para que PANEL_USER acceda y modifique /root/MKP
setfacl -m u:"$PANEL_USER":x /root
setfacl -R -m u:"$PANEL_USER":rwX "$WORKDIR"
setfacl -dR -m u:"$PANEL_USER":rwX "$WORKDIR"

# 3. Sudoers específico para operaciones necesarias
cat <<EOF_SUDOER > "$SUDOERS_FILE"
Cmnd_Alias MKP_SYSTEMCTL = /usr/bin/systemctl status *, \
    /usr/bin/systemctl restart *, \
    /usr/bin/systemctl show *
Cmnd_Alias MKP_PRINT = /usr/sbin/lpadmin, /usr/bin/lpoptions
Cmnd_Alias MKP_LPSTAT = /usr/bin/lpstat
$PANEL_USER ALL=(ALL) NOPASSWD: MKP_SYSTEMCTL, MKP_PRINT, MKP_LPSTAT
EOF_SUDOER
chmod 440 "$SUDOERS_FILE"
visudo -cf "$SUDOERS_FILE" >/dev/null

# 3.1 Generar hash PBKDF2 para Basic Auth
SALT=$(python3 - <<'PY'
import secrets
print(secrets.token_hex(16))
PY
)

BASIC_HASH=$(MKP_PLAIN_PASS="$BASIC_PASS" MKP_PLAIN_SALT="$SALT" MKP_PBKDF="$PBKDF_ITER" python3 - <<'PY'
import hashlib, os
password = os.environ['MKP_PLAIN_PASS']
salt = bytes.fromhex(os.environ['MKP_PLAIN_SALT'])
iterations = int(os.environ['MKP_PBKDF'])
derived = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations)
print(derived.hex())
PY
)

BASIC_SECRET="${PBKDF_ITER}:${SALT}:${BASIC_HASH}"

# 4. Unidad systemd para el panel
cat <<EOF_SERVICE > "$SERVICE_FILE"
[Unit]
Description=MKP Web Panel
After=network.target

[Service]
User=$PANEL_USER
Group=$PANEL_USER
WorkingDirectory=$WORKDIR
Environment=PATH=$VENV_DIR/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=MKP_SUDO_BIN=/usr/bin/sudo
Environment=MKP_SYSTEM_PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=MKP_BASIC_USER=$BASIC_USER
Environment=MKP_BASIC_PASSWORD_HASH=$BASIC_SECRET
Environment=MKP_BASIC_PBKDF_ITER=$PBKDF_ITER
ExecStart=$VENV_DIR/bin/uvicorn webapp.app:app --host 0.0.0.0 --port $PANEL_PORT
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF_SERVICE

chmod 644 "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable --now mkp-panel.service

systemctl status --no-pager mkp-panel.service

echo "Panel listo en http://<servidor>:$PANEL_PORT"
