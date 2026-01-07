# Voice Commands for Socket Sentinel

## Overview
Voice command feature allows you to trigger actions using your voice instead of clicking buttons. Speech recognition runs **locally** using Whisper AI (no external API required).

## How It Works
1. **Access the UI**: Navigate to https://ss.nindevdo.com/ui
2. **Grant Microphone Permission**: Browser will ask for mic access
3. **Hold to Speak**: Click and hold the "Hold to Speak" button
4. **Say Your Command**: Speak clearly (e.g., "kill", "death", "headshot")
5. **Release**: Let go of the button to process the command

## Supported Commands

### Common Actions (all games)
- **kill** - Triggers kill action
- **death** / "died" / "I died" - Triggers death action
- **clear** / "cleared" / "all clear" - Clears overlay

### Hunt Showdown Specific
- **headshot** / "dome" / "domed" - Headshot action
- **assist** / "helped" - Assist action
- **banish** / "banished" - Banish action
- **revive** / "rez" / "rezzed" - Revive action
- **traded** - Trade kill action

### Run Management
- **start run** / "new run" / "let's go" - Start new run
- **end run** / "game over" - End current run

### Extraction
- **extract** / "extracted" / "evac" - Extraction action

## Tips
- Speak clearly and at normal volume
- Keep commands short (1-3 words)
- Current game is auto-detected from OBS scene
- Transcription appears below the button after processing
- First use will download Whisper model (~150MB)

## Troubleshooting

### "Microphone access denied"
- Check browser permissions for microphone
- On Chrome: Click lock icon in address bar → Site settings → Microphone

### "Could not match command"
- Check that the action exists for your current game
- Try alternative phrases (see supported commands above)
- View transcription to see what was heard

### Slow processing
- First transcription downloads the model (one-time)
- CPU-based transcription takes 1-2 seconds
- "base" model prioritizes speed over accuracy

## Technical Details
- **Model**: Whisper base (English only)
- **Processing**: Local CPU (no GPU required)
- **Latency**: ~1-2 seconds for transcription
- **Privacy**: All processing happens in your Docker container
- **Storage**: Models stored in `/tmp` (auto-downloaded on first use)
