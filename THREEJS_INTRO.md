# Three.js Intro Animation System

## Overview

A new global system action `intro` has been added to the OBS Socket Sentinel overlay system. This action triggers a stunning 3D animated introduction featuring "The Cam Bros" text with fire effects.

## Features

### Visual Effects
- **3D Rotating Text**: The text "The Cam Bros" appears in 3D space with smooth rotation
- **Fire Particle System**: 200 animated fire particles rise from the bottom
- **Pulsating Glow**: Dynamic emissive lighting that pulses with the animation
- **Gradient Fire Colors**: Orange, red, and yellow gradient effects
- **Transparent Background**: Seamlessly overlays on your stream

### Technical Details
- **Duration**: 8 seconds (configurable in `main.py` via `INTRO_DISPLAY_DURATION`)
- **Library**: Three.js r128 (loaded from CDN)
- **z-index**: 20000 (displays above all other overlay elements)
- **Performance**: Optimized particle system with efficient rendering

## Configuration

### Global System Action

The intro action is defined in `app/config.yaml`:

```yaml
global_system_actions:
  intro: "🎬"
```

This makes it available across all games without needing to define it per-game.

### Duration Settings

In `app/main.py`, you can adjust the display duration:

```python
INTRO_DISPLAY_DURATION = 8.0  # Show intro for 8 seconds
```

## Usage

### Via HTTP API

```bash
curl -X POST http://localhost:8088/action \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "game": "hunt_showdown",
    "action": "intro"
  }'
```

### Via Test Script

```bash
cd /home/captain/Public/ghorg/nindevdo/obs-socket-sentinel
./app/test_intro.sh
```

### Via OBS Lua Script

```lua
-- From socket-sentinel-http.lua or any Lua hotkey script
local data = '{"game":"hunt_showdown","action":"intro"}'
send_http_request("POST", "/action", data)
```

### Via UI Driver

The intro action should appear in the UI driver interface under "System Actions" with the 🎬 emoji.

## File Changes

### Modified Files

1. **app/config.yaml**
   - Added `global_system_actions` section
   - Defined `intro: "🎬"` action

2. **app/main.py**
   - Added `GLOBAL_SYSTEM_ACTIONS` global variable
   - Added `current_intro`, `intro_display_until`, `INTRO_DISPLAY_DURATION` state variables
   - Updated `load_config()` to load global system actions
   - Created `trigger_intro()` function
   - Added intro handling in `handle_action()`
   - Added intro notification to `/overlay` endpoint response

3. **app/overlay_template.html**
   - Added Three.js library CDN link
   - Added `#intro-canvas` element and CSS styling
   - Implemented Three.js scene, camera, renderer, and animation
   - Created fire particle system
   - Created 3D text with fire material and texture
   - Added intro state management in `pollOverlay()` function

### New Files

1. **app/test_intro.sh**
   - Test script to trigger the intro animation
   - Automatically reads `SS_TOKEN` from environment or `.env` file

## Customization

### Changing the Text

Edit `app/overlay_template.html` around line 1368:

```javascript
current_intro = {
  "trigger": True,
  "text": "Your Custom Text",  // Change this
  "timestamp": now
}
```

And in the frontend (around line 1367):

```javascript
ctx.fillText('Your Custom Text', canvas.width / 2, canvas.height / 2);
```

### Adjusting Fire Colors

In `app/overlay_template.html`, modify the material colors:

```javascript
const textMaterial = new THREE.MeshStandardMaterial({
  color: 0xff6600,        // Main fire color (orange)
  emissive: 0xff3300,     // Glow color (red-orange)
  emissiveIntensity: 1.5, // Glow strength
  // ...
});
```

And the gradient:

```javascript
gradient.addColorStop(0, '#ff6600');    // Start color
gradient.addColorStop(0.5, '#ff3300');  // Middle color
gradient.addColorStop(1, '#ffaa00');    // End color
```

### Particle Count

Adjust the number of fire particles:

```javascript
const particleCount = 200;  // Default: 200, increase for more particles
```

### Animation Speed

Modify rotation and particle speeds:

```javascript
// Text rotation speed
introTextMesh.rotation.y += 0.01;  // Increase for faster rotation

// Particle rise speed
velocities.push({
  y: Math.random() * 0.05 + 0.02  // Adjust the multiplier for speed
});
```

## Troubleshooting

### Intro Doesn't Appear

1. **Check browser console** for Three.js errors
2. **Verify SS_TOKEN** is correct in your request
3. **Check overlay endpoint** by visiting `http://localhost:8088/overlay` in browser
4. **Ensure OBS Browser Source** has hardware acceleration enabled

### Performance Issues

1. **Reduce particle count** (lower `particleCount` value)
2. **Decrease emissive intensity** (less glow = better performance)
3. **Enable hardware acceleration** in OBS Browser Source settings

### Text Not Visible

1. **Check canvas size** - text might be outside viewport
2. **Verify z-index** - ensure intro canvas is above other elements
3. **Check opacity** - canvas should have `opacity: 1` when visible

## Integration with Existing Systems

The intro system seamlessly integrates with:

- **Achievement notifications** (lower z-index, won't conflict)
- **Meme/video overlays** (intro has higher z-index)
- **Counter boxes** (intro displays independently)
- **Run tracking** (intro doesn't affect stats)
- **CTA notifications** (intro has higher z-index)

## Future Enhancements

Potential improvements for the intro system:

1. **Multiple intro templates** - Select different animations
2. **Custom text from API** - Pass text in the request
3. **Sound effects** - Add audio to the intro
4. **Different particle effects** - Snow, sparkles, etc.
5. **Transition effects** - Fade in/out improvements
6. **Font customization** - Allow different fonts via API

## Credits

- **Three.js**: https://threejs.org/
- **Developer**: Socket Sentinel Team
- **Version**: 1.0.0
- **Date**: 2025-12-27
