# Dynamic Synonym Burst Words

## Overview

The overlay now displays **dynamic synonyms** for action words instead of repeatedly showing the same word. When a video plays with burst words enabled, each burst will show a different synonym related to the action (e.g., "ELIMINATED", "DESTROYED", "OBLITERATED" for "kill").

## How It Works

### Backend (Python)

1. **Synonym Generation** (`get_synonyms_for_action()`):
   - Attempts to use NLTK WordNet for natural language synonyms (if installed)
   - Falls back to curated game-action dictionaries
   - Returns shuffled list of 10-15 synonyms per action
   - Caches results per overlay update

2. **Curated Dictionaries**:
   - Pre-defined synonym lists for common game actions
   - Optimized for gaming terminology (e.g., "REKT", "FRAGGED", "DOMED")
   - Includes slang and gaming culture words

### Frontend (JavaScript)

1. **Synonym Cycling**:
   - Receives array of synonyms from backend
   - Cycles through synonyms sequentially with each burst
   - Resets to beginning when new action triggered
   - Falls back to original action word if no synonyms available

2. **Visual Display**:
   - Each burst word appears at random position
   - Random size (2-6rem)
   - Random animation duration (0.55-1.0s)
   - Same styling as before, just varied text

## Action Synonym Dictionaries

### Kill
`["ELIMINATED", "DOWNED", "SLAIN", "DEFEATED", "DESTROYED", "WASTED", "FRAGGED", "REKT", "OBLITERATED", "TERMINATED"]`

### Death
`["FALLEN", "PERISHED", "EXPIRED", "DECEASED", "ELIMINATED", "TERMINATED", "FLATLINED", "DOWN", "TOAST", "DONE"]`

### Headshot
`["HEADPOP", "CRANKED", "DOMED", "NOGGIN HIT", "BRAIN SHOT", "HEAD TAP", "SCALPED", "POPPED", "CRITICAL", "PRECISION"]`

### Downed
`["KNOCKED", "DROPPED", "FLOORED", "GROUNDED", "DOWN", "INCAPACITATED", "CRAWLING", "WOUNDED", "HURT", "DAMAGED"]`

### Revive
`["RESURRECTED", "RESTORED", "SAVED", "RECOVERED", "HEALED", "BACK UP", "HELPED", "ASSISTED", "RESCUED", "RENEWED"]`

### Funny
`["HILARIOUS", "LMAO", "LOL", "COMEDY", "JOKES", "HAHA", "ROFL", "KEK", "WILD", "BRUH"]`

### Banish
`["EXORCISED", "EXPELLED", "REMOVED", "ERASED", "PURGED", "CLEANSED", "VANISHED", "GONE", "SENT AWAY", "DISMISSED"]`

### Extraction
`["ESCAPED", "EVACUATED", "EXTRACTED", "SURVIVED", "BAILED", "LEFT", "DEPARTED", "FLED", "MADE IT", "OUT"]`

### Undo
`["REVERSED", "REVERTED", "CANCELLED", "UNDONE", "ROLLED BACK", "FIXED", "CORRECTED", "OOPS", "NEVERMIND", "MISTAKE"]`

### Clear
`["RESET", "WIPED", "CLEARED", "CLEANED", "ERASED", "FRESH START", "NEW", "BLANK", "ZERO", "RESTART"]`

## Example Flow

1. User triggers "kill" action via HTTP endpoint
2. Backend generates synonyms:
   ```python
   synonyms = ["OBLITERATED", "DOWNED", "ELIMINATED", "DESTROYED", "WASTED", ...]
   ```
3. Synonyms sent to frontend via `/overlay` API:
   ```json
   {
     "action": "kill",
     "synonyms": ["OBLITERATED", "DOWNED", "ELIMINATED", ...],
     ...
   }
   ```
4. During video playback, burst words appear:
   - First burst: "OBLITERATED" 💥
   - Second burst: "DOWNED" 💥
   - Third burst: "ELIMINATED" 💥
   - And so on...

## Code Changes

### Backend (`app/main.py`)

- Added `ACTION_SYNONYMS` dictionary with game-action synonyms
- Added `get_synonyms_for_action()` function
- Added `last_synonyms` global variable
- Updated `update_live_overlay()` to generate synonyms
- Updated `/overlay` endpoint to include `synonyms` in JSON

### Frontend (`app/overlay_template.html`)

- Added `wordBurstSynonyms` and `synonymIndex` variables
- Modified `spawnBurstWord()` to cycle through synonyms
- Updated `pollOverlay()` to receive and store synonyms

## NLTK Integration (Optional)

If you want even more dynamic synonyms using natural language processing:

```bash
# Install NLTK
pip install nltk

# Download WordNet corpus (run once)
python3 -c "import nltk; nltk.download('wordnet')"
```

With NLTK installed:
- WordNet synonyms generated dynamically
- Falls back to curated lists if WordNet has no matches
- Combines WordNet + curated for best variety

**Note**: The system works perfectly fine without NLTK using the curated dictionaries.

## Benefits

✅ **Variety**: Never see the same word twice in succession  
✅ **Engaging**: More dynamic and entertaining visual feedback  
✅ **Gaming Culture**: Includes popular gaming slang and terminology  
✅ **Fallback Safe**: Always has synonyms via curated dictionaries  
✅ **Minimal Overhead**: Synonyms generated once per action, cached  
✅ **Extensible**: Easy to add new actions and synonyms

## Adding Custom Synonyms

To add synonyms for a new action, edit `ACTION_SYNONYMS` in `app/main.py`:

```python
ACTION_SYNONYMS = {
    # ... existing entries ...
    "your_action": ["SYNONYM1", "SYNONYM2", "SYNONYM3", ...],
}
```

Tips:
- Use ALL CAPS for consistency
- 10-15 synonyms per action is ideal
- Mix formal and slang terms
- Consider gaming culture references
- Keep words short (2-3 syllables works best visually)

## Performance

- **Memory**: ~1KB per action (10 synonyms × ~10 chars each)
- **CPU**: Negligible (simple list operations)
- **Network**: ~200 bytes added to `/overlay` API response
- **No impact** on video playback or animation performance

## Future Enhancements

Possible improvements:
- Add more actions (assists, objectives, etc.)
- Language localization (Spanish, French, etc.)
- User-customizable synonym lists via config
- Weighted synonym selection (prefer certain words)
- Context-aware synonyms (different words based on game state)
