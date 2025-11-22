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

**Solution**: Enhanced video playback logic in frontend:
- Detects Tenor videos (`tenor.com` or `/dvideos/` URLs)
- For Tenor + audio combinations:
  - Sets `video.loop = true` to repeat the GIF
  - Uses audio duration for total playback time
  - Stops video when audio ends
- For YouTube/other videos: plays once, uses video duration

**Files Changed**:
- `app/overlay_template.html`: Enhanced `loadedHandler()` function with looping logic

## Technical Details

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

### Tenor Looping Logic
```
if (isTenorVideo && hasAudio && audio.duration > video.duration) {
  video.loop = true;
  playback_duration = audio.duration;
  // Stop video when audio ends
}
```

## Benefits

1. **More Accurate Community Voting**: Emoji reactions now properly accumulate as votes
2. **Reduced Repetition**: Popular media won't dominate selections
3. **Better Audio/Video Sync**: Tenor GIFs loop to match audio length
4. **Improved Variety**: Anti-repetition system encourages diverse content
5. **Weighted Fairness**: Recently played content can still be selected, just with lower probability

## Backward Compatibility

- All changes are backward compatible
- No configuration changes required
- Existing Discord cache continues to work
- No breaking changes to API endpoints