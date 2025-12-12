## Visual Example: Before vs After

### Before (Same Word Repeatedly)
```
Video starts playing...

💥 KILL! 💥
        💥 KILL! 💥
   💥 KILL! 💥
             💥 KILL! 💥
   💥 KILL! 💥
```

### After (Dynamic Synonyms)
```
Video starts playing...

💥 OBLITERATED! 💥
        💥 DOWNED! 💥
   💥 ELIMINATED! 💥
             💥 DESTROYED! 💥
   💥 WASTED! 💥
        💥 FRAGGED! 💥
   💥 REKT! 💥
             💥 SLAIN! 💥
```

## Test It Out

1. **Start the application**:
   ```bash
   make dev
   ```

2. **Trigger an action**:
   ```bash
   curl -X POST http://localhost:8888/action/kill/hunt_showdown
   ```

3. **Watch the overlay** - you should see different synonyms appear with each beat of the video!

## Checking the Logs

When an action is triggered, you'll see log entries like:

```
[synonyms] Generated 10 synonyms for 'kill': ['OBLITERATED', 'DOWNED', 'ELIMINATED', 'DESTROYED', 'WASTED']...
[video_cycle] Selected '/dvideos/abc123.mp4' (weight=2.0) - progress: 1/15 in cycle #1
```

In the browser console (overlay page), you'll see:

```
[synonyms] Loaded 10 synonyms: ["OBLITERATED", "DOWNED", "ELIMINATED", "DESTROYED", "WASTED"]
```

## Customization Example

Want to add synonyms for a new action like "assist"? Add to `ACTION_SYNONYMS` in `app/main.py`:

```python
ACTION_SYNONYMS = {
    # ... existing entries ...
    "assist": ["TEAMWORK", "SUPPORT", "BACKUP", "HELPED", "COORDINATED", "COMBO", "SYNERGY", "CLUTCH", "SAVED", "COVERED"],
}
```

Now assists will show varied words like "TEAMWORK!", "SUPPORT!", "BACKUP!" instead of just "ASSIST!" every time.

## Performance Notes

- Synonyms are generated **once** when action is triggered
- No performance impact during video playback
- Words cycle through sequentially (no repeated lookups)
- Fallback dictionaries are in-memory (no file I/O)

## Browser Compatibility

Works in all modern browsers:
- ✅ Chrome/Edge
- ✅ Firefox
- ✅ Safari
- ✅ OBS Browser Source
