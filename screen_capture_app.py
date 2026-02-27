#!/usr/bin/env python3
"""
ScreenshotApp
macOS用 ウィンドウ指定スクリーンショットアプリ

特定のウィンドウを指定して、最前面でなくてもキャプチャ可能。
ショートカット: Cmd+Ctrl+S で手動撮影

使用前に以下の権限を付与してください：
- 画面収録
- アクセシビリティ
"""

import os
import sys
import json
import time
import tempfile
import subprocess
import threading
import webbrowser
import urllib.parse
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Tuple
from io import BytesIO

try:
    from PIL import Image, ImageChops
    from Quartz import (
        CGWindowListCopyWindowInfo,
        CGWindowListCreateImage,
        CGRectNull,
        kCGWindowListOptionIncludingWindow,
        kCGWindowListOptionAll,
        kCGWindowListExcludeDesktopElements,
        kCGWindowImageDefault,
        kCGWindowImageBoundsIgnoreFraming,
        kCGWindowImageNominalResolution,
        kCGNullWindowID,
        CGImageGetWidth, CGImageGetHeight,
        CGImageGetBytesPerRow, CGImageGetDataProvider,
        CGDataProviderCopyData,
        CGEventCreate, CGEventGetLocation,
        CGEventTapCreate, CGEventGetIntegerValueField,
        CGEventGetFlags, CGEventTapEnable,
        kCGSessionEventTap, kCGHeadInsertEventTap,
        kCGEventKeyDown, kCGKeyboardEventKeycode,
        kCGEventFlagMaskCommand, kCGEventFlagMaskControl,
        CFMachPortCreateRunLoopSource, CFRunLoopGetCurrent,
        CFRunLoopAddSource, CFRunLoopRun, kCFRunLoopCommonModes
    )
    from AppKit import NSPasteboard, NSPasteboardTypePNG
except ImportError as e:
    print(f"必要なパッケージがインストールされていません: {e}")
    print("  pip3 install Pillow pyobjc-framework-Quartz pyobjc-framework-Cocoa")
    sys.exit(1)


# ─── State ───────────────────────────────────────

class AppState:
    capture_mode: str = "window"  # "window" or "region"
    target_window_id: Optional[int] = None
    target_window_name: str = ""
    target_owner_name: str = ""
    region: Optional[Tuple[int, int, int, int]] = None
    retina_scale: int = 2
    save_dir: Path = Path.home() / "Desktop" / "screenshots"
    save_mode: str = "folder"  # "folder", "clipboard", "both"
    is_running: bool = False
    capture_count: int = 0
    mode: str = "manual"
    last_image: Optional[Image.Image] = None
    change_detected_time: Optional[float] = None
    auto_thread: Optional[threading.Thread] = None
    status: str = "停止中"
    settling_time: float = 0.5
    polling_interval: float = 0.2

state = AppState()

DIFF_THRESHOLD = 0.5
PORT = 8765
SHORTCUT_KEYCODE = 1  # S key


# ─── Window Functions ────────────────────────────

def get_window_list():
    """実行中のウィンドウ一覧を取得（デスクトップ要素除外）"""
    options = kCGWindowListOptionAll | kCGWindowListExcludeDesktopElements
    window_list = CGWindowListCopyWindowInfo(options, kCGNullWindowID)

    windows = []
    seen = set()
    for w in window_list:
        owner = w.get('kCGWindowOwnerName', '')
        name = w.get('kCGWindowName', '')
        wid = w.get('kCGWindowNumber', 0)
        layer = w.get('kCGWindowLayer', 0)
        bounds = w.get('kCGWindowBounds', {})
        width = int(bounds.get('Width', 0))
        height = int(bounds.get('Height', 0))

        # フィルタ: 小さすぎる、レイヤーが特殊、名前なしを除外
        if width < 50 or height < 50:
            continue
        if layer != 0:
            continue
        if not owner:
            continue

        # 重複排除キー
        key = (owner, name, width, height)
        if key in seen:
            continue
        seen.add(key)

        display_name = f"{owner}"
        if name:
            display_name += f" - {name}"
        display_name += f" ({width}×{height})"

        windows.append({
            'id': wid,
            'owner': owner,
            'name': name or '',
            'width': width,
            'height': height,
            'display': display_name,
        })

    return windows


