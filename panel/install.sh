#!/bin/bash
set -e

APP_NAME="ov-panel"
INSTALL_DIR="/opt/$APP_NAME"
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

echo -e "${YELLOW}Downloading latest release...${NC}"

LATEST_URL=$(curl -s https://api.github.com/repos/anonysec/ov/releases/latest \
    | grep "tarball_url" | cut -d '"' -f 4)

if [ -z "$LATEST_URL" ]; then
    echo -e "${YELLOW}Could not fetch latest release. Falling back to main branch...${NC}"
    LATEST_URL="https://github.com/anonysec/ov/archive/refs/heads/main.tar.gz"
fi

# Remove old installation if it exists
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}Removing old installation...${NC}"
    rm -rf "$INSTALL_DIR"
fi

mkdir -p "$INSTALL_DIR"
cd /tmp

wget -O latest.tar.gz "$LATEST_URL" 2>/dev/null || \
curl -L -o latest.tar.gz "$LATEST_URL"

echo -e "${YELLOW}Extracting...${NC}"

rm -rf /tmp/ov-extract
mkdir -p /tmp/ov-extract
tar -xzf latest.tar.gz -C /tmp/ov-extract

# Find the extracted root directory
EXTRACTED_DIR=$(find /tmp/ov-extract -maxdepth 1 -type d ! -path /tmp/ov-extract | head -1)

if [ -d "$EXTRACTED_DIR/${REPO_SUBDIR}" ]; then
    cp -a "$EXTRACTED_DIR/${REPO_SUBDIR}"/. "$INSTALL_DIR"/
else
    cp -a "$EXTRACTED_DIR"/* "$INSTALL_DIR"/ 2>/dev/null || true
fi

rm -rf /tmp/ov-extract latest.tar.gz

cd "$INSTALL_DIR"

echo -e "${YELLOW}Installing dependencies...${NC}"
uv sync

# Node.js (needed for frontend)
echo -e "${YELLOW}Installing NodeJS...${NC}"
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs build-essential

echo -e "${YELLOW}Launching installer...${NC}"

uv run python installer.py