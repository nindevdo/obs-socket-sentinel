# OBS Voice Commands - Full WebSocket Control

## Voice Command Categories

This document maps natural language voice commands to OBS WebSocket v5 requests.

---

## 1. STREAMING (Already Implemented ✅)

### Commands
- "start stream", "go live", "start streaming"
- "stop stream", "end stream", "stop streaming"
- "toggle stream"

### WebSocket Calls
- `StartStream`
- `StopStream`
- `ToggleStream`
- `GetStreamStatus`

---

## 2. RECORDING (Already Implemented ✅)

### Commands
- "start recording", "start record"
- "stop recording", "stop record"
- "toggle recording"

### WebSocket Calls
- `StartRecord`
- `StopRecord`
- `ToggleRecord`
- `GetRecordStatus`

---

## 3. REPLAY BUFFER (Already Implemented ✅)

### Commands
- "start replay buffer"
- "stop replay buffer"
- "save replay", "clip that", "save that"

### WebSocket Calls
- `StartReplayBuffer`
- `StopReplayBuffer`
- `SaveReplayBuffer`
- `GetReplayBufferStatus`

---

## 4. VIRTUAL CAMERA (NEW)

### Commands
- "start virtual camera", "virtual cam on"
- "stop virtual camera", "virtual cam off"
- "toggle virtual camera"

### WebSocket Calls
- `StartVirtualCam`
- `StopVirtualCam`
- `ToggleVirtualCam`
- `GetVirtualCamStatus`

---

## 5. SCENES (Partially Implemented ✅)

### Current Implementation
- Scene switching via dynamic scene list
- "switch to [scene name]"

### Additional Commands (NEW)
- "what scene am I on", "current scene"
- "create scene [name]"
- "delete scene [name]"
- "rename scene [old] to [new]"
- "studio mode on/off"
- "preview [scene name]" (studio mode)

### WebSocket Calls
- `GetSceneList` ✅
- `GetCurrentProgramScene` ✅
- `SetCurrentProgramScene` ✅
- `GetCurrentPreviewScene` (NEW)
- `SetCurrentPreviewScene` (NEW)
- `CreateScene` (NEW)
- `RemoveScene` (NEW)
- `SetSceneName` (NEW)
- `GetStudioModeEnabled` (NEW)
- `SetStudioModeEnabled` (NEW)

---

## 6. SOURCES (Already Implemented ✅)

### Commands
- "camera on/off", "show/hide camera", "toggle camera"
- "[source name] on/off"

### WebSocket Calls
- `SetSceneItemEnabled` ✅
- `GetSceneItemEnabled` ✅

### Additional (NEW)
- "screenshot [source]"
- "save screenshot [source]"

### WebSocket Calls (NEW)
- `GetSourceScreenshot`
- `SaveSourceScreenshot`

---

## 7. AUDIO / INPUTS (NEW)

### Commands
- "mute [source]", "unmute [source]"
- "mute mic", "unmute mic"
- "volume [source] [0-100]"
- "volume up/down [source]"
- "monitor [source] on/off"

### WebSocket Calls
- `GetInputMute`
- `SetInputMute`
- `ToggleInputMute`
- `GetInputVolume`
- `SetInputVolume`
- `GetInputMonitorType`
- `SetInputMonitorType`

---

## 8. FILTERS (Already Implemented ✅)

### Commands
- Color filter switching ✅
- "[filter name] on/off"

### WebSocket Calls
- `GetSourceFilterList` ✅
- `SetSourceFilterEnabled` ✅
- `SetSourceFilterSettings` ✅

### Additional (NEW)
- "create filter [type] on [source]"
- "remove filter [name] from [source]"

### WebSocket Calls (NEW)
- `CreateSourceFilter`
- `RemoveSourceFilter`

---

## 9. TRANSITIONS (Partially Implemented)

### Current
- Transitions loaded dynamically ✅

### Commands (NEW)
- "use [transition name]"
- "fade transition", "cut transition"
- "transition speed [duration]"

### WebSocket Calls
- `GetTransitionList` ✅
- `SetCurrentTransition` (NEW)
- `GetTransitionDuration` (NEW)
- `SetTransitionDuration` (NEW)

---

## 10. MEDIA CONTROLS (NEW)

### Commands
- "play media", "pause media"
- "restart media", "stop media"
- "next media", "previous media"

### WebSocket Calls
- `GetMediaInputStatus`
- `TriggerMediaInputAction` (play/pause/restart/stop/next/previous)

---

## 11. HOTKEYS (NEW - POWERFUL)

### Commands
- "trigger [hotkey name]"
- "press [hotkey]"

### WebSocket Calls
- `GetHotkeyList`
- `TriggerHotkeyByName`

### Use Cases
- "push to talk"
- "push to mute"
- Any custom OBS hotkey

---

## 12. PROFILES & COLLECTIONS (NEW)

### Commands
- "switch to profile [name]"
- "switch to collection [name]"
- "what profile am I using"

### WebSocket Calls
- `GetProfileList`
- `SetCurrentProfile`
- `GetSceneCollectionList`
- `SetCurrentSceneCollection`

---

## 13. STATS & INFO (NEW)

### Commands
- "stream stats", "how's my stream"
- "fps", "what's my fps"
- "dropped frames"
- "bitrate"

### WebSocket Calls
- `GetStats`
- `GetStreamStatus`

---

## 14. ADVANCED FEATURES (NEW)

### Screenshot Automation
- "take screenshot"
- "screenshot every [N] seconds"

### Auto-switching
- "switch scenes every [N] seconds"
- "random scene"

### Batch Commands
- "execute [command1] then [command2]"
- Uses request batching

---

## Implementation Priority

### Phase 1 (Quick Wins)
1. Virtual Camera controls
2. Audio/Input mute/volume
3. Transition switching
4. Hotkey triggering
5. Studio mode

### Phase 2 (Enhanced Control)
1. Media playback controls
2. Screenshot automation
3. Stats/info queries
4. Profile/collection switching

### Phase 3 (Advanced)
1. Scene/source creation/removal
2. Filter management
3. Batch command execution
4. Custom automation sequences

---

## Natural Language Parsing Strategy

### Current Approach
- Keyword matching with word boundaries
- Scene name matching from OBS state
- Shortcut mappings in `voice_commands.py`

### Enhanced Approach (Recommended)
1. **Intent Classification**
   - Category: stream/record/scene/audio/filter/etc.
   - Action: start/stop/toggle/set/get
   - Target: source name, scene name, value

2. **Entity Extraction**
   - Source names from OBS state
   - Scene names from OBS state
   - Filter names from OBS state
   - Numeric values (volume %, duration)

3. **Command Templates**
   ```
   [action] [target] [modifier]
   "mute" "microphone" ""
   "volume" "desktop audio" "50"
   "switch to" "gaming scene" ""
   "toggle" "camera" ""
   ```

4. **Fuzzy Matching**
   - "mic" → "Mic/Aux"
   - "desktop" → "Desktop Audio"
   - "game scene" → "Gaming Scene"

---

## Security Considerations

### Restricted Commands
Some commands should require confirmation or be disabled:
- Scene/source deletion
- Profile changes
- Stream service settings
- File operations

### Safe Commands
- Scene switching
- Source visibility
- Audio mute/volume
- Filter toggles
- Replay buffer save
- Screenshots

---

## Next Steps

1. Extend `obs_controller.py` with new WebSocket methods
2. Add command mappings to `voice_commands.py`
3. Implement intent parsing for complex commands
4. Add confirmation prompts for destructive operations
5. Create voice feedback for successful operations

