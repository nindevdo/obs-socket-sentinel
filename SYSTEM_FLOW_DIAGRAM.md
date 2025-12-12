# System Flow: Video Cycle + Synonym Burst Words

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  USER TRIGGERS ACTION                                           │
│  curl -X POST /action/kill/hunt_showdown                        │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│  BACKEND: update_live_overlay()                                 │
├─────────────────────────────────────────────────────────────────┤
│  1. Increment kill counter                                      │
│  2. Generate synonyms (WordNet + curated)                       │
│     └─> ["OBLITERATED", "DOWNED", "ELIMINATED", ...]           │
│  3. Select video from cycle pool                                │
│     └─> Check cycle state for "kill" action                     │
│     └─> Get unplayed video from current cycle                   │
│     └─> Mark as played, track progress                          │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│  VIDEO CYCLE POOL (for "kill" action)                           │
├─────────────────────────────────────────────────────────────────┤
│  Cycle #1: [Video_A, Video_A, Video_B, Video_B, Video_C, ...]  │
│            └─────┘   └─────┘   └─────┘   └─────┘   └────┘      │
│            weight=2  weight=2  weight=2  weight=2  weight=1     │
│                                                                  │
│  Remaining: [Video_B, Video_C, Video_D, ...]                    │
│  Already Played: [Video_A]                                      │
│                                                                  │
│  When all slots played → Start Cycle #2                         │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│  OVERLAY API: /overlay                                          │
├─────────────────────────────────────────────────────────────────┤
│  {                                                               │
│    "action": "kill",                                             │
│    "text": "💀 kill x3",                                         │
│    "video": "/dvideos/abc123.mp4",                              │
│    "video_duration": 10.5,                                       │
│    "synonyms": ["OBLITERATED", "DOWNED", "ELIMINATED", ...],    │
│    ...                                                           │
│  }                                                               │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│  FRONTEND: overlay_template.html                                │
├─────────────────────────────────────────────────────────────────┤
│  1. Receive overlay update                                      │
│  2. Store synonyms array                                        │
│  3. Load video and start playback                               │
│  4. Start audio analysis (detect beats)                         │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────┐
│  BURST WORD ANIMATION (during video playback)                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Beat 1 detected (t=0.5s)                                       │
│  └─> spawnBurstWord()                                           │
│      └─> synonyms[0] = "OBLITERATED"                            │
│      └─> Display at random position with animation              │
│                                                                  │
│  Beat 2 detected (t=1.2s)                                       │
│  └─> spawnBurstWord()                                           │
│      └─> synonyms[1] = "DOWNED"                                 │
│      └─> Display at random position                             │
│                                                                  │
│  Beat 3 detected (t=2.0s)                                       │
│  └─> spawnBurstWord()                                           │
│      └─> synonyms[2] = "ELIMINATED"                             │
│      └─> Display at random position                             │
│                                                                  │
│  ... continues cycling through synonym array ...                │
│                                                                  │
│  Visual result:                                                  │
│     💥 OBLITERATED! 💥                                           │
│             💥 DOWNED! 💥                                        │
│        💥 ELIMINATED! 💥                                         │
│                   💥 DESTROYED! 💥                               │
│     💥 WASTED! 💥                                                │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## Key Integration Points

### 1. Video Selection (Cycle-Based)
- **State**: Per-action cycle tracking
- **Logic**: Fair rotation, weighted repetition
- **Result**: No video plays twice until all have played once

### 2. Synonym Generation (Hybrid)
- **Source 1**: NLTK WordNet (natural language)
- **Source 2**: Curated dictionaries (gaming slang)
- **Result**: 10-15 unique words per action, shuffled

### 3. Burst Word Display (Sequential)
- **Input**: Synonym array from backend
- **Trigger**: Audio beat detection
- **Output**: Different word each burst
- **Cycle**: Wraps around when array exhausted

## State Management

```
Backend State (per action):
├─ video_cycle_state["kill"]
│  ├─ pool: [(url, weight, duration, orig), ...]
│  ├─ remaining: [(url, weight, duration, orig), ...]
│  └─ cycle_number: 1
│
└─ last_synonyms
   └─ ["OBLITERATED", "DOWNED", ...]

Frontend State:
├─ wordBurstSynonyms: ["OBLITERATED", "DOWNED", ...]
└─ synonymIndex: 0 → 1 → 2 → ... (increments each burst)
```

## Example Session

```
Action 1: kill
├─ Backend: Select Video_A (cycle 1/15), Generate synonyms
├─ Frontend: Show "OBLITERATED", "DOWNED", "ELIMINATED"...
└─ Video plays for 10s with 8 different burst words

Action 2: kill (30 seconds later)
├─ Backend: Select Video_B (cycle 2/15), Generate NEW synonyms
├─ Frontend: Show "FRAGGED", "REKT", "DESTROYED"...
└─ Video plays for 8s with 6 different burst words

Action 3: kill (2 minutes later)
├─ Backend: Select Video_C (cycle 3/15), Generate NEW synonyms
├─ Frontend: Show "SLAIN", "TERMINATED", "WASTED"...
└─ Video plays for 12s with 10 different burst words

... continues through all 15 videos in cycle ...

Action 16: kill
├─ Backend: Cycle complete! Start Cycle #2, Select Video_A again
├─ Frontend: NEW synonyms, fresh variety
└─ Different experience than first time Video_A played
```

## Benefits of Combined System

✅ **Video Variety**: All videos rotate fairly before repeating
✅ **Word Variety**: 10-15 unique burst words per action
✅ **Weighted Balance**: Popular videos play more, but not excessively
✅ **Fresh Experience**: Each action feels unique even with same video
✅ **Predictable**: No random spikes, smooth distribution
✅ **Engaging**: Dynamic text + fair rotation = better viewing experience

## Performance Characteristics

- **Video Selection**: O(1) random choice from remaining list
- **Synonym Generation**: O(n) where n=number of synonyms (10-15)
- **Burst Display**: O(1) array lookup
- **Memory**: ~1KB per action for cycle state + synonyms
- **Network**: ~200 bytes additional per API call
- **CPU**: Negligible impact during playback
