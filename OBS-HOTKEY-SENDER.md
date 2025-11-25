# OBS Hotkey Sender (Python) 🎮

A secure Python replacement for the Lua script that connects OBS to Socket Sentinel with token authentication.

## 🔧 Features

- **🔐 Secure Authentication**: Token-based authentication for both HTTP and TCP
- **🎯 Scene-Based Gating**: Actions only fire when the correct game scene is active
- **📡 Dynamic Config**: Loads configuration from Socket Sentinel server
- **🔑 Flexible Hotkeys**: Configurable keyboard shortcuts for all game actions
- **📊 Better Logging**: Comprehensive logging with timestamps and error handling
- **🖥️ OBS Integration**: Monitors scene changes via OBS WebSocket

## 📋 Requirements

- Python 3.7+
- OBS Studio with WebSocket plugin enabled
- Socket Sentinel server running

## 🚀 Installation

1. **Install Dependencies**:
   ```bash
   ./install-hotkey-sender.sh
   ```
   
   Or manually:
   ```bash
   pip3 install obsws-python requests keyboard pyyaml
   ```

2. **Configure Environment**:
   ```bash
   cp hotkey-sender.env .env
   # Edit .env with your settings
   ```

3. **Set Environment Variables**:
   ```bash
   export SS_TOKEN="your-secure-token-here"
   export OBS_PASSWORD="your-obs-websocket-password"
   ```

## ⚙️ Configuration

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `SS_TOKEN` | **Security token** (must match server) | `rematch_garage_culinary_...` |
| `OBS_PASSWORD` | OBS WebSocket password | `ukxNIWzEchoxZdSI` |

### Optional Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SENTINEL_HOST` | `127.0.0.1` | Socket Sentinel server host |
| `SENTINEL_TCP_PORT` | `5678` | TCP port for sending actions |
| `SENTINEL_HTTP_PORT` | `8088` | HTTP port for config fetch |
| `OBS_HOST` | `localhost` | OBS WebSocket host |
| `OBS_PORT` | `4455` | OBS WebSocket port |

## 🎮 Usage

1. **Start Socket Sentinel Server**:
   ```bash
   docker-compose up obs-socket-sentinel
   ```

2. **Start OBS** with WebSocket enabled

3. **Run Hotkey Sender**:
   ```bash
   python3 app/obs-hotkey-sender.py
   ```

## 🔑 Default Hotkey Mappings

| Action | Hotkey | Description |
|--------|--------|-------------|
| `kill` | `F1` | Register a kill |
| `death` | `F2` | Register a death |
| `headshot` | `F3` | Register a headshot |
| `downed` | `F4` | Register being downed |
| `revive` | `F5` | Register a revive |
| `start` | `F9` | Start recording session |
| `clear` | `F10` | Clear overlay |
| `run_start` | `Ctrl+F1` | Start a new run |
| `run_end` | `Ctrl+F2` | End current run |

## 🔐 Security Features

### Authentication Flow
1. **HTTP Requests**: Uses `Authorization: Bearer {SS_TOKEN}` header
2. **TCP Requests**: Includes `token={SS_TOKEN}` in payload
3. **Scene Validation**: Only allows actions for the current game scene

### TCP Message Format
```
token=your-secure-token-here
game=hunt_showdown
action=kill
```

## 📊 Scene-Based Action Gating

The script automatically determines which game is active based on the OBS scene name:

- **Scene Name**: `Hunt Showdown - Gameplay`
- **Detected Game**: `hunt_showdown`
- **Allowed Actions**: Only Hunt Showdown actions will work

This prevents accidentally triggering wrong game actions.

## 📝 Logging

Logs are written to both console and `obs-hotkey-sender.log`:

```
2025-11-23 18:13:34 [INFO] 📡 Fetching config from http://127.0.0.1:8088/config
2025-11-23 18:13:34 [INFO] ✅ Loaded config with 4 games: ['hunt_showdown', 'enshrouded', 'chivalry2', 'fortnite']
2025-11-23 18:13:34 [INFO] 🔑 Mapped f1 → hunt_showdown:kill
2025-11-23 18:13:34 [INFO] 📺 Scene changed: 'Hunt Showdown - Gameplay' → game: hunt_showdown
2025-11-23 18:13:34 [INFO] 🎯 Executing hunt_showdown:kill for scene 'Hunt Showdown - Gameplay'
2025-11-23 18:13:34 [INFO] 📤 Sent: game=hunt_showdown action=kill → 127.0.0.1:5678
```

## 🐛 Troubleshooting

### Authentication Errors
```bash
❌ Authentication failed - check SS_TOKEN
```
**Solution**: Ensure `SS_TOKEN` matches the server configuration.

### OBS Connection Issues
```bash
❌ Failed to connect to OBS: Connection refused
```
**Solution**: 
1. Enable OBS WebSocket in Tools → WebSocket Server Settings
2. Set password and update `OBS_PASSWORD`
3. Check OBS is running and port 4455 is available

### Scene Detection Issues
```bash
🚫 Ignoring hunt_showdown:kill - current scene 'Menu' maps to game 'None'
```
**Solution**: Switch to a scene name that contains your game name (e.g., "Hunt Showdown Gameplay").

### Server Connection Issues
```bash
❌ Could not connect to server at http://127.0.0.1:8088
```
**Solution**: Ensure Socket Sentinel server is running with `docker-compose up`.

## 🔄 Migration from Lua Script

The Python script replaces the Lua script with these improvements:

| Feature | Lua Script | Python Script |
|---------|------------|---------------|
| Authentication | ❌ None | ✅ Token-based |
| Error Handling | ⚠️ Basic | ✅ Comprehensive |
| Scene Monitoring | ⚠️ Static | ✅ Real-time |
| Logging | ⚠️ Minimal | ✅ Detailed |
| Hotkey Flexibility | ⚠️ Limited | ✅ Configurable |
| Config Loading | ⚠️ One-time | ✅ Dynamic |

## 🎯 Next Steps

1. **Customize Hotkeys**: Edit the `default_mappings` in `obs-hotkey-sender.py`
2. **Add Actions**: Configure new actions in your Socket Sentinel YAML config
3. **Scene Names**: Use descriptive scene names that match your games
4. **Security**: Use a strong, unique `SS_TOKEN` for production deployments

## 📚 Related Files

- `obs-hotkey-sender.py` - Main Python script
- `hotkey-sender.env` - Configuration template
- `install-hotkey-sender.sh` - Installation script
- `socket-sentinel.lua` - Original Lua script (deprecated)