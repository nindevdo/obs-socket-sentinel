# Quick Start: Three.js Intro

## 🎬 Trigger the Intro

### Method 1: Test Script (Easiest)
```bash
cd /home/captain/Public/ghorg/nindevdo/obs-socket-sentinel
./app/test_intro.sh
```

### Method 2: HTTP API
```bash
curl -X POST http://localhost:8088/action \
  -H "Authorization: Bearer YOUR_SS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"game":"hunt_showdown","action":"intro"}'
```

### Method 3: From OBS Lua Script
```lua
local data = '{"game":"hunt_showdown","action":"intro"}'
send_http_request("POST", "/action", data)
```

## 🎨 What You'll See

- **3D Text**: "The Cam Bros" rotating in 3D space
- **Fire Particles**: 200 orange/red particles rising upward
- **Glow Effect**: Pulsating emissive glow
- **Duration**: 8 seconds
- **Colors**: Orange (#ff6600), Red (#ff3300), Yellow (#ffaa00)

## ⚙️ Quick Customizations

### Change Duration
In `app/main.py`:
```python
INTRO_DISPLAY_DURATION = 10.0  # Change from 8 to 10 seconds
```

### Change Text
In `app/overlay_template.html` (search for "The Cam Bros"):
```javascript
ctx.fillText('Your Text Here', canvas.width / 2, canvas.height / 2);
```

### Change Colors
In `app/overlay_template.html`:
```javascript
const textMaterial = new THREE.MeshStandardMaterial({
  color: 0xff6600,     // Change main color
  emissive: 0xff3300,  // Change glow color
  // ...
});
```

## 🐛 Troubleshooting

**Intro doesn't show?**
1. Check browser console in OBS Browser Source
2. Verify SS_TOKEN is correct
3. Ensure OBS has hardware acceleration enabled

**Performance issues?**
- Reduce particle count (change `200` to `100`)
- Lower emissive intensity (change `1.5` to `0.8`)

## 📚 Full Documentation

See `THREEJS_INTRO.md` for complete documentation.
