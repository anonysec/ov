#!/bin/bash
set -e

APP_NAME="ov-panel"
INSTALL_DIR="/opt/$APP_NAME"
REPO_URL="https://github.com/anonysec/ov"
# Subfolder inside the anonysec/ov repo that holds this app.
REPO_SUBDIR="panel"

GREEN="\033[0;32m"
YELLOW="\033[1;33m"
CYAN="\033[0;36m"
BLUE="\033[0;34m"
NC="\033[0m"

echo -e "${YELLOW}Updating system...${NC}"
apt update -y
apt install -y python3 python3-full python3-venv wget curl git ca-certificates

echo -e "${YELLOW}Installing uv...${NC}"
wget -qO- https://astral.sh/uv/uv/install.sh | sh

export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}uv not found in PATH, trying alternative installation...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Always download the latest code from the main branch.
# This fixes the problem where bash <(curl -s https://raw.githubusercontent.com/anonysec/ov/main/panel/install.sh)
# was serving old installer.py / old menus.
echo -e "${YELLOW}Downloading latest code from main branch...${NC}"

TARBALL_URL="https://github.com/anonysec/ov/archive/refs/heads/main.tar.gz"

# Remove old install dir contents if it exists, so one-liner always gives fresh installer.py
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}Removing old installation to get fresh code...${NC}"
    rm -rf "$INSTALL_DIR"
fi

mkdir -p "$INSTALL_DIR"
cd /tmp

wget --no-check-certificate -O ov-main.tar.gz "$TARBALL_URL" || curl -L --insecure -o ov-main.tar.gz "$TARBALL_URL"
echo -e "${YELLOW}Extracting fresh code...${NC}"

# ov-main/ + panel/  → strip 2 levels
tar -xzf ov-main.tar.gz -C "$INSTALL_DIR" --strip-components=2 \
    --wildcards "*/${REPO_SUBDIR}/*" 2>/dev/null || true
rm -f ov-main.tar.gz 2>/dev/null || true

cd "$INSTALL_DIR"

echo -e "${YELLOW}Installing dependencies...${NC}"
uv sync

# Node.js (needed for frontend)
echo -e "${YELLOW}Installing NodeJS...${NC}"
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs build-essential

echo -e "${YELLOW}Installing Python dependencies...${NC}"

uv run python installer.py