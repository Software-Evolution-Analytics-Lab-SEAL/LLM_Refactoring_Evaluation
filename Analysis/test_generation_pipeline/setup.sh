#!/bin/bash
# ============================================================
# Test Generation Pipeline – Setup
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TOOLS_DIR="${SCRIPT_DIR}/../tools"

echo "========================================"
echo " Test Generation Pipeline – Setup"
echo "========================================"

mkdir -p "$TOOLS_DIR"

# ---- Randoop ----
if [ -f "$TOOLS_DIR/randoop-all-4.3.2.jar" ]; then
    echo "✓ Randoop 4.3.2 found"
else
    echo "→ Downloading Randoop 4.3.2 ..."
    curl -L "https://github.com/randoop/randoop/releases/download/v4.3.2/randoop-all-4.3.2.jar" \
        -o "$TOOLS_DIR/randoop-all-4.3.2.jar"
    echo "✓ Randoop downloaded"
fi

# ---- EvoSuite ----
if [ -f "$TOOLS_DIR/evosuite-1.2.0.jar" ]; then
    echo "✓ EvoSuite 1.2.0 found"
else
    echo "→ Downloading EvoSuite 1.2.0 ..."
    curl -L "https://github.com/EvoSuite/evosuite/releases/download/v1.2.0/evosuite-1.2.0.jar" \
        -o "$TOOLS_DIR/evosuite-1.2.0.jar"
    echo "✓ EvoSuite downloaded"
fi

# ---- JDK 8 ----
if [ -d "$TOOLS_DIR/jdk8" ]; then
    echo "✓ JDK 8 found"
else
    echo "→ Installing JDK 8 via Zulu ..."
    ARCH=$(uname -m)
    if [ "$ARCH" = "x86_64" ]; then
        JDK_URL="https://cdn.azul.com/zulu/bin/zulu8.78.0.19-ca-jdk8.0.412-linux_x64.tar.gz"
    else
        JDK_URL="https://cdn.azul.com/zulu/bin/zulu8.78.0.19-ca-jdk8.0.412-linux_aarch64.tar.gz"
    fi
    curl -L "$JDK_URL" -o /tmp/jdk8.tar.gz
    mkdir -p "$TOOLS_DIR/jdk8"
    tar xzf /tmp/jdk8.tar.gz -C "$TOOLS_DIR/jdk8" --strip-components=1
    rm /tmp/jdk8.tar.gz
    echo "✓ JDK 8 installed"
fi

# ---- Maven ----
if [ -d "$TOOLS_DIR/apache-maven-3.6.3" ]; then
    echo "✓ Maven 3.6.3 found"
else
    echo "→ Installing Maven 3.6.3 ..."
    curl -L "https://archive.apache.org/dist/maven/maven-3/3.6.3/binaries/apache-maven-3.6.3-bin.tar.gz" \
        -o /tmp/maven.tar.gz
    tar xzf /tmp/maven.tar.gz -C "$TOOLS_DIR"
    rm /tmp/maven.tar.gz
    echo "✓ Maven 3.6.3 installed"
fi

echo ""
echo "Setup complete."
echo "Run:  python3 run_pipeline.py --dataset ../dataset.jsonl"
