import subprocess
import threading
import time
from Quartz import CGEventCreate, CGEventGetLocation

def get_click_pos():
    positions = []
    monitoring = {'active': True}
    def monitor():
        while monitoring['active']:
            event = CGEventCreate(None)
            pos = CGEventGetLocation(event)
            positions.append((int(pos.x), int(pos.y)))
            time.sleep(0.02)

    t = threading.Thread(target=monitor, daemon=True)
    t.start()
    
    # Run screencapture in interactive mode, but maybe it requires a file
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.png') as tmp:
        subprocess.run(['screencapture', '-i', '-c', tmp.name])
    
    monitoring['active'] = False
    return positions[-1] if positions else None

print(get_click_pos())
