# NLTK WordNet Integration

## Status: ✅ INSTALLED

NLTK and WordNet corpus are now included in the Docker image for dynamic synonym generation.

## What Was Added

### Dockerfile Changes
```dockerfile
# Install Python dependencies
RUN pip install --no-cache-dir aiohttp watchdog obsws-python pyyaml yt_dlp nltk

# Download NLTK WordNet corpus for synonym generation
RUN python -c "import nltk; nltk.download('wordnet', quiet=True); nltk.download('omw-1.4', quiet=True)"
```

### What This Provides

1. **WordNet**: Large lexical database of English with ~150,000 words
2. **omw-1.4**: Open Multilingual Wordnet for additional coverage
3. **Automatic fallback**: If WordNet has no synonyms for an action, falls back to curated dictionaries

## How It Works

The synonym generation now uses a **hybrid approach**:

1. **Try WordNet first** - Get natural language synonyms from NLTK
2. **Supplement with curated list** - Add gaming-specific terms
3. **Shuffle for variety** - Randomize order each time

### Example Output

**WordNet synonyms for "kill":**
- DEFEAT
- SHOOT DOWN  
- STAMP OUT
- VOTE OUT
- VOTE DOWN

**Curated gaming synonyms:**
- ELIMINATED
- FRAGGED
- REKT
- OBLITERATED

**Combined result:**
- Mix of both lists gives best variety
- Gaming terms + natural language synonyms
- Total: 10-15 unique words per action

## Verification

```bash
# Build image
docker build -t obs-socket-sentinel .

# Test WordNet inside container
docker run --rm obs-socket-sentinel python -c "
from nltk.corpus import wordnet
synsets = wordnet.synsets('kill', pos=wordnet.VERB)
print(f'WordNet found {len(synsets)} synonym sets for kill')
"
```

## Image Size Impact

- **NLTK package**: ~3 MB
- **WordNet corpus**: ~10 MB
- **Total addition**: ~13 MB (minimal impact)

## Benefits

✅ **Richer synonyms**: Natural language variations from WordNet  
✅ **Gaming terms preserved**: Curated list still used for slang  
✅ **Better variety**: More unique words per action  
✅ **Fallback safe**: Works even if WordNet has no results  
✅ **Zero runtime cost**: Corpus downloaded during build

## Examples with WordNet

### "kill" action
WordNet: DEFEAT, SHOOT DOWN, STAMP OUT, VOTE OUT, VOTE DOWN  
Curated: ELIMINATED, DOWNED, SLAIN, FRAGGED, REKT  
**Combined**: DEFEAT, ELIMINATED, SHOOT DOWN, FRAGGED, STAMP OUT...

### "revive" action  
WordNet: REVIVIFY, RECREATE, REPAIR, RENOVATE, COME TO  
Curated: RESURRECTED, RESTORED, SAVED, HEALED  
**Combined**: REVIVIFY, RESURRECTED, RECREATE, RESTORED, REPAIR...

### "death" action
WordNet: (falls back to curated - "death" is a noun)  
Curated: FALLEN, PERISHED, EXPIRED, DECEASED, FLATLINED  
**Combined**: Uses curated list exclusively

## Logs

With WordNet enabled, you'll see:
```
[synonyms] Found 5 WordNet synonyms for 'kill'
[synonyms] Generated 10 synonyms for 'kill': ['DEFEAT', 'SHOOT DOWN', ...]
```

Without WordNet (shouldn't happen in Docker):
```
[synonyms] NLTK not available, using fallback dictionary
[synonyms] Generated 10 synonyms for 'kill': ['ELIMINATED', 'DOWNED', ...]
```

## No Action Required

The Docker image will automatically include NLTK and WordNet on next build. No configuration changes needed - the code already handles both WordNet and fallback scenarios gracefully.
