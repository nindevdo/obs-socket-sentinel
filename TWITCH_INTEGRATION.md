# Twitch API Integration

## Overview
Integrated Twitch API to create stream markers and clips with contextual descriptions extracted from voice commands.

## Features Implemented

### 1. Twitch Stream Markers
- Automatically creates Twitch stream markers when saying "clip that", "mark this", etc.
- Marker descriptions are extracted from the voice transcription buffer
- Supports up to 140 characters (Twitch limit)

### 2. Twitch Clip Creation
- Automatically creates Twitch clips with the same voice command
- Returns clip edit URL for easy access
- Uses the same contextual description as markers

### 3. Context Extraction
- Extracts surrounding speech before "clip that" phrase
- Example: "that was an insane headshot clip that" → Description: "that was an insane headshot"
- Falls back to "Highlight" if no context found
- Truncates long descriptions intelligently (keeps last ~120 chars with "..." prefix)

### 4. Multi-Platform Support
- Works with local replay buffer (saves if active)
- Works with Twitch streaming (creates markers + clips)
- Can work with both simultaneously

## Configuration

### Environment Variables (.env)
```bash
# Get these from https://dev.twitch.tv/console/apps
TWITCH_API_CLIENT_ID=your_twitch_client_id
TWITCH_API_CLIENT_SECRET=your_twitch_client_secret

# Your Twitch channel user ID (numeric)
# Get from: https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/
TWITCH_BROADCASTER_ID=your_broadcaster_id
```

### How to Get Credentials

1. **Client ID & Secret:**
   - Go to https://dev.twitch.tv/console/apps
   - Click "Register Your Application"
   - Name: "OBS Socket Sentinel" (or anything)
   - OAuth Redirect URLs: `http://localhost`
   - Category: "Application Integration"
   - Click "Create"
   - Copy the Client ID
   - Click "New Secret" and copy the Client Secret

2. **Broadcaster ID:**
   - Go to https://www.streamweasels.com/tools/convert-twitch-username-to-user-id/
   - Enter your Twitch username
   - Copy the numeric User ID

## Usage

### Voice Commands
Say any of these phrases while streaming:
- "clip that"
- "clip this"
- "mark this"
- "bookmark"
- "highlight"

### Example Scenarios

**Scenario 1: Gaming highlight**
```
You say: "that was sick clip that"
Result:
- ✅ Replay buffer saved (if active)
- ✅ Twitch marker created: "that was sick"
- ✅ Twitch clip created: "that was sick"
```

**Scenario 2: Coding moment**
```
You say: "finally got it working after two hours clip that"
Result:
- Description: "finally got it working after two hours"
- Creates marker + clip with that description
```

**Scenario 3: No context**
```
You say: "clip that" (nothing before it)
Result:
- Description: "Highlight" (generic fallback)
```

## Technical Details

### Files Modified

1. **app/obs_controller.py**
   - Added Twitch API imports
   - Updated `create_stream_marker()` to call Twitch APIs
   - Added `description` parameter to `handle_obs_action()`
   - Integrated marker and clip creation with context

2. **app/main.py**
   - Added `extract_context_from_buffer()` function
   - Modified OBS action handler to extract context
   - Passes context to `handle_obs_action()`

3. **app/twitch_api.py**
   - OAuth client credentials flow
   - `create_twitch_stream_marker()` - POST to Twitch markers API
   - `create_twitch_clip()` - POST to Twitch clips API
   - Token caching to avoid repeated OAuth requests

4. **docker-compose.yml**
   - Added Twitch environment variables

### Flow Diagram
```
Browser → Audio → Whisper → Transcription Buffer
                                    ↓
                          "great play clip that"
                                    ↓
                    Voice Command Parser (detects "clip that")
                                    ↓
                    Context Extractor (gets "great play")
                                    ↓
                    handle_obs_action(action="obs_clip_that", description="great play")
                                    ↓
                    create_stream_marker(description="great play")
                                    ↓
            ┌───────────────────────┼───────────────────────┐
            ↓                       ↓                       ↓
    Save Replay Buffer    Create Twitch Marker    Create Twitch Clip
       (if active)           (if streaming)          (if streaming)
```

### Error Handling
- Gracefully handles missing credentials (logs warning)
- Continues to save replay buffer even if Twitch API fails
- Works offline (only local replay buffer)
- Supports streaming without replay buffer

### Logging
- `✅ Twitch stream marker created: <description>`
- `🎬 Twitch clip created: <edit_url>`
- `⚠️ Twitch marker creation failed (check credentials/stream)`
- `📝 Extracted context: '<description>'`

## Testing

### Test Without Streaming
1. Enable replay buffer in OBS
2. Say "test clip that"
3. Check logs for replay buffer save
4. Twitch API calls will be skipped (not streaming)

### Test With Streaming
1. Start streaming to Twitch
2. Enable replay buffer (optional)
3. Say "amazing moment clip that"
4. Check logs for:
   - Replay buffer save
   - Twitch marker creation
   - Twitch clip creation with edit URL
5. Check Twitch dashboard for marker and clip

### Test Context Extraction
```python
# In Python shell or test script
transcription_buffer = [
    ("that was an insane", 1234567890.0),
    ("headshot clip that", 1234567891.0)
]

description = extract_context_from_buffer("headshot clip that")
# Should return: "that was an insane headshot"
```

## Limitations

1. **Twitch Markers:**
   - Only work during live streams
   - Limited to 140 characters
   - Require valid OAuth credentials

2. **Twitch Clips:**
   - Only work during live streams
   - Clip creation is asynchronous (202 Accepted)
   - Clip might not be available immediately
   - 1000 clips per 24 hours (Twitch rate limit)

3. **Context Extraction:**
   - Limited to 3-second transcription buffer
   - Relies on accurate Whisper transcription
   - May miss context if speech is split across too many chunks

## Troubleshooting

### Marker/Clip Creation Fails
- Check if you're actually streaming to Twitch
- Verify credentials in `.env` are correct
- Check container logs: `docker compose logs -f obs-socket-sentinel`
- Verify broadcaster ID matches your Twitch username

### No Context Extracted
- Check transcription buffer in logs
- Verify "clip that" phrase is detected
- Ensure previous speech is within 3-second window

### OAuth Errors
- Regenerate client secret in Twitch developer console
- Update `.env` and restart container
- Check Twitch app is not suspended

## Future Enhancements

- [ ] YouTube live stream marker integration
- [ ] Custom marker categories/tags
- [ ] Clip duration control ("30 second clip")
- [ ] Automatic clip upload to Discord/Twitter
- [ ] Marker timeline visualization in overlay
- [ ] Voice command to retrieve last clip URL
