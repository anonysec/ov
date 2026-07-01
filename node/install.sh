#!/bin/bash
set -e

APP_NAME="ov-node"
INSTALL_DIR="/opt/$APP_NAME"
REPO_SUBDIR="node"

GREEN="\033[0;32m"
YELLOW="\033[1;33m"
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

# Robust extraction: release tarball structure is <wrapper>/node/...
# Always find the single top-level wrapper dir
WRAPPER_DIR=$(find /tmp/ov-extract -mindepth 1 -maxdepth 1 -type d | head -1)

if [ -n "$WRAPPER_DIR" ] && [ -d "$WRAPPER_DIR/$REPO_SUBDIR" ]; then
    echo -e "${YELLOW}Found wrapper: $(basename $WRAPPER_DIR), copying $REPO_SUBDIR/...${NC}"
    cp -a "$WRAPPER_DIR/$REPO_SUBDIR"/. "$INSTALL_DIR"/
else
    # Fallbacks for unusual tarballs
    NODE_DIR=$(find /tmp/ov-extract -type d -name "$REPO_SUBDIR" 2>/dev/null | head -1)
    if [ -n "$NODE_DIR" ]; then
        cp -a "$NODE_DIR"/. "$INSTALL_DIR"/
    else
        EXTRACTED_DIR=$(find /tmp/ov-extract -mindepth 1 -maxdepth 1 -type d | head -1)
        cp -a "$EXTRACTED_DIR"/* "$INSTALL_DIR"/ 2>/dev/null || true
    fi
fi

# Explicitly locate and copy .env.example from node/ subdir inside tarball
ENV_EXAMPLE=$(find /tmp/ov-extract -type f -path "*/$REPO_SUBDIR/.env.example" 2>/dev/null | head -1)
if [ -n "$ENV_EXAMPLE" ]; then
    cp -f "$ENV_EXAMPLE" "$INSTALL_DIR/.env.example" 2>/dev/null || true
    echo -e "${YELLOW}Copied .env.example from release tarball${NC}"
fi

# Final verification
if [ ! -f "$INSTALL_DIR/.env.example" ]; then
    if [ -n "$WRAPPER_DIR" ] && [ -f "$WRAPPER_DIR/$REPO_SUBDIR/.env.example" ]; then
        cp -f "$WRAPPER_DIR/$REPO_SUBDIR/.env.example" "$INSTALL_DIR/.env.example"
    fi
fi

if [ ! -f "$INSTALL_DIR/.env.example" ]; then
    echo -e "${YELLOW}Warning: .env.example still missing after extraction (installer.py has fallback)${NC}"
fi

rm -rf /tmp/ov-extract latest.tar.gz

cd "$INSTALL_DIR"

echo -e "${YELLOW}Installing dependencies...${NC}"
uv sync

uv run python installer.py