# Voice Command Ideas for Socket Sentinel

Now that we have voice control working, here are creative actions we could add:

## 🎭 Scene & Presentation Control
- **"Zoom in"/"Zoom out"** - Adjust camera zoom levels via OBS filters
- **"Show chat"/"Hide chat"** - Toggle chat overlay visibility
- **"Full screen cam"/"Picture in picture"** - Quick camera layout changes
- **"Show alerts"/"Hide alerts"** - Toggle notification area
- **"Webcam on/off"** - Toggle webcam source visibility

## 🎨 Visual Effects
- **"Add blur"/"Remove blur"** - Background blur on/off
- **"Green screen"** - Toggle chroma key
- **"Black and white"/"Color"** - Toggle color filters
- **"Slow motion effect"** - Trigger slow-mo replay (if supported)
- **"Night mode"/"Day mode"** - Dark/light theme switching

## 📊 Information Overlays
- **"Show stats"** - Display game stats overlay
- **"Show timer"** - Start/stop on-screen timer
- **"Show scoreboard"** - Toggle score display
- **"Show FPS counter"** - Performance overlay
- **"Poll time"** - Start a viewer poll

## 🎵 Audio Control
- **"Mute mic"/"Unmute mic"** - Quick mic toggle
- **"Lower music"/"Raise music"** - Adjust background music volume
- **"Game audio only"** - Mute other sources
- **"Play intro music"** - Trigger specific audio clips
- **"Sound effect [name]"** - Play sound effects by name

## 🎬 Stream Markers & Highlights
- **"Mark this"/"Bookmark"** - Add stream marker with voice note ✅ **IMPLEMENTING**
- **"Clip that"** - Add highlight marker to stream ✅ **IMPLEMENTING**
- **"Highlight reel"** - Add timestamp for highlight compilation
- **"Epic moment"** - Flag for post-stream editing

## 🎮 Game Integration
- **"Show loadout"** - Display current gear/setup
- **"Compare stats"** - Show stat comparison overlay
- **"Predict [outcome]"** - Set prediction overlay
- **"Challenge mode"** - Activate viewer challenge overlay

## 📢 Chat & Social
- **"Shoutout [name]"** - Automated shoutout overlay
- **"Poll question"** - Voice-to-text poll creation
- **"Pin message"** - Pin last chat message
- **"Slow mode on/off"** - Chat moderation
- **"Show social links"** - Display social media overlay

## 🎯 Quick Actions
- **"Emergency BRB"** - Instant BRB scene + mute all
- **"Bathroom break"** - BRB + timer + pause recording
- **"Technical difficulties"** - Error screen + hold music
- **"Ending soon"** - End stream countdown overlay
- **"Starting raid"** - Raid transition scene

## 🔧 Advanced OBS Features
- **"Start virtual cam"/"Stop virtual cam"** - Toggle virtual camera
- **"Screenshot"** - Take OBS screenshot
- **"Studio mode"** - Toggle studio mode
- **"Preview scene [name]"** - Load scene in preview

## 🎪 Interactive Elements
- **"Spin the wheel"** - Random game/challenge selector
- **"Roll dice"** - Random number overlay
- **"Coin flip"** - Heads/tails decision maker
- **"Random viewer"** - Select random chatter

## 📝 Text & Captions
- **"Show banner [text]"** - Display custom text banner
- **"Lower third [text]"** - Name/title overlay
- **"Caption on/off"** - Toggle closed captions
- **"Change title to [text]"** - Update stream title

## Priority Implementations
Most useful for immediate workflow:

1. ✅ **"Clip that"** - Add stream marker (IN PROGRESS)
2. **"Mute mic"/"Unmute mic"** - Simple audio control
3. **"Mark this"** - Add stream markers
4. **"Show/hide chat"** - Source visibility toggle
5. **"Emergency BRB"** - Quick preset scene combination

## Implementation Notes
- Voice commands use Whisper transcription with 1-second audio chunks
- Multi-word commands work via 3-second buffering system
- Commands match against shortcuts and scene names
- All commands require SS_TOKEN authentication
- Stream markers are added via OBS WebSocket API during active streams
