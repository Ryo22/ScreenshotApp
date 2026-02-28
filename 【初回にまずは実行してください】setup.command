#!/bin/bash
# ============================================
# ScreenshotApp セットアップスクリプト
# ダブルクリックで以下を自動実行:
#   1. Python仮想環境(venv)を作成
#   2. 必要なパッケージをインストール
#   3. ScreenshotApp.app を生成
# ============================================

set -e

# スクリプト自身のディレクトリに移動
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${SCRIPT_DIR}"

APP_NAME="ScreenshotApp"
APP_DIR="${SCRIPT_DIR}/${APP_NAME}.app"
VENV_DIR="${SCRIPT_DIR}/venv"
REQUIREMENTS="${SCRIPT_DIR}/requirements.txt"

echo ""
echo "============================================"
echo "🔧 ${APP_NAME} セットアップ"
echo "============================================"
echo ""

# ─── 1. Python3 確認 ─────────────────────────
echo "📌 Step 1: Python3 を確認..."

if command -v python3 &> /dev/null; then
    SYSTEM_PYTHON="$(command -v python3)"
    echo "   ✅ Python3: ${SYSTEM_PYTHON}"
else
    echo "   ❌ Python3 が見つかりません"
    echo "   Xcode Command Line Tools をインストールしてください:"
    echo "   xcode-select --install"
    echo ""
    read -p "Enter を押して終了..."
    exit 1
fi

# ─── 2. 仮想環境の作成 ───────────────────────
echo ""
echo "📌 Step 2: Python 仮想環境を作成..."

if [ -d "${VENV_DIR}" ]; then
    echo "   既存の venv を検出"
else
    echo "   venv を作成中..."
    python3 -m venv "${VENV_DIR}"
    echo "   ✅ venv 作成完了"
fi

PYTHON_PATH="${VENV_DIR}/bin/python3"
PIP_PATH="${VENV_DIR}/bin/pip3"

# ─── 3. パッケージのインストール ─────────────
echo ""
echo "📌 Step 3: 必要なパッケージをインストール..."

if [ -f "${REQUIREMENTS}" ]; then
    "${PIP_PATH}" install --upgrade pip --quiet 2>/dev/null
    "${PIP_PATH}" install -r "${REQUIREMENTS}" --quiet
    echo "   ✅ パッケージインストール完了"
else
    echo "   ⚠️ requirements.txt が見つかりません"
    echo "   手動でインストールしてください:"
    echo "   ${PIP_PATH} install Pillow pyobjc-framework-Quartz pyobjc-framework-Cocoa"
    "${PIP_PATH}" install Pillow pyobjc-framework-Quartz pyobjc-framework-Cocoa --quiet
    echo "   ✅ パッケージインストール完了"
fi

# ─── 4. 既存の .app を削除 ───────────────────
echo ""
echo "📌 Step 4: ${APP_NAME}.app を作成..."

if [ -d "${APP_DIR}" ]; then
    echo "   既存の ${APP_NAME}.app を削除..."
    rm -rf "${APP_DIR}"
fi

# ─── 5. AppleScript で .app を生成 ──────────
APPLESCRIPT=$(cat << ENDSCRIPT
on run
    tell application "Terminal"
        activate
        do script "cd '${SCRIPT_DIR}' && '${PYTHON_PATH}' '${SCRIPT_DIR}/screen_capture_app.py'"
    end tell
end run
ENDSCRIPT
)

echo "${APPLESCRIPT}" | osacompile -o "${APP_DIR}"
echo "   ✅ アプリバンドル作成完了"

# ─── 6. アイコンを設定 ──────────────────────
ICON_PNG="${SCRIPT_DIR}/app_icon.png"
RESOURCES_DIR="${APP_DIR}/Contents/Resources"

if [ -f "${ICON_PNG}" ]; then
    TMPDIR_ICON=$(mktemp -d)
    CONVERTED_PNG="${TMPDIR_ICON}/icon_source.png"
    sips -s format png "${ICON_PNG}" --out "${CONVERTED_PNG}" > /dev/null 2>&1 || cp "${ICON_PNG}" "${CONVERTED_PNG}"

    ICONSET_DIR="${TMPDIR_ICON}/AppIcon.iconset"
    mkdir -p "${ICONSET_DIR}"

    sips -z 16 16     "${CONVERTED_PNG}" --out "${ICONSET_DIR}/icon_16x16.png"      > /dev/null 2>&1 || true
    sips -z 32 32     "${CONVERTED_PNG}" --out "${ICONSET_DIR}/icon_16x16@2x.png"   > /dev/null 2>&1 || true
    sips -z 32 32     "${CONVERTED_PNG}" --out "${ICONSET_DIR}/icon_32x32.png"      > /dev/null 2>&1 || true
    sips -z 64 64     "${CONVERTED_PNG}" --out "${ICONSET_DIR}/icon_32x32@2x.png"   > /dev/null 2>&1 || true
    sips -z 128 128   "${CONVERTED_PNG}" --out "${ICONSET_DIR}/icon_128x128.png"    > /dev/null 2>&1 || true
    sips -z 256 256   "${CONVERTED_PNG}" --out "${ICONSET_DIR}/icon_128x128@2x.png" > /dev/null 2>&1 || true
    sips -z 256 256   "${CONVERTED_PNG}" --out "${ICONSET_DIR}/icon_256x256.png"    > /dev/null 2>&1 || true
    sips -z 512 512   "${CONVERTED_PNG}" --out "${ICONSET_DIR}/icon_256x256@2x.png" > /dev/null 2>&1 || true
    sips -z 512 512   "${CONVERTED_PNG}" --out "${ICONSET_DIR}/icon_512x512.png"    > /dev/null 2>&1 || true
    sips -z 1024 1024 "${CONVERTED_PNG}" --out "${ICONSET_DIR}/icon_512x512@2x.png" > /dev/null 2>&1 || true

    iconutil -c icns "${ICONSET_DIR}" -o "${RESOURCES_DIR}/applet.icns" 2>/dev/null || true

    if [ -f "${RESOURCES_DIR}/applet.icns" ]; then
        echo "   ✅ アイコン設定完了"
    else
        echo "   ⚠️ ICNS変換に失敗。デフォルトアイコンを使用します"
    fi

    rm -rf "${TMPDIR_ICON}"
else
    echo "   ⚠️ app_icon.png が見つかりません。デフォルトアイコンを使用します"
fi

# ─── 7. quarantine 属性を除去 ───────────────
xattr -cr "${APP_DIR}" 2>/dev/null || true

# ─── 完了 ───────────────────────────────────
echo ""
echo "============================================"
echo "✅ セットアップ完了！"
echo ""
echo "📍 アプリ: ${APP_DIR}"
echo ""
echo "🚀 使い方:"
echo "   • ${APP_NAME}.app をダブルクリックして起動"
echo "   • Dock にドラッグ＆ドロップで追加可能"
echo ""
echo "⚠️ 初回起動時に必要な権限:"
echo "   • 画面収録"
echo "   • アクセシビリティ"
echo "============================================"
echo ""
read -p "Enter を押して終了..."
