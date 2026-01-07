# Voice Feature Python Scoping Issue - RESOLVED ✅

## Problem
The `/voice/status` endpoint was returning HTTP 500 error:
```json
{"error": "cannot access local variable 'os' where it is not associated with a value"}
```

## Root Cause
Python's variable scoping rules caused the issue. Two local `import` statements inside the `handle_http()` function:
- Line 7104: `import os` (in `/debug_video` endpoint handler)
- Line 7327: `import os.path` (in `/sounds/` static file handler)

When Python sees ANY import statement for a name inside a function (even if it's in a different branch of if/elif), it treats that name as **local to the entire function**. This meant that attempts to use the globally-imported `os` module (line 8) BEFORE reaching those local imports would fail with "cannot access local variable".

## The Issue Chain
1. Global `import os` at top of file (line 8) ✓
2. `handle_http()` function starts (line 5277)
3. `/voice/status` endpoint tries to call `os.getenv()` (line 6936) ❌ FAILS
4. Later in same function: `import os` (line 7104) and `import os.path` (line 7327)
5. Python sees these future imports and treats `os` as local throughout entire function
6. Using `os` BEFORE it's locally imported = UnboundLocalError

## Solution
Removed the redundant local import statements since `os` was already imported globally:

**File: `app/main.py`**

### Change 1 (Line ~7104)
```diff
  elif path.startswith("/debug_video"):
      try:
-         import os
          from pathlib import Path
```

### Change 2 (Line ~7327)  
```diff
  elif path.startswith("/sounds/"):
-     import os.path
      rel = path[len("/sounds/") :].lstrip("/")
```

## Verification
```bash
# Test endpoint
curl -s http://localhost:8088/voice/status \
  -H "Authorization: Bearer rematch_garage_culinary_unluckily_unclamped_expansive"

# Expected output:
{"enabled": true, "audio_streaming": false, "last_transcription": null}
```

## Key Learnings
1. **Never use local imports for standard library modules** if they're already imported globally
2. **Python scoping is function-wide**, not block-scoped like some languages
3. Local imports anywhere in a function affect the ENTIRE function scope
4. Always check for ALL imports of a name when debugging "local variable" errors

## Status
✅ **FIXED** - Voice status endpoint now working correctly
✅ Voice listener running on GPU (Whisper model loaded)
✅ UDP port 5555 listening for audio stream
✅ UI will now display voice listener status correctly

## Next Steps
1. Test audio streaming with FFmpeg
2. Verify voice commands trigger actions correctly
3. Document final FFmpeg command for user

---
*Fixed: 2026-01-06*
