#!/bin/bash
# ============================================
# ScreenshotApp .app 作成スクリプト
# ダブルクリックで Terminal 経由で起動するアプリを生成
# ============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="ScreenshotApp"
APP_DIR="${SCRIPT_DIR}/${APP_NAME}.app"

echo "🔧 ${APP_NAME}.app を作成中..."

# 既存の .app を削除
if [ -d "${APP_DIR}" ]; then
    echo "   既存の ${APP_NAME}.app を削除..."
    rm -rf "${APP_DIR}"
fi

# Python3 のパスを検出
if [ -f "${SCRIPT_DIR}/venv/bin/python3" ]; then
    PYTHON_PATH="${SCRIPT_DIR}/venv/bin/python3"
elif [ -f "${SCRIPT_DIR}/.venv/bin/python3" ]; then
    PYTHON_PATH="${SCRIPT_DIR}/.venv/bin/python3"
elif command -v python3 &> /dev/null; then
    PYTHON_PATH="$(command -v python3)"
else
    echo "❌ Python3 が見つかりません"
    exit 1
fi

echo "   Python: ${PYTHON_PATH}"

# AppleScript で Terminal 経由のアプリを生成
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

# アイコンを設定
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

# quarantine 属性を除去
xattr -cr "${APP_DIR}" 2>/dev/null || true

echo ""
echo "============================================"
echo "✅ ${APP_NAME}.app の作成が完了しました！"
echo ""
echo "📍 場所: ${APP_DIR}"
echo ""
echo "🚀 使い方:"
echo "   • Finder でダブルクリックして起動"
echo "   • Dock にドラッグ＆ドロップで追加可能"
echo "============================================"
