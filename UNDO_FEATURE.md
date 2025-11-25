# Undo Feature Documentation

## Overview
The OBS Socket Sentinel now includes an undo system that allows you to reverse actions one by one in case of accidental button presses.

## How It Works
- Every action (kill, death, headshot, etc.) is tracked in an undo history
- The `undo` action removes the most recent action from history
- Action counts are decremented and run statistics are reversed
- A chapter entry is added showing what was undone
- History is limited to the last 50 actions to prevent memory issues

## Usage

### Hotkeys
- **F11**: Undo the last action (default mapping)
- Works globally across all game scenes

### TCP Command
Send the action `undo` via TCP to trigger an undo:
```
game=hunt_showdown
action=undo
```
Or simply:
```
undo
```

### OBS Lua Script
The undo hotkey is automatically registered when the Lua script loads.

## Examples

### Scenario 1: Accidental Double-Press
1. Press kill button (F1) twice accidentally
2. Overlay shows: "💀 kill x2"
3. Press undo (F11)
4. Overlay shows: "💀 kill x1" 
5. Action count correctly decremented

### Scenario 2: Wrong Action
1. Press kill (F1) but it should have been death (F2)
2. Overlay shows: "💀 kill x1"
3. Press undo (F11)
4. Overlay shows: "Undone"
5. Press death (F2)
6. Overlay shows: "☠️ death x1"

### Scenario 3: Run Statistics
1. During a run: kill, kill, death, headshot
2. Run stats: 2 kills, 1 death, 1 headshot
3. Press undo (F11) to undo the headshot
4. Run stats: 2 kills, 1 death, 0 headshots
5. Action history shows what was undone

## Technical Details

### What Gets Undone
- Action counts per project
- Run statistics (kills, deaths, headshots, events)
- Chapter file gets an "UNDO: [action]" entry

### What Doesn't Get Undone
- Run start/end events (these are special)
- Clear actions (irreversible reset)
- Media playback (videos/sounds don't replay in reverse)

### History Limits
- Maximum 50 actions in undo history
- History is cleared when "clear" action is used
- History persists until application restart

### Error Handling
- If no actions to undo, overlay shows "Nothing to undo"
- System gracefully handles edge cases like empty history
- Failed chapter writes are logged but don't stop undo

## Configuration
The undo action is automatically available in all game configurations. No additional setup required.

### Hotkey Customization
Modify the hotkey mapping in:
- Python script: `obs-hotkey-sender.py` line ~232
- Lua script: System actions are auto-registered

```python
default_mappings = {
    # ... other mappings ...
    'undo': 'f11',  # Change this to desired key
}
```