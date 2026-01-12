# Voice-Controlled Color Filters

## Overview
Control OBS color correction filters using voice commands. Say a color name or phrase, and the system will automatically update your camera's color correction filter with the corresponding color scheme.

## Features

### Single Filter Approach
Instead of toggling multiple filters on/off, this system modifies a **single color correction filter** by updating its color properties (`color_add` and `color_multiply`). This is:
- More efficient (no enable/disable juggling)
- Cleaner (one filter instead of many)
- More flexible (easy to add new colors)

### Supported Colors
Built-in color palette:
- **Blue** - Cool blue tint
- **Magenta** - Vibrant magenta/pink
- **Cyan** - Cool cyan aqua
- **Red** - Warm red tint
- **Green** - Natural green tone
- **Yellow** - Warm yellow/golden
- **Purple** - Deep purple
- **Orange** - Warm orange
- **Pink** - Soft pink
- **Normal** - Reset to neutral (no color)

## Configuration

### Environment Variables (.env or docker-compose.yml)
```bash
# The source (camera) that has the color filter
OBS_CAMERA_SOURCE=Video Capture Device

# The name of the color correction filter in OBS
OBS_COLOR_FILTER=gb-color
```

### OBS Setup
1. Add a **Color Correction** filter to your camera source
2. Name it "gb-color" (or whatever you set in `OBS_COLOR_FILTER`)
3. The filter settings will be updated automatically via voice commands

## Voice Commands

### Direct Color Names
Say any color name:
- "blue"
- "magenta"
- "cyan"
- "red"
- "green"
- "yellow"
- "purple"
- "orange"
- "pink"

### Phrases
More natural phrases:
- "I'm feeling blue"
- "feeling magenta"
- "I'm feeling cyan"
- "feeling red"
- "feeling green"

The system supports both "I'm" and "im" variations.

### Reset to Normal
- "normal" - Removes color tint

## How It Works

### Voice Command Flow
```
You say: "I'm feeling blue"
    ↓
Whisper transcribes: "i'm feeling blue"
    ↓
VoiceCommandParser matches: color_shortcuts["i'm feeling blue"] = "blue"
    ↓
Returns: ('color', 'blue')
    ↓
voice_command_handler() calls:
    obs_ctrl.set_color_correction_filter(source, filter, "blue")
    ↓
OBS filter settings updated:
    color_add: 0xFF0066FF (blue tint)
    color_multiply: 0xFFCCDDFF (cool tone)
```

### Technical Details
1. **Color Palette** - Defined in `obs_controller.py` with hex color values
2. **Filter Update** - Uses `set_source_filter_settings()` with `overlay=True`
3. **Overlay Mode** - Only updates color values, preserves other filter settings

## Customization

### Adding New Colors
Edit `obs_controller.py`, find the `color_palette` dictionary in `set_color_correction_filter()`:

```python
color_palette = {
    "your_color": {
        "color_add": 0xFFRRGGBB,      # Additive color
        "color_multiply": 0xFFRRGGBB, # Multiplicative color
    },
}
```

Then add voice commands in `voice_commands.py`:
```python
self.color_shortcuts = {
    "your_color": "your_color",
    "feeling your_color": "your_color",
}
```

### Adjusting Color Values
The color palette uses hex ARGB format: `0xFFRRGGBB`
- `FF` = Alpha (always 255/0xFF)
- `RR` = Red component (00-FF)
- `GG` = Green component (00-FF)
- `BB` = Blue component (00-FF)

**color_add**: Adds color tint
- Higher values = stronger tint
- `0xFF000000` = no tint

**color_multiply**: Multiplies existing colors
- `0xFFFFFFFF` = normal (no change)
- Lower values = darker
- Adjust RGB to shift tone (e.g., `0xFFCCDDFF` = cool blue tone)

### Different Filter Type
If using a different OBS filter (not Color Correction), you'll need to:
1. Check what properties that filter supports
2. Update the `color_palette` dictionary with appropriate property names
3. The filter must support property modification via OBS WebSocket

## Testing

### Manual Test (without voice)
You can test the color switching from Python:
```python
from obs_controller import get_obs_controller
import asyncio

async def test():
    obs = await get_obs_controller()
    await obs.set_color_correction_filter("Video Capture Device", "gb-color", "blue")

asyncio.run(test())
```

### Voice Test
1. Start streaming/recording (or just have OBS open with camera active)
2. Say "feeling blue"
3. Check logs: `docker compose logs -f obs-socket-sentinel`
4. You should see:
   ```
   [voice] 🎨 Color command 'feeling blue' -> color 'blue'
   🎨 Applied color 'blue' to filter 'gb-color' on 'Video Capture Device'
   [voice] ✅ Switched to color 'blue'
   ```

### Troubleshooting

**Color doesn't change:**
- Check filter name matches `OBS_COLOR_FILTER` env var
- Check source name matches `OBS_CAMERA_SOURCE` env var
- Verify filter is enabled in OBS
- Check if filter is "Color Correction" type (or compatible)

**Voice command not recognized:**
- Check transcription in logs (what Whisper heard)
- Verify color name exists in `color_shortcuts` dictionary
- Try saying it more clearly or slower

**Wrong colors applied:**
- Adjust hex values in `color_palette`
- Test with different `color_add` and `color_multiply` values
- OBS may render colors differently based on scene/sources

## Future Ideas
- [ ] Temperature-based colors ("warm", "cool")
- [ ] Mood-based colors ("happy", "sad", "angry")
- [ ] Intensity control ("light blue", "dark blue")
- [ ] Gradual transitions between colors
- [ ] Save/recall custom color presets
- [ ] Time-based automatic color switching
