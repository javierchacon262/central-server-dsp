#!/usr/bin/env bash
# Prepara la VM de Oracle Cloud (Ubuntu 24.04, VM.Standard.E2.1.Micro) y levanta el
# central detrás de Caddy (D08, D09, CS-002 §11). Se puede correr varias veces.
#
#   ssh ubuntu@IP 'bash -s' < despliegue/preparar-vm.sh            # rama main
#   ssh ubuntu@IP 'RAMA=feat/central bash -s' < despliegue/preparar-vm.sh
#
# El token de administración se lee de la entrada ADMIN_TOKEN del entorno, solo la
# primera vez, y queda en /opt/central-server-dsp/.env con permisos 600. Nunca se
# imprime.
set -euo pipefail

REPO="https://github.com/javierchacon262/central-server-dsp.git"
RAMA="${RAMA:-main}"
DIR="/opt/central-server-dsp"
DOMINIO="${DOMINIO:-dsp.cshire.io}"

paso() { printf '\n==> %s\n' "$*"; }

paso "Swap de 2 GB (la VM tiene 1 GB de RAM y construye la imagen)"
if ! swapon --show=NAME --noheadings | grep -qx /swapfile; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
fi
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
swapon --show

paso "iptables: abrir 80 y 443 antes del REJECT de la imagen de Oracle"
for puerto in 80 443; do
  if ! sudo iptables -C INPUT -p tcp -m state --state NEW --dport "$puerto" -j ACCEPT 2>/dev/null; then
    linea=$(sudo iptables -L INPUT --line-numbers -n | awk '$2 == "REJECT" {print $1; exit}')
    if [ -n "$linea" ]; then
      sudo iptables -I INPUT "$linea" -p tcp -m state --state NEW --dport "$puerto" -j ACCEPT
    else
      sudo iptables -A INPUT -p tcp -m state --state NEW --dport "$puerto" -j ACCEPT
    fi
  fi
done
if command -v netfilter-persistent >/dev/null; then
  sudo netfilter-persistent save >/dev/null
fi
sudo iptables -L INPUT -n --line-numbers | sed -n '1,12p'

paso "Docker Engine y el plugin de compose (repositorio oficial de Docker)"
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq ca-certificates curl git >/dev/null
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin >/dev/null
fi
sudo usermod -aG docker "$USER"
sudo docker --version
sudo docker compose version

paso "Código: $REPO, rama $RAMA, en $DIR"
if [ ! -d "$DIR/.git" ]; then
  sudo mkdir -p "$DIR"
  sudo chown "$USER":"$USER" "$DIR"
  git clone -q "$REPO" "$DIR"
fi
git -C "$DIR" fetch -q origin
git -C "$DIR" checkout -q -B "$RAMA" "origin/$RAMA"
git -C "$DIR" log --oneline -1

paso "Configuración en $DIR/.env (600)"
if [ ! -f "$DIR/.env" ]; then
  if [ -z "${ADMIN_TOKEN:-}" ]; then
    echo "Falta ADMIN_TOKEN en el entorno para crear .env la primera vez." >&2
    exit 1
  fi
  umask 077
  cat > "$DIR/.env" <<CONF
ADMIN_TOKEN=${ADMIN_TOKEN}
PUBLICAR=127.0.0.1:9000
DOMINIO=${DOMINIO}
PERMITIR_URL_PRIVADAS=false
CONF
fi
chmod 600 "$DIR/.env"
grep -v '^ADMIN_TOKEN=' "$DIR/.env"
echo "ADMIN_TOKEN=(oculto, $(grep -c '^ADMIN_TOKEN=.\+' "$DIR/.env") definido)"

paso "Central y Caddy"
cd "$DIR"
sudo docker compose --profile nube up -d --build
sudo docker compose ps
