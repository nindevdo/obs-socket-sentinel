# 🎬 OBS Remote Control Integration

## Overview

Socket Sentinel now includes **native OBS remote control** via WebSocket! This allows you to:

- **Switch scenes** remotely
- **Change transitions** 
- **Start/Stop streaming**
- **Start/Stop recording**
- **Auto-populate controls** from your OBS setup

All OBS controls are **dynamically fetched** from your OBS instance, so scene names and transitions update automatically.

---

## ✅ Setup

### 1. Enable OBS WebSocket

1. Open OBS Studio
2. Go to **Tools → WebSocket Server Settings**
3. Check **"Enable WebSocket server"**
4. Note the **Port** (default: 4455)
5. Set a **Server Password** (or leave blank)
6. Click **OK**

### 2. Configure Environment Variables

Your `docker-compose.yml` already has OBS settings. Just update them:

```yaml
services:
  obs-socket-sentinel:
    environment:
      - OBS_IP=localhost          # IP of machine running OBS
      - OBS_PORT=4455             # OBS WebSocket port (default: 4455)
      - OBS_PASSWORD=             # WebSocket password (set in OBS)
```

**If OBS is on a different machine:**
```yaml
- OBS_IP=192.168.1.100  # IP address of OBS computer
```

### 3. Restart Container

```bash
docker-compose restart obs-socket-sentinel
```

---

## 🎯 Usage

### Get Available OBS Controls

Fetch all available scenes, transitions, and controls:

```bash
curl http://ss.nindevdo.com/obs/actions
```

**Response:**
```json
{
  "scene_gaming": "🎬 Gaming",
  "scene_just_chatting": "🎬 Just Chatting",
  "scene_be_right_back": "🎬 Be Right Back",
  "transition_fade": "✨ Fade",
  "transition_cut": "✨ Cut",
  "obs_start_stream": "🔴 Start Stream",
  "obs_stop_stream": "⏹️ Stop Stream",
  "obs_start_record": "🔴 Start Record",
  "obs_stop_record": "⏹️ Stop Record"
}
```

### Trigger OBS Actions

Switch to a scene:
```bash
curl -X POST http://ss.nindevdo.com/action \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"game":"hunt_showdown","action":"scene_gaming"}'
```

Change transition:
```bash
curl -X POST http://ss.nindevdo.com/action \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"game":"hunt_showdown","action":"transition_fade"}'
```

Start streaming:
```bash
curl -X POST http://ss.nindevdo.com/action \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"game":"hunt_showdown","action":"obs_start_stream"}'
```

---

## 🖥️ UI Integration

The UI at **http://ss.nindevdo.com/ui** will **automatically show OBS controls** when connected!

### Layout:
1. 🛠️ **System Actions** (yellow) - intro, undo, clear, start
2. 🎬 **OBS Remote Control** (green) - auto-populated scenes/transitions
3. 🎮 **Game Actions** (blue) - kill, death, headshot, etc.

All on one page, no scrolling needed!

---

## 🔧 Available Actions

### Scene Switching
- **Format:** `scene_<scene_name>`
- **Example:** `scene_gaming`, `scene_just_chatting`
- **Auto-generated** from your OBS scenes

### Transition Control
- **Format:** `transition_<transition_name>`
- **Example:** `transition_fade`, `transition_cut`
- **Auto-generated** from your OBS transitions

### Streaming Control
- `obs_start_stream` - Start streaming
- `obs_stop_stream` - Stop streaming

### Recording Control
- `obs_start_record` - Start recording
- `obs_stop_record` - Stop recording

---

## 🛠️ Advanced Features

### Source Visibility (Coming Soon)
Toggle sources on/off within scenes.

### Scene Collection Switching (Coming Soon)
Switch between different scene collections.

### Audio Control (Coming Soon)
Adjust volume, mute/unmute sources.

---

## 🔍 Troubleshooting

### "OBS not connected" error

**Check:**
1. Is OBS running?
2. Is WebSocket server enabled in OBS?
3. Are the credentials correct in docker-compose.yml?
4. Can the container reach OBS? (firewall, network)

**Test connection:**
```bash
docker-compose logs obs-socket-sentinel | grep OBS
```

**Should see:**
```
✅ Connected to OBS WebSocket at localhost:4455
📡 OBS State: 5 scenes, 3 transitions, 12 sources
```

### Actions not appearing

**Refresh OBS state:**
```bash
curl http://ss.nindevdo.com/obs/actions
```

This will fetch the latest scenes and transitions from OBS.

### Scene names with spaces

Spaces are converted to underscores:
- OBS: `"Just Chatting"`
- Action: `scene_just_chatting`

---

## 📝 Example Use Cases

### Stream Manager Dashboard

Create a remote dashboard to:
- Switch scenes during stream
- Control streaming/recording
- Change transitions
- All from phone/tablet

### Automated Scene Switching

Trigger scene changes based on:
- Game events (kills, deaths)
- Time-based automation
- External triggers

### Multi-PC Setup

Control OBS on streaming PC from gaming PC over network.

---

## 🔐 Security

- Uses same authentication as other actions
- WebSocket password protects OBS access
- Can restrict OBS_IP to localhost only

---

## 📚 API Reference

### GET /obs/actions

Returns available OBS controls.

**Response:** JSON object with action_key → display_name

### POST /action

Execute OBS action.

**Body:**
```json
{
  "game": "project_name",
  "action": "scene_gaming"
}
```

---

## 📋 Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OBS_IP` | IP address of OBS machine | `localhost` |
| `OBS_PORT` | OBS WebSocket port | `4455` |
| `OBS_PASSWORD` | WebSocket password | `` (empty) |

---

**Ready to remote control your OBS!** 🎬🎮

