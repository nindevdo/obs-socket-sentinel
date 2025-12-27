# 🎬 Setting Up Intro Hotkey

## Quick Setup (Recommended)

The intro action is now available in the UI Driver! 

### Access the UI
1. Open: `http://ss.nindevdo.com/ui`
2. Find **"🛠️ System Actions"** section
3. You'll see **🎬 intro** button

### Assign a Hotkey (via OBS Hotkey Sender)

If you're using `obs-hotkey-sender.py`, you can assign any keyboard shortcut:

1. **Edit your hotkey config** (usually in the script or environment)
2. **Add intro mapping**:
   ```python
   # Example hotkey assignment
   'F12': 'intro'  # Press F12 to trigger intro
   ```

3. **Restart the hotkey sender script**

## Manual Trigger Methods

### 1. Via Test Script
```bash
./app/test_intro.sh
```

### 2. Via HTTP API
```bash
curl -X POST http://ss.nindevdo.com/action \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"game":"hunt_showdown","action":"intro"}'
```

### 3. Via UI Button
1. Go to http://ss.nindevdo.com/ui
2. Click the **🎬 intro** button in System Actions

## Hotkey Sender Configuration

If you want to set up the Python hotkey sender for OBS:

### Install Dependencies
```bash
pip install obsws-python requests keyboard pyyaml
```

### Configure Hotkeys
Edit your hotkey configuration to include:
```python
HOTKEY_MAPPINGS = {
    'F12': 'intro',       # Intro animation
    'F1': 'kill',         # Kill action
    'F2': 'death',        # Death action
    # ... other mappings
}
```

### Run the Hotkey Sender
```bash
python3 app/obs-hotkey-sender.py
```

## What You'll See

When the intro triggers, you'll see:
- **Realistic fire text**: "The Cam Bros" with gradient fire colors (red→orange→yellow→white)
- **ProggyClean Nerd Font**: Same font as the rest of your overlay
- **300 fire particles**: Multi-colored particles (red at bottom, yellow at top)
- **Flickering animation**: Particles fade and shrink as they rise
- **Subtle floating**: Text gently bobs up and down
- **8 seconds duration**: Configurable in main.py

## Troubleshooting

### "Don't see intro button in UI"
- Refresh the UI page (Ctrl+F5)
- Clear browser cache
- Check that Docker container restarted successfully

### "Hotkey not working"
- Ensure obs-hotkey-sender.py is running
- Check that OBS WebSocket is connected
- Verify hotkey mapping includes 'intro'

### "Fire doesn't look right"
- Refresh OBS Browser Source cache
- Ensure hardware acceleration is enabled
- Check browser console for WebGL errors

## Advanced: Custom Hotkey Script

Create your own hotkey script:

```python
#!/usr/bin/env python3
import requests
import keyboard

SS_TOKEN = "your_token_here"
SERVER = "http://ss.nindevdo.com"

def trigger_intro():
    response = requests.post(
        f"{SERVER}/action",
        headers={"Authorization": f"Bearer {SS_TOKEN}"},
        json={"game": "hunt_showdown", "action": "intro"}
    )
    print(f"Intro triggered: {response.json()}")

keyboard.add_hotkey('F12', trigger_intro)
print("Press F12 to trigger intro. Press Ctrl+C to exit.")
keyboard.wait()
```

Save as `trigger_intro_hotkey.py` and run:
```bash
python3 trigger_intro_hotkey.py
```

---

**See also:**
- THREEJS_INTRO.md - Full documentation
- QUICK_START_INTRO.md - Quick reference
- verify_intro.sh - Verification script
