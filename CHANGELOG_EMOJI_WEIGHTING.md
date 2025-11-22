# Emoji Weighting & Tenor Looping Improvements

## Changes Made

### 1. Fixed Emoji Reaction Weighting System
**Problem**: Previously used `max(match_weight, count)` which only took the highest emoji count instead of treating emoji reactions as votes.

**Solution**: Changed to `match_weight += count` to sum all matching emoji reactions, creating a proper voting system where:
- More emoji reactions = higher weight/probability
- Each emoji reaction adds to the total "vote count" for that piece of media
- Media with more community engagement (emoji reactions) is more likely to be selected

**Files Changed**:
- `app/main.py`: Updated all media selection functions:
  - `get_cached_discord_sound()`
  - `get_cached_discord_meme()`
  - `get_cached_discord_video()`
  - `fetch_random_discord_meme()`
  - `fetch_random_discord_video()`
  - `fetch_random_discord_sound()`

### 2. Implemented Anti-Repetition System
**Problem**: Same popular media could be selected repeatedly, making the overlay feel stale.

**Solution**: Added tracking system to reduce weights of recently played media:
- Tracks last 5 played items per action type
- Applies penalties based on recency (most recent = highest penalty)
- Penalty scale: 20%, 35%, 50%, 65%, 80% of original weight

**New Functions**:
- `apply_anti_repetition_weighting()`: Reduces weights for recently played media
- `track_played_media()`: Maintains rolling history per action

**New Global Variables**:
- `recent_media_history`: Dict storing recent media per action
- `RECENT_MEDIA_HISTORY_SIZE = 5`: History size limit

### 3. Fixed Tenor Video Looping for Audio Sync
**Problem**: Tenor GIF videos would play once and stop, even if audio was longer.

**Solution**: Enhanced video playback logic in both backend and frontend:
- **Backend**: Proper media pairing logic that distinguishes:
  - Tenor videos (silent GIFs) → pair with Discord audio
  - YouTube videos (have audio) → use video's own audio, no external audio
- **Frontend**: Smart audio handling that:
  - Only applies Discord audio to Tenor videos
  - Loops Tenor videos to match audio duration
  - Mutes external audio for YouTube videos
  - Uses video's natural audio for YouTube content

**Files Changed**:
- `app/main.py`: Enhanced `pick_media_for_action()` with proper video type detection
- `app/overlay_template.html`: Enhanced video playback logic with audio type awareness

### 4. Improved Media Selection Logic
**Problem**: All videos were treated the same, causing audio conflicts.

**Solution**: Implemented smart media pairing:
- **YouTube Mode**: Video plays with its own audio, no external Discord audio
- **Tenor + Audio Mode**: Tenor video loops with Discord audio sync
- **Tenor Silent Mode**: Tenor video plays once without audio
- **GIF + Audio Mode**: Traditional static GIF with Discord audio

**Selection Priorities**:
1. Tenor + Discord Audio (highest preference)
2. YouTube videos (second preference) 
3. GIF + Audio combinations (third preference)
4. Silent Tenor videos (lowest preference)

## Technical Details

### Media Pairing Logic
```python
# Detect video type using original source URL (tracked during caching)
# Backend now returns: (cached_path, duration, original_source_url)
if video and original_video_url:
    if YOUTUBE_RE.search(original_video_url):
        is_youtube_video = True  # YouTube videos
    else:
        is_tenor_video = True    # Tenor, Discord attachments, etc.

# Pairing rules:
# 1. YouTube videos → use video's own audio, no external audio
# 2. Tenor videos → can pair with Discord audio  
# 3. Static GIFs → can pair with Discord audio
```

### Emoji Voting Weight Formula
```
For each message with matching action emoji:
total_weight = sum(reaction.count for reaction in matching_reactions)
```

### Anti-Repetition Weight Formula
```
For recently played media:
penalty_factor = 1.0 - (0.8 - (recency_index * 0.15))
adjusted_weight = original_weight * max(0.2, penalty_factor)

Where recency_index: 0 = most recent, 4 = oldest in history
```

### Frontend Audio Logic
```javascript
// Backend now sends proper audio pairing, so detection is simple
const hasExternalAudio = !!soundUrl && soundUrl.trim() !== '';
const isTenorVideo = hasExternalAudio;   // Discord audio = Tenor video
const isYouTubeVideo = !hasExternalAudio && hasVideo; // No external audio = YouTube

if (isTenorVideo && hasExternalAudio) {
  // Loop Tenor video to match Discord audio length
  video.loop = true;
  playback_duration = discord_audio.duration;
} else if (isYouTubeVideo) {
  // Use video's own audio, ignore any external audio
  video.loop = false;
  playback_duration = video.duration;
}
```

## Benefits

1. **Proper Audio/Video Separation**: YouTube videos use their own audio, Tenor GIFs pair with Discord audio
2. **More Accurate Community Voting**: Emoji reactions now properly accumulate as votes
3. **Reduced Repetition**: Popular media won't dominate selections
4. **Better Audio/Video Sync**: Tenor GIFs loop to match audio length
5. **Improved Variety**: Anti-repetition system encourages diverse content
6. **No Audio Conflicts**: Clear separation between video types prevents audio overlap

## Testing

All changes tested using Docker container:
- ✅ Python syntax validation
- ✅ HTML template validation  
- ✅ Module import verification
- ✅ Docker build compatibility

## Backward Compatibility

- All changes are backward compatible
- No configuration changes required
- Existing Discord cache continues to work
- No breaking changes to API endpoints