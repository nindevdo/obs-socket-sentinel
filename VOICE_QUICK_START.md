# Quick Start - Stream Your Microphone to Voice Listener

## The System is Ready!

Your voice listener is now **running and waiting for audio** on UDP port 5555.

## Start Streaming Audio NOW

### Option 1: FFmpeg (Recommended - One Command)

```bash
# Linux - Stream default microphone
ffmpeg -f alsa -i default -ar 16000 -ac 1 -f s16le udp://192.168.0.8:5555

# List available devices first:
arecord -l

# Then stream specific device (example):
ffmpeg -f alsa -i hw:0,0 -ar 16000 -ac 1 -f s16le udp://192.168.0.8:5555
```

Replace `192.168.0.8` with your actual Docker host IP if streaming from another machine.

### Option 2: Test with Simulated Audio

```bash
# Generate test tone and stream it
ffmpeg -f lavfi -i "sine=frequency=1000:duration=5" -ar 16000 -ac 1 -f s16le udp://localhost:5555
```

## What Changed

✅ **Fixed Issues:**
- Removed UI voice button (was conflicting with continuous listener)
- Added cooldown (2 seconds minimum between transcriptions)
- Increased silence threshold (RMS > 2000 to avoid background noise)
- Continuous listener now ONLY processes when actual audio is received

✅ **How It Works Now:**
1. Stream audio to UDP port 5555 (raw PCM, 16kHz, mono)
2. System buffers 3 seconds of audio
3. Checks if audio is loud enough (RMS > 2000)
4. Transcribes with Whisper on GPU (~0.2 seconds)
5. Parses command and triggers action automatically
6. Waits 2 seconds before processing next audio

## Monitor Activity

```bash
# Watch logs in real-time
docker logs -f obs-socket-sentinel-obs-socket-sentinel-1 | grep voice

# You should see:
# [voice] 🎤 Transcribing audio...
# [voice] 📝 Transcribed: 'kill'
# [voice] ✅ Auto-triggering action: hunt_showdown/kill
```

## Firewall (Already Done)

Port 5555/UDP should be open in firewalld. If not:
```bash
sudo firewall-cmd --add-port=5555/udp --permanent
sudo firewall-cmd --reload
```

## Troubleshooting

**No audio being processed?**
- Check if FFmpeg is streaming: you should see data rate output
- Verify port: `ss -ulnp | grep 5555` (should show listening)
- Check if audio is loud enough (speak clearly, adjust silence_threshold if needed)

**Commands not recognized?**
- Check what was transcribed in logs
- Try clearer pronunciation
- Add more synonyms to voice_commands.py

**Want to adjust settings?**
Edit `/home/captain/Public/ghorg/nindevdo/obs-socket-sentinel/app/voice_listener.py`:
```python
self.buffer_duration = 3.0      # Seconds to buffer
self.silence_threshold = 2000   # Lower = more sensitive
self.transcribe_cooldown = 2.0  # Minimum seconds between commands
```

---

**Ready!** Just run the FFmpeg command above and start speaking commands!