def cgimage_to_pil(cg_image) -> Optional[Image.Image]:
    """CGImageRef を PIL Image に変換"""
    if cg_image is None:
        return None
    try:
        width = CGImageGetWidth(cg_image)
        height = CGImageGetHeight(cg_image)
        bytes_per_row = CGImageGetBytesPerRow(cg_image)

        provider = CGImageGetDataProvider(cg_image)
        data = CGDataProviderCopyData(provider)

        img = Image.frombytes('RGBA', (width, height), bytes(data),
                              'raw', 'BGRA', bytes_per_row, 1)
        return img.convert('RGB')
    except Exception as e:
        print(f"CGImage→PIL変換エラー: {e}")
        return None


def capture_window(window_id: int) -> Optional[Image.Image]:
    """指定ウィンドウをキャプチャ（最前面でなくてもOK）"""
    try:
        cg_image = CGWindowListCreateImage(
            CGRectNull,
            kCGWindowListOptionIncludingWindow,
            window_id,
            kCGWindowImageBoundsIgnoreFraming | kCGWindowImageNominalResolution
        )
        return cgimage_to_pil(cg_image)
    except Exception as e:
        print(f"ウィンドウキャプチャエラー: {e}")
        return None


def capture_window_thumbnail(window_id: int, max_width: int = 400) -> Optional[bytes]:
    """サムネイル用にリサイズしたPNG bytesを返す"""
    img = capture_window(window_id)
    if img is None:
        return None
    ratio = max_width / img.width
    new_size = (max_width, int(img.height * ratio))
    img = img.resize(new_size, Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


# ─── Region Functions ────────────────────────────

def detect_retina_scale() -> int:
    try:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            tmp_path = tmp.name
        subprocess.run(['screencapture', '-R', '0,0,10,10', '-x', tmp_path],
                       capture_output=True, timeout=5)
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            img = Image.open(tmp_path)
            scale = max(1, img.width // 10)
            img.close()
            os.remove(tmp_path)
            return scale
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except:
        pass
    return 2


def interactive_select_region():
    """screencapture -i -s でドラッグ選択し、マウス追跡で座標も取得"""
    positions = []
    monitoring = {'active': True}

    def monitor_mouse():
        while monitoring['active']:
            try:
                event = CGEventCreate(None)
                pos = CGEventGetLocation(event)
                positions.append((int(pos.x), int(pos.y)))
            except:
                pass
            time.sleep(0.016)

    monitor_thread = threading.Thread(target=monitor_mouse, daemon=True)
    monitor_thread.start()

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        tmp_path = tmp.name
    subprocess.run(['screencapture', '-i', '-s', tmp_path], capture_output=True)

    monitoring['active'] = False
    monitor_thread.join(timeout=1)

    if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
        img = Image.open(tmp_path)
        cap_w, cap_h = img.size
        img.close()
        os.remove(tmp_path)

        scale = state.retina_scale
        w = cap_w // scale
        h = cap_h // scale

        if len(positions) >= 2:
            last_x, last_y = positions[-1]
            x = last_x - w
            y = last_y - h
            state.region = (max(0, x), max(0, y), w, h)
        else:
            state.region = (100, 100, w, h)

        state.capture_mode = "region"
        state.status = f"領域: {state.region[0]},{state.region[1]} {w}x{h}"
        print(f"✅ 領域選択: {state.region}")
        return True
    else:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False


def capture_region() -> Optional[Image.Image]:
    """screencaptureコマンドで画面領域をキャプチャ"""
    if not state.region:
        return None
    try:
        x, y, w, h = state.region
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            tmp_path = tmp.name
        subprocess.run(['screencapture', '-R', f'{x},{y},{w},{h}', '-x', tmp_path],
                       capture_output=True, timeout=5)
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            img = Image.open(tmp_path)
            img.load()
            os.remove(tmp_path)
            return img
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except Exception as e:
        print(f"領域キャプチャエラー: {e}")
    return None


# ─── Core Functions ──────────────────────────────

def init_capture_count():
    state.capture_count = 0
    if not state.save_dir.exists():
        return
    for f in state.save_dir.glob("slide_*.png"):
        try:
            num = int(f.stem.split("_")[1])
            state.capture_count = max(state.capture_count, num)
        except:
            pass


def images_different(img1: Image.Image, img2: Image.Image) -> bool:
    if img1.size != img2.size:
        return True
    diff = ImageChops.difference(img1, img2)
    histogram = diff.histogram()
    non_zero = sum(histogram[i] for i in range(1, 256))
    return (non_zero / (img1.width * img1.height * 3)) * 100 > DIFF_THRESHOLD


def play_sound():
    os.system('killall afplay 2>/dev/null; afplay /System/Library/Sounds/Pop.aiff &')


def copy_to_clipboard(image: Image.Image):
    """PIL ImageをmacOSクリップボードにPNGとしてコピー"""
    try:
        buf = BytesIO()
        image.save(buf, 'PNG')
        png_data = buf.getvalue()

        from Foundation import NSData
        ns_data = NSData.dataWithBytes_length_(png_data, len(png_data))
        pasteboard = NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setData_forType_(ns_data, NSPasteboardTypePNG)
        return True
    except Exception as e:
        print(f"クリップボードコピーエラー: {e}")
        return False


def save_image(image: Image.Image):
    state.capture_count += 1
    filename = f"slide_{state.capture_count:04d}.png"
    status_parts = []

    try:
        # フォルダに保存
        if state.save_mode in ("folder", "both"):
            filepath = state.save_dir / filename
            image.save(filepath, "PNG")
            status_parts.append(f"📁 {filename}")
            print(f"📸 {filename} ({state.capture_count}枚目)")

        # クリップボードにコピー
        if state.save_mode in ("clipboard", "both"):
            if copy_to_clipboard(image):
                status_parts.append("📋 コピー済")
                print(f"📋 クリップボードにコピー")
            else:
                status_parts.append("❌ コピー失敗")

        threading.Thread(target=play_sound, daemon=True).start()
        state.status = "✓ " + " / ".join(status_parts) if status_parts else f"✓ {filename}"
    except Exception as e:
        print(f"保存エラー: {e}")


def do_capture() -> Optional[Image.Image]:
    """現在のキャプチャモードに応じてキャプチャ"""
    if state.capture_mode == "window" and state.target_window_id:
        return capture_window(state.target_window_id)
    elif state.capture_mode == "region" and state.region:
        return capture_region()
    return None


def manual_capture():
    if not state.is_running:
        state.status = "❌ 開始してください"
        return False
    if state.capture_mode == "window" and not state.target_window_id:
        state.status = "❌ ウィンドウ未選択"
        return False
    if state.capture_mode == "region" and not state.region:
        state.status = "❌ 領域未設定"
        return False
    image = do_capture()
    if image:
        save_image(image)
        return True
    state.status = "❌ キャプチャ失敗"
    return False


def auto_monitor_loop():
    while state.is_running and state.mode == "auto":
        try:
            current_image = do_capture()
            if current_image is None:
                time.sleep(1)
                continue
            if state.last_image:
                if images_different(state.last_image, current_image):
                    state.change_detected_time = time.time()
                    state.status = "🔍 変化検知..."
                elif state.change_detected_time:
                    if time.time() - state.change_detected_time >= state.settling_time:
                        save_image(current_image)
                        state.change_detected_time = None
            state.last_image = current_image
        except Exception as e:
            print(f"自動監視エラー: {e}")
        time.sleep(state.polling_interval)


def start_capture():
    if state.capture_mode == "window" and not state.target_window_id:
        state.status = "❌ ウィンドウを選択してください"
        return False
    if state.capture_mode == "region" and not state.region:
        state.status = "❌ 領域を選択してください"
        return False
    state.is_running = True
    state.save_dir.mkdir(parents=True, exist_ok=True)
    target_desc = state.target_owner_name if state.capture_mode == "window" else f"{state.region[2]}x{state.region[3]}"
    if state.mode == "manual":
        state.status = "🖱 Cmd+Ctrl+S で撮影"
        print(f"手動モード開始 - {target_desc}")
    else:
        state.last_image = None
        state.change_detected_time = None
        state.auto_thread = threading.Thread(target=auto_monitor_loop, daemon=True)
        state.auto_thread.start()
        state.status = "🔄 監視中"
        print(f"自動モード開始 - {target_desc}")
    return True


def stop_capture():
    state.is_running = False
    state.status = "停止中"
    print(f"停止: {state.capture_count}枚保存")


# ─── Keyboard ────────────────────────────────────

def keyboard_callback(proxy, event_type, event, refcon):
    if event_type == kCGEventKeyDown:
        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        flags = CGEventGetFlags(event)
        cmd_pressed = (flags & kCGEventFlagMaskCommand) != 0
        ctrl_pressed = (flags & kCGEventFlagMaskControl) != 0
        if cmd_pressed and ctrl_pressed and keycode == SHORTCUT_KEYCODE:
            threading.Thread(target=manual_capture, daemon=True).start()
    return event


def start_keyboard_listener():
    tap = CGEventTapCreate(
        kCGSessionEventTap, kCGHeadInsertEventTap, 0,
        1 << kCGEventKeyDown, keyboard_callback, None
    )
    if tap is None:
        print("⚠️ キーボードイベントのタップに失敗")
        print("   アクセシビリティ権限を確認してください")
        return False
    source = CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes)
    CGEventTapEnable(tap, True)
    print("✅ キーボードショートカット有効: Cmd+Ctrl+S")
    CFRunLoopRun()
    return True


# ─── HTML ────────────────────────────────────────

HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ScreenshotApp</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
            color: #fff; min-height: 100vh; padding: 15px;
        }
        .container { max-width: 480px; margin: 0 auto; }
        h1 { text-align: center; margin-bottom: 15px; font-size: 1.3em; }
        .card {
            background: rgba(255,255,255,0.08); border-radius: 12px;
            padding: 14px; margin-bottom: 10px;
            border: 1px solid rgba(255,255,255,0.06);
        }
        .card h2 { font-size: 0.8em; color: #888; margin-bottom: 8px; }
        .card small { color: #666; font-size: 0.75em; }
        .info {
            background: rgba(33,150,243,0.15); padding: 10px;
            border-radius: 8px; font-size: 0.9em; margin-bottom: 12px; text-align: center;
        }
        .info kbd {
            background: rgba(255,255,255,0.2); padding: 3px 8px;
            border-radius: 4px; font-family: monospace; font-size: 1.1em;
        }
        select, input[type="text"], input[type="number"] {
            width: 100%; padding: 10px; border: none; border-radius: 8px;
            background: rgba(255,255,255,0.1); color: #fff;
            font-size: 0.9em; margin-bottom: 6px;
            appearance: auto; -webkit-appearance: auto;
        }
        select option { background: #2a2a3e; color: #fff; }
        .row { display: flex; gap: 6px; }
        .row input, .row select { flex: 1; }
        .mode-btns { display: flex; gap: 6px; }
        .mode-btn {
            flex: 1; padding: 10px; border: 2px solid #444;
            border-radius: 8px; background: transparent; color: #fff;
            cursor: pointer; font-size: 0.85em; transition: all 0.2s;
        }
        .mode-btn.active { border-color: #7c4dff; background: rgba(124,77,255,0.2); }
        .mode-btn:hover { border-color: #7c4dff; }
        .main-btn {
            width: 100%; padding: 14px; border: none; border-radius: 10px;
            font-size: 1.1em; cursor: pointer; font-weight: bold; margin-bottom: 8px;
            transition: transform 0.1s;
        }
        .main-btn:active { transform: scale(0.98); }
        .start-btn { background: linear-gradient(135deg, #7c4dff, #448aff); color: #fff; }
        .stop-btn { background: rgba(255,255,255,0.12); border: 1px solid rgba(255,82,82,0.4); color: #ff8a80; }
        .status {
            text-align: center; padding: 12px;
            background: rgba(0,0,0,0.3); border-radius: 8px;
        }
        .count { font-size: 1.8em; font-weight: bold; color: #7c4dff; }
        .footer { display: flex; gap: 6px; margin-top: 8px; }
        .footer button {
            flex: 1; padding: 8px; border: 1px solid rgba(255,255,255,0.15); border-radius: 8px;
            background: rgba(255,255,255,0.05); color: #aaa; cursor: pointer; font-size: 0.85em;
            transition: all 0.2s;
        }
        .footer button:hover { background: rgba(255,255,255,0.1); color: #fff; }
        .select-btn {
            width: 100%; padding: 8px; margin-top: 6px;
            border: 1px dashed rgba(255,255,255,0.2); border-radius: 8px;
            background: rgba(124,77,255,0.1); color: #aaa;
            cursor: pointer; font-size: 0.85em; transition: all 0.2s;
        }
        .select-btn:hover { background: rgba(124,77,255,0.2); color: #fff; }
        .thumbnail {
            width: 100%; border-radius: 8px; margin-top: 8px;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .target-info {
            background: rgba(124,77,255,0.15); padding: 8px 12px;
            border-radius: 8px; font-size: 0.85em; margin-bottom: 8px;
            display: flex; align-items: center; gap: 8px;
        }
        .target-info .dot { width: 8px; height: 8px; border-radius: 50%; background: #7c4dff; }
        .capture-mode-btns { display: flex; gap: 6px; margin-bottom: 10px; }
        .capture-mode-btn {
            flex: 1; padding: 10px; border: 2px solid #444;
            border-radius: 8px; background: transparent; color: #fff;
            cursor: pointer; font-size: 0.85em; transition: all 0.2s;
        }
        .capture-mode-btn.active { border-color: #00bcd4; background: rgba(0,188,212,0.15); }
    </style>
</head>
<body>
    <div class="container">
        <h1>📷 ScreenshotApp</h1>

        <div class="info" style="{{manual_info_display}}">
            ⌨️ 手動撮影: <kbd>Cmd</kbd> + <kbd>Ctrl</kbd> + <kbd>S</kbd>
        </div>

        <div class="target-info" style="{{target_display}}">
            <span class="dot"></span>
            <span>{{target_name}}</span>
        </div>

        <div class="capture-mode-btns">
            <button class="capture-mode-btn {{window_mode_active}}" onclick="setCaptureMode('window')">🖥 ウィンドウ</button>
            <button class="capture-mode-btn {{region_mode_active}}" onclick="setCaptureMode('region')">🔲 画面範囲</button>
        </div>

        <div class="card" style="{{window_section_display}}">
            <h2>🖥 対象ウィンドウ</h2>
            <select id="windowSelect" onchange="selectWindow(this.value)">
                <option value="">-- ウィンドウを選択 --</option>
            </select>
            <button class="select-btn" onclick="refreshWindows()">🔄 ウィンドウ一覧を更新</button>
        </div>

        <div class="card" style="{{region_section_display}}">
            <h2>🔲 撮影領域</h2>
            <div class="row">
                <input type="number" id="rx" value="{{rx}}" placeholder="X">
                <input type="number" id="ry" value="{{ry}}" placeholder="Y">
                <input type="number" id="rw" value="{{rw}}" placeholder="幅">
                <input type="number" id="rh" value="{{rh}}" placeholder="高さ">
            </div>
            <button class="select-btn" onclick="selectRegion()">🖱 ドラッグで選択</button>
        </div>

        <div class="card">
            <h2>💾 保存方法</h2>
            <div class="capture-mode-btns">
                <button class="capture-mode-btn {{save_folder_active}}" onclick="setSaveMode('folder')" style="border-color: {{save_folder_active_color}}">📁 フォルダ</button>
                <button class="capture-mode-btn {{save_clipboard_active}}" onclick="setSaveMode('clipboard')" style="border-color: {{save_clipboard_active_color}}">📋 クリップボード</button>
                <button class="capture-mode-btn {{save_both_active}}" onclick="setSaveMode('both')" style="border-color: {{save_both_active_color}}">📁+📋 両方</button>
            </div>
        </div>

        <div class="card" style="{{folder_section_display}}">
            <h2>📁 保存先</h2>
            <input type="text" id="saveDir" value="{{save_dir}}" readonly>
            <button class="select-btn" onclick="selectFolder()">📁 変更</button>
        </div>

        <div class="card">
            <h2>モード</h2>
            <div class="mode-btns">
                <button class="mode-btn {{manual_active}}" onclick="setMode('manual')">🖱 手動</button>
                <button class="mode-btn {{auto_active}}" onclick="setMode('auto')">🔄 自動</button>
            </div>
        </div>

        <div class="card" style="{{auto_display}}">
            <h2>自動モード設定</h2>
            <div class="row">
                <div style="flex:1">
                    <small>検知待機 (秒)</small>
                    <input type="number" id="settlingTime" value="{{settling_time}}" step="0.1" min="0.1">
                </div>
                <div style="flex:1">
                    <small>監視間隔 (秒)</small>
                    <input type="number" id="pollingInterval" value="{{polling_interval}}" step="0.1" min="0.1">
                </div>
            </div>
        </div>

        <button class="main-btn {{btn_class}}" onclick="toggleCapture()">{{btn_text}}</button>

        <div class="card">
            <div class="status">
                <div class="count">{{count}} 枚</div>
                <div>{{status}}</div>
            </div>
        </div>

        <div id="thumbnailArea"></div>

        <div class="footer">
            <button onclick="openFolder()" style="{{folder_section_display}}">📂 開く</button>
            <button onclick="resetCount()">🔄 リセット</button>
            <button onclick="location.reload()">♻️ 更新</button>
        </div>
    </div>

    <script>
        function $(id) { return document.getElementById(id); }
        function setMode(m) { fetch('/api/mode?mode='+m).then(()=>location.reload()); }
        function setSaveMode(m) { fetch('/api/save_mode?mode='+m).then(()=>location.reload()); }
        function setCaptureMode(m) { fetch('/api/capture_mode?mode='+m).then(()=>location.reload()); }
        function toggleCapture() {
            let p = `saveDir=${encodeURIComponent($('saveDir')?.value||'')}&settlingTime=${$('settlingTime')?.value||0.5}&pollingInterval=${$('pollingInterval')?.value||0.2}`;
            if ($('rx')) p += `&rx=${$('rx').value}&ry=${$('ry').value}&rw=${$('rw').value}&rh=${$('rh').value}`;
            fetch('/api/toggle?'+p).then(()=>location.reload());
        }
        function openFolder() { fetch('/api/open_folder'); }
        function resetCount() { fetch('/api/reset').then(()=>location.reload()); }
        function selectFolder() { fetch('/api/select_folder').then(()=>location.reload()); }
        function selectRegion() { fetch('/api/select_region').then(()=>location.reload()); }

        // ウィンドウ一覧取得
        async function refreshWindows() {
            try {
                const res = await fetch('/api/windows');
                const windows = await res.json();
                const sel = $('windowSelect');
                const currentId = '{{selected_window_id}}';
                sel.innerHTML = '<option value="">-- ウィンドウを選択 --</option>';
                windows.forEach(w => {
                    const opt = document.createElement('option');
                    opt.value = w.id;
                    opt.textContent = w.display;
                    if (String(w.id) === currentId) opt.selected = true;
                    sel.appendChild(opt);
                });
            } catch(e) { console.error(e); }
        }

        function selectWindow(wid) {
            if (!wid) return;
            fetch('/api/select_window?id=' + wid).then(() => {
                // サムネイル表示
                const area = $('thumbnailArea');
                const img = document.createElement('img');
                img.src = '/api/thumbnail?id=' + wid + '&t=' + Date.now();
                img.className = 'thumbnail';
                area.innerHTML = '';
                area.appendChild(img);
            });
        }

        // ステータス更新
        async function updateStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                document.querySelector('.count').textContent = data.count + ' 枚';
                document.querySelector('.status div:last-child').textContent = data.status;
            } catch(e) {}
        }
        setInterval(updateStatus, 1500);

        // 起動時にウィンドウ一覧を読み込み
        refreshWindows();
    </script>
</body>
</html>
'''


# ─── HTTP Handler ────────────────────────────────

class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        try:
            if path == '/':
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()

                target_name = ""
                if state.capture_mode == "window" and state.target_owner_name:
                    target_name = state.target_owner_name
                    if state.target_window_name:
                        target_name += f" - {state.target_window_name}"
                elif state.capture_mode == "region" and state.region:
                    x, y, w, h = state.region
                    target_name = f"画面範囲: ({x},{y}) {w}×{h}"

                html = HTML_TEMPLATE
                rx, ry, rw, rh = state.region if state.region else (100, 100, 800, 600)
                replacements = {
                    '{{save_dir}}': str(state.save_dir),
                    '{{manual_active}}': 'active' if state.mode == 'manual' else '',
                    '{{auto_active}}': 'active' if state.mode == 'auto' else '',
                    '{{btn_class}}': 'stop-btn' if state.is_running else 'start-btn',
                    '{{btn_text}}': '⏹ 停止' if state.is_running else '▶️ 開始',
                    '{{count}}': str(state.capture_count),
                    '{{status}}': state.status,
                    '{{settling_time}}': str(state.settling_time),
                    '{{polling_interval}}': str(state.polling_interval),
                    '{{auto_display}}': '' if state.mode == 'auto' else 'display:none;',
                    '{{manual_info_display}}': '' if state.mode == 'manual' else 'display:none;',
                    '{{target_display}}': '' if (state.capture_mode == 'window' and state.target_window_id) or (state.capture_mode == 'region' and state.region) else 'display:none;',
                    '{{target_name}}': target_name,
                    '{{selected_window_id}}': str(state.target_window_id or ''),
                    '{{window_mode_active}}': 'active' if state.capture_mode == 'window' else '',
                    '{{region_mode_active}}': 'active' if state.capture_mode == 'region' else '',
                    '{{window_section_display}}': '' if state.capture_mode == 'window' else 'display:none;',
                    '{{region_section_display}}': '' if state.capture_mode == 'region' else 'display:none;',
                    '{{rx}}': str(rx), '{{ry}}': str(ry), '{{rw}}': str(rw), '{{rh}}': str(rh),
                    # 保存モード
                    '{{save_folder_active}}': 'active' if state.save_mode == 'folder' else '',
                    '{{save_clipboard_active}}': 'active' if state.save_mode == 'clipboard' else '',
                    '{{save_both_active}}': 'active' if state.save_mode == 'both' else '',
                    '{{save_folder_active_color}}': '#00bcd4' if state.save_mode == 'folder' else '#444',
                    '{{save_clipboard_active_color}}': '#00bcd4' if state.save_mode == 'clipboard' else '#444',
                    '{{save_both_active_color}}': '#00bcd4' if state.save_mode == 'both' else '#444',
                    '{{folder_section_display}}': 'display:none;' if state.save_mode == 'clipboard' else '',
                }
                for k, v in replacements.items():
                    html = html.replace(k, v)
                self.wfile.write(html.encode('utf-8'))

            elif path == '/api/windows':
                windows = get_window_list()
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(windows).encode('utf-8'))

            elif path == '/api/select_window':
                wid = int(query.get('id', [0])[0])
                if wid:
                    # ウィンドウ情報を取得して保存
                    windows = get_window_list()
                    for w in windows:
                        if w['id'] == wid:
                            state.target_window_id = wid
                            state.target_owner_name = w['owner']
                            state.target_window_name = w['name']
                            state.status = f"選択: {w['owner']}"
                            print(f"🖥 ウィンドウ選択: {w['display']}")
                            break
                self.send_response(200)
                self.end_headers()

            elif path == '/api/thumbnail':
                wid = int(query.get('id', [0])[0])
                if wid:
                    data = capture_window_thumbnail(wid)
                    if data:
                        self.send_response(200)
                        self.send_header('Content-type', 'image/png')
                        self.end_headers()
                        self.wfile.write(data)
                        return
                self.send_response(404)
                self.end_headers()

            elif path == '/api/capture_mode':
                if not state.is_running:
                    state.capture_mode = query.get('mode', ['window'])[0]
                self.send_response(200)
                self.end_headers()

            elif path == '/api/select_region':
                interactive_select_region()
                self.send_response(200)
                self.end_headers()

            elif path == '/api/mode':
                if not state.is_running:
                    state.mode = query.get('mode', ['manual'])[0]
                self.send_response(200)
                self.end_headers()

            elif path == '/api/save_mode':
                if not state.is_running:
                    mode = query.get('mode', ['folder'])[0]
                    if mode in ('folder', 'clipboard', 'both'):
                        state.save_mode = mode
                self.send_response(200)
                self.end_headers()

            elif path == '/api/toggle':
                if state.is_running:
                    stop_capture()
                else:
                    try:
                        state.save_dir = Path(query.get('saveDir', [str(state.save_dir)])[0])
                        state.settling_time = float(query.get('settlingTime', [0.5])[0])
                        state.polling_interval = float(query.get('pollingInterval', [0.2])[0])
                        if state.capture_mode == 'region':
                            state.region = (
                                int(query.get('rx', [100])[0]),
                                int(query.get('ry', [100])[0]),
                                int(query.get('rw', [800])[0]),
                                int(query.get('rh', [600])[0])
                            )
                        start_capture()
                    except Exception as e:
                        print(f"エラー: {e}")
                self.send_response(200)
                self.end_headers()

            elif path == '/api/capture':
                threading.Thread(target=manual_capture, daemon=True).start()
                self.send_response(200)
                self.end_headers()

            elif path == '/api/open_folder':
                os.system(f'open "{state.save_dir}"')
                self.send_response(200)
                self.end_headers()

            elif path == '/api/reset':
                state.capture_count = 0
                self.send_response(200)
                self.end_headers()

            elif path == '/api/status':
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                data = json.dumps({'count': state.capture_count, 'status': state.status})
                self.wfile.write(data.encode('utf-8'))

            elif path == '/api/select_folder':
                try:
                    script = 'set f to choose folder with prompt "保存先フォルダを選択"\nreturn POSIX path of f'
                    result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=60)
                    if result.returncode == 0 and result.stdout.strip():
                        state.save_dir = Path(result.stdout.strip())
                        state.save_dir.mkdir(parents=True, exist_ok=True)
                        init_capture_count()
                except Exception as e:
                    print(f"フォルダ選択エラー: {e}")
                self.send_response(200)
                self.end_headers()

            else:
                self.send_response(404)
                self.end_headers()
        except BrokenPipeError:
            pass


# ─── Main ────────────────────────────────────────

def main():
    print("=" * 50)
    print("ScreenshotApp")
    print("=" * 50)
    print("\n[権限が必要です]")
    print("  1. 画面収録")
    print("  2. アクセシビリティ")
    print("=" * 50)

    state.retina_scale = detect_retina_scale()
    state.save_dir.mkdir(parents=True, exist_ok=True)
    init_capture_count()

    print(f"\n保存先: {state.save_dir}")
    print(f"🌐 http://localhost:{PORT}")

    webbrowser.open(f'http://localhost:{PORT}')

    print("\n⌨️ ショートカット: Cmd+Ctrl+S")
    print("終了: Ctrl+C\n")

    def run_keyboard_listener():
        try:
            start_keyboard_listener()
        except Exception as e:
            print(f"キーボードリスナーエラー: {e}")

    keyboard_thread = threading.Thread(target=run_keyboard_listener, daemon=True)
    keyboard_thread.start()

    try:
        server = HTTPServer(('localhost', PORT), RequestHandler)
        server.serve_forever()
    except KeyboardInterrupt:
        stop_capture()
        print("\n終了")


if __name__ == "__main__":
    main()
