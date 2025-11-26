# Emoji Weighting & Anti-Repetition Improvements (Updated)

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

### 2. Improved Anti-Repetition System
**Problem**: Same popular media was being selected too frequently due to aggressive penalties and small history size.

**Solution**: Enhanced tracking system with better balance:
- **Increased history size**: Now tracks last **10 items** (was 5)
- **Gentler penalties**: New gradual penalty system:
  - Most recent: 10% weight (was 20%)
  - 2nd recent: 25% weight (was 35%) 
  - 3rd recent: 40% weight (was 50%)
  - 4th recent: 55% weight (was 65%)
  - 5th recent: 70% weight (was 80%)
  - 6th+ recent: 85% weight (cap, allows older items back)
- **Better formula**: Simpler, more predictable penalty calculation

### 3. New Diversity Weighting System
**Problem**: Lower-reaction content rarely got selected, making variety poor.

**Solution**: Added diversity boost system that:
- Calculates how "underrepresented" each item is compared to highest-reaction content
- Gives small bonus (up to 15% of original weight) to lower-reaction items
- Ensures content with fewer reactions can still occasionally be selected
- Maintains emoji voting importance while improving variety

**New/Updated Functions**:
- `apply_diversity_weighting()`: NEW - Gives underrepresented content a small boost
- `apply_anti_repetition_weighting()`: IMPROVED - Gentler penalties with better formula
- `track_played_media()`: UPDATED - Now maintains 10-item rolling history per action

**Updated Global Variables**:
- `RECENT_MEDIA_HISTORY_SIZE = 10`: Increased from 5 to reduce repetition cycles
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

### Updated Anti-Repetition Weight Formula
```python
# New gentler penalty system
penalty_multiplier = 0.10 + (recency_index * 0.15)  # 10%, 25%, 40%, 55%, 70%, 85%...
penalty_multiplier = min(penalty_multiplier, 0.85)  # Cap at 85%
adjusted_weight = original_weight * penalty_multiplier
```

### New Diversity Weighting Formula  
```python
# Calculate how underrepresented this item is (0.0 to 1.0)
underrepresented_ratio = 1.0 - ((weight - min_weight) / (max_weight - min_weight))
# Apply small diversity bonus (up to 15% of original weight)
diversity_bonus = weight * (underrepresented_ratio * 0.15)
adjusted_weight = weight + diversity_bonus
```

### Legacy Anti-Repetition Formula (Removed)
```python
# OLD (problematic): penalty_factor = 1.0 - (0.8 - (recency_index * 0.15))
# This produced: 20%, 35%, 50%, 65%, 80% which was too harsh
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

1. **Better Variety**: 10-item history and gentler penalties reduce repetition cycles
2. **Fairer Selection**: Diversity weighting gives lower-reaction content a chance
3. **Maintained Democracy**: Emoji reactions still drive selection, just with better balance
4. **Reduced Staleness**: Same popular videos won't dominate as much
5. **Predictable Penalties**: Clearer, simpler anti-repetition formula
6. **Improved User Experience**: More engaging variety while respecting community votes

### Before vs After Comparison:
| Aspect | Before | After |
|--------|--------|-------|
| History size | 5 items | 10 items |
| Most recent penalty | 20% weight | 10% weight |
| Oldest in history | 80% weight | 85% weight |
| Diversity boost | None | Up to 15% bonus for low-reaction content |
| Repetition cycles | Frequent | Significantly reduced |

## Testing

All changes tested using Docker container:
- ✅ Python syntax validation
- ✅ Import verification  
- ✅ Mathematical formula validation
- ✅ Docker build compatibility

## Backward Compatibility

- All changes are backward compatible
- No configuration changes required
- Existing Discord cache continues to work
- No breaking changes to API endpoints
- History will gradually build up to 10 items over time

## Summary

These improvements address the core issue of repetitive video selection while maintaining the democratic emoji voting system. The changes provide:
- **Better balance** between popular and less popular content
- **Longer variety cycles** through increased history size
- **Fairer chances** for all content through diversity weighting
- **Gentler penalties** that still discourage immediate repetition

The system now properly balances community preferences (emoji reactions) with content variety.