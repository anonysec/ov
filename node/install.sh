#!/bin/bash
set -e

APP_NAME="ov-node"
INSTALL_DIR="/opt/$APP_NAME"
REPO_URL="https://github.com/anonysec/ov"
# Subfolder inside the anonysec/ov repo that holds this app.
REPO_SUBDIR="node"
PYTHON="/usr/bin/python3"

GREEN="\033[0;32m"
YELLOW="\033[1;33m"
NC="\033[0m"

echo -e "${YELLOW}Updating system...${NC}"
apt update -y
apt install -y python3 python3-full python3-venv wget curl git

echo -e "${YELLOW}Installing uv...${NC}"
wget -qO- https://astral.sh/uv/uv/install.sh | sh

export PATH="$HOME/.local/bin:$PATH"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}uv not found in PATH, trying alternative installation...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# Download repo release
if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${YELLOW}Downloading latest release...${NC}"

    LATEST_URL=$(curl -s https://api.github.com/repos/anonysec/ov/releases/latest \
        | grep "tarball_url" \
        | cut -d '"' -f 4)

    mkdir -p "$INSTALL_DIR"
    cd /tmp

    wget -O latest.tar.gz "$LATEST_URL"

    echo -e "${YELLOW}Extracting...${NC}"
    # Release tarball is the whole anonysec/ov repo; extract only this app's
    # subfolder into INSTALL_DIR (strip wrapper dir + subfolder name).
    tar -xzf latest.tar.gz -C "$INSTALL_DIR" --strip-components=2 \
        --wildcards "*/${REPO_SUBDIR}/*"
    rm -f latest.tar.gz
else
    echo -e "${GREEN}Directory exists, skipping download.${NC}"
fi

cd "$INSTALL_DIR"

echo -e "${YELLOW}Installing dependencies...${NC}"
uv sync

uv run python installer.py