# Video Cycle Rotation System

## Overview

Implemented a smart video rotation system that cycles through all available videos before repeating, with weighted videos appearing more frequently in a balanced way.

## The Problem

Previously, video selection used weighted random selection with anti-repetition penalties. This meant:
- Popular videos (with many emoji reactions) could still play too frequently
- No guarantee all videos would be seen before repeats
- Unpredictable rotation patterns

Example: With 10 videos where 5 have 2 "kill" reactions and 5 have 1 reaction, the same high-weight video could theoretically play multiple times while some low-weight videos never played.

## The Solution

### Cycle-Based Rotation

Videos are now organized into **cycles**. Each cycle is a "pool" of video slots:
- Each unique video gets at least 1 slot in the pool
- Videos with higher emoji weights get additional slots (up to 3x max)
- All slots in the pool must be used before the cycle repeats

### Weight-to-Slots Formula

```python
# Videos with minimum weight appear once per cycle
min_weight = min(all_video_weights)

# Higher-weighted videos appear proportionally more
repetitions = round(video_weight / min_weight)
repetitions = min(repetitions, 3)  # Cap at 3x to prevent domination
```

### Example Scenarios

#### Scenario 1: 10 videos, 5 with double weight
- 5 videos with 2 reactions → 2 slots each = 10 slots
- 5 videos with 1 reaction → 1 slot each = 5 slots
- **Total cycle: 15 slots**

In 3 complete cycles (45 selections):
- High-weight videos: 6 plays each (30 total)
- Low-weight videos: 3 plays each (15 total)
- **Ratio: exactly 2:1** ✅

#### Scenario 2: 3 videos with weights 3, 2, 1
- Video A (weight 3) → 3 slots
- Video B (weight 2) → 2 slots  
- Video C (weight 1) → 1 slot
- **Total cycle: 6 slots**

In 2 complete cycles (12 selections):
- Video A: 6 plays
- Video B: 4 plays
- Video C: 2 plays
- **Perfect proportional distribution** ✅

#### Scenario 3: Equal weight videos
- All videos have 1 slot each
- **Guarantees each video plays once before any repeat** ✅

## Implementation Details

### Data Structure

```python
video_cycle_state: Dict[str, Dict] = {
    "action_key": {
        "pool": [(url, weight, duration, original_url), ...],      # Full cycle slots
        "remaining": [(url, weight, duration, original_url), ...], # Unplayed slots
        "cycle_number": 1                                          # Current cycle
    }
}
```

### Selection Algorithm

1. **Check if cycle needs initialization**
   - First time for this action
   - Available videos changed

2. **Select from remaining slots**
   - Random choice from `remaining` list
   - Equal probability for all remaining slots
   - Remove selected slot from `remaining`

3. **Cycle completion**
   - When `remaining` is empty, reset to full `pool`
   - Increment cycle number
   - Continue selection

### Key Benefits

✅ **Predictable rotation**: All videos play before repeats  
✅ **Fair weighting**: High-reaction videos play more, but proportionally  
✅ **No domination**: Single video can't play back-to-back (max 3x per cycle)  
✅ **Variety**: Lower-weighted content still gets screen time  
✅ **Transparent**: Logs show cycle progress and video distribution

## Code Changes

### Modified Files

- `app/main.py`:
  - Added `video_cycle_state` global dictionary
  - Added `build_video_cycle_pool()` function
  - Modified `get_cached_discord_video_with_weight()` to use cycle-based selection
  - Updated comments on `apply_anti_repetition_weighting()` (now mainly for non-video media)

### New Test File

- `test_video_cycle.py`: Comprehensive test suite validating the cycle logic

## Migration Notes

- Existing video selection code is completely replaced
- No data migration needed (state is in-memory)
- Backward compatible with existing emoji weighting in config
- Legacy `recent_media_history` still tracked for non-video media

## Logging

New log messages help track cycle behavior:

```
[video_cycle] Built pool for kill: 15 slots from 10 unique videos
[video_cycle]   video_0_high: weight=2.0, appears 2x in cycle
[video_cycle]   video_0_low: weight=1.0, appears 1x in cycle
[video_cycle] Created new cycle #1 for kill with 15 slots
[video_cycle] Selected 'video_0_low' (weight=1.0) - progress: 1/15 in cycle #1
[video_cycle] Cycle complete! Starting cycle #2 for kill
```

## Performance

- **Memory**: O(n) where n = number of unique videos per action
- **Selection**: O(1) random selection from remaining list
- **No additional network calls**: Works with existing cached videos
- **Minimal CPU overhead**: Simple list operations

## Future Enhancements

Possible improvements:
- Add cycle stats to `/overlay` API for UI display
- Configurable max repetitions per cycle (currently hardcoded at 3)
- Option to force minimum spacing between same video plays
- Cycle reset on video pool changes (already implemented)
