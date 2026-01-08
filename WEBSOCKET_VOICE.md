# WebSocket Voice Streaming Implementation

## Overview
Replaced HTTP POST audio streaming with WebSocket for more stable, continuous voice command processing.

## Changes Made

### Backend (main.py)
1. **Added WebSocket Endpoint**: `/voice/ws`
   - Handles WebSocket upgrade handshake
   - Processes WebSocket frames (binary audio data, ping/pong, close)
   - Feeds audio directly to existing `process_browser_audio_chunk()` function

2. **Added `handle_voice_websocket()` Function**
   - Parses WebSocket frame protocol (RFC 6455)
   - Handles binary frames (audio PCM data)
   - Responds to ping/pong for keep-alive
   - Handles connection close gracefully
   - 60-second timeout for inactive connections

3. **Kept HTTP POST Endpoint** `/voice/audio`
   - Maintained for backward compatibility
   - Can be removed later if WebSocket proves stable

### Frontend (ui_driver_template.html)
1. **WebSocket Connection**
   - Connects to `ws://` or `wss://` based on page protocol
   - Automatically uses secure WebSocket (wss://) when accessed via HTTPS (Cloudflare)
   
2. **Audio Streaming**
   - Sends PCM audio chunks directly via WebSocket binary frames
   - No buffering - immediate streaming (lower latency)
   - Sends every 4096 samples (~85ms at 48kHz)

3. **Auto-Reconnect Logic**
   - Detects WebSocket disconnection
   - Automatically attempts to reconnect after 2 seconds
   - Restarts entire audio capture pipeline on reconnect
   - Can be disabled by setting `this.autoReconnect = false`

4. **Status Indicators**
   - Shows "Connected - Listening..." when WebSocket is open
   - Shows "Disconnected - Reconnecting..." during reconnect
   - Shows WebSocket errors in status bar

### Removed Features
- OBS audio capture (not viable - server has no audio devices)
- Audio source dropdown (only browser mic is supported)
- `sendPCMAudioChunks()` HTTP POST batching logic (no longer needed)

## Benefits Over HTTP POST

### Stability
✅ **Persistent connection** - No repeated connection overhead  
✅ **Better timeout handling** - WebSockets designed for long-lived connections  
✅ **Cloudflare friendly** - WebSockets are better supported than long HTTP POST requests  
✅ **Auto-reconnect** - Automatically recovers from connection drops  

### Performance
✅ **Lower latency** - No batching, immediate streaming  
✅ **Less overhead** - Single connection vs many HTTP requests  
✅ **Bi-directional** - Can send status updates from server to client  

### Reliability
✅ **Connection state** - Always know if connected or not  
✅ **Ping/pong** - Built-in keep-alive mechanism  
✅ **Graceful close** - Proper connection termination  

## How It Works

### Connection Flow
```
1. Browser -> GET /voice/ws (Upgrade: websocket)
2. Server -> 101 Switching Protocols (WebSocket handshake)
3. Connection established ✅
4. Browser sends binary frames (PCM audio)
5. Server processes audio → Whisper → Voice commands
6. Connection stays open until user stops or timeout
```

### Audio Capture Loop
```javascript
ScriptProcessorNode.onaudioprocess (every 85ms)
  ↓
Convert Float32 → Int16 PCM
  ↓
WebSocket.send(pcm.buffer) [Binary frame]
  ↓
Server receives frame
  ↓
process_browser_audio_chunk()
  ↓
Whisper transcription
  ↓
Voice command execution
```

### Reconnection Logic
```
WebSocket.onclose triggered
  ↓
Check if autoReconnect enabled
  ↓
Wait 2 seconds
  ↓
Stop current microphone
  ↓
Wait 1 second
  ↓
Start new microphone + WebSocket
```

## Usage

### Start Voice Commands
1. Open Action UI (http://localhost:8088 or via Cloudflare)
2. Click "🎤 Start Listening"
3. Allow microphone access
4. Status shows "🎤 Connected - Listening..."
5. Speak commands!

### Stop Voice Commands
1. Click "🔴 Stop Listening"
2. WebSocket closes gracefully
3. Microphone access released

## Troubleshooting

### "WebSocket error" in status
- Check browser console for details
- Verify server is running
- Check Cloudflare tunnel is active (if remote)

### Connection keeps dropping
- Check Cloudflare settings (timeout limits)
- Verify network stability
- Check browser console for specific error codes

### No audio being processed
- Check that Whisper model is loaded (see logs)
- Verify microphone permissions granted
- Check audio levels (should see input in browser)
- Look for `[voice-ws]` messages in Docker logs

### Auto-reconnect not working
- Check `this.autoReconnect` is true
- Verify no JavaScript errors in console
- Check that WebSocket close event is firing

## Testing Remote Access

### Through Cloudflare Tunnel
1. Access UI via Cloudflare URL (https://your-domain.com)
2. WebSocket automatically uses `wss://` (secure)
3. Click "Start Listening"
4. Test with various commands
5. Try backgrounding browser tab - should keep working

### Connection Quality Indicators
- **Good**: Steady "Connected" status, commands work consistently
- **Poor**: Frequent "Reconnecting..." messages, delayed responses
- **Failed**: Immediate disconnect, unable to reconnect

## Configuration

### WebSocket Timeout
Change in `handle_voice_websocket()`:
```python
header_bytes = await asyncio.wait_for(reader.readexactly(2), timeout=60.0)
```
Default: 60 seconds. Increase for slower connections.

### Reconnect Delay
Change in `ui_driver_template.html`:
```javascript
setTimeout(() => {
    // ...reconnect logic
}, 2000);  // 2 seconds
```

### Audio Chunk Size
Change in `ui_driver_template.html`:
```javascript
const processor = audioContext.createScriptProcessor(4096, 1, 1);
```
Options: 256, 512, 1024, 2048, 4096, 8192, 16384

Smaller = lower latency, more CPU
Larger = less CPU, higher latency

## Known Limitations

1. **Browser only** - No OBS direct capture (server has no audio hardware)
2. **Single client** - One browser connection at a time
3. **No authentication** - WebSocket upgrade doesn't check token (relying on HTTP auth for /voice/ws path would require custom implementation)
4. **Binary only** - Only handles binary frames, text frames ignored

## Future Improvements

- [ ] Add WebSocket authentication via Sec-WebSocket-Protocol header
- [ ] Send transcription results back to browser via WebSocket
- [ ] Add audio level meter in browser UI
- [ ] Implement exponential backoff for reconnection
- [ ] Add WebSocket compression for lower bandwidth
- [ ] Support multiple simultaneous connections
- [ ] Send keep-alive pings from server

## Migration Notes

### Old HTTP POST Method (Deprecated)
```javascript
// Buffered chunks, sent every 1 second
sendPCMAudioChunks(chunks, sampleRate)
```

### New WebSocket Method
```javascript
// Immediate streaming, sent every ~85ms
websocket.send(pcm.buffer)
```

The HTTP POST endpoint is still available but should be considered deprecated. Once WebSocket proves stable through Cloudflare, the HTTP POST code can be removed.

## Files Modified

- `app/main.py` - Added WebSocket handler and `/voice/ws` endpoint
- `app/ui_driver_template.html` - Replaced HTTP POST with WebSocket streaming
- `Dockerfile` - Removed audio capture packages (not needed)

## Files Removed

- `app/obs_audio_capture.py` - OBS audio capture (not viable)
- `OBS_AUDIO_CAPTURE.md` - Documentation for removed feature
