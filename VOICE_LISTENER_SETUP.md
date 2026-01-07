# Continuous Voice Listening Setup Guide

## Overview
Socket Sentinel now supports **always-on voice command monitoring** with GPU acceleration. Audio is streamed from your network to the Docker container for real-time processing.

## Architecture

```
Audio Source (PC/Device)
    ↓
UDP Stream (port 5555)
    ↓
Docker Container (voice_listener.py)
    ↓
Whisper AI (RTX 3090 GPU)
    ↓
Command Parser
    ↓
Action Trigger
```

## Requirements

- ✅ NVIDIA RTX 3090 (or any CUDA-capable GPU)
- ✅ NVIDIA Docker runtime installed
- ✅ Audio streaming software (see options below)
- ✅ Network audio source

## Setup Steps

### 1. Enable GPU in Docker

The docker-compose.yml is already configured for GPU access:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: 1
          capabilities: [gpu]
```

### 2. Enable Voice Listener

Edit `.env` file:
```bash
VOICE_LISTENER_ENABLED=true
VOICE_AUDIO_PORT=5555
```

### 3. Stream Audio to Container

You need to send audio to the container via UDP on port 5555. Here are several options:

#### Option A: FFmpeg (Recommended)

Stream from default microphone:
```bash
# Linux (ALSA)
ffmpeg -f alsa -i default -ar 16000 -ac 1 -f s16le udp://localhost:5555

# Windows (DirectShow)
ffmpeg -f dshow -i audio="Microphone" -ar 16000 -ac 1 -f s16le udp://localhost:5555

# macOS (AVFoundation)
ffmpeg -f avfoundation -i ":0" -ar 16000 -ac 1 -f s16le udp://localhost:5555
```

Stream from specific audio device:
```bash
# List audio devices first
ffmpeg -list_devices true -f dshow -i dummy    # Windows
ffmpeg -f alsa -list_devices                    # Linux
ffmpeg -f avfoundation -list_devices true -i "" # macOS

# Then stream from specific device
ffmpeg -f alsa -i hw:1,0 -ar 16000 -ac 1 -f s16le udp://192.168.0.8:5555
```

#### Option B: GStreamer

```bash
gst-launch-1.0 autoaudiosrc ! audioconvert ! audioresample ! \
  audio/x-raw,rate=16000,channels=1,format=S16LE ! \
  udpsink host=192.168.0.8 port=5555
```

#### Option C: Python Script (Custom)

```python
import pyaudio
import socket

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
UDP_IP = "192.168.0.8"
UDP_PORT = 5555

p = pyaudio.PyAudio()
stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE,
                input=True, frames_per_buffer=CHUNK)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print(f"Streaming audio to {UDP_IP}:{UDP_PORT}...")

try:
    while True:
        data = stream.read(CHUNK, exception_on_overflow=False)
        sock.sendto(data, (UDP_IP, UDP_PORT))
except KeyboardInterrupt:
    pass

stream.stop_stream()
stream.close()
p.terminate()
sock.close()
```

Save as `stream_audio.py` and run: `python stream_audio.py`

### 4. Rebuild and Start Container

```bash
cd /home/captain/Public/ghorg/nindevdo/obs-socket-sentinel
docker-compose build
docker-compose up -d
```

### 5. Verify GPU Usage

Check if Whisper is using GPU:
```bash
docker logs obs-socket-sentinel-obs-socket-sentinel-1 | grep "Whisper"
```

You should see: `✅ Whisper model loaded on GPU`

Monitor GPU usage:
```bash
nvidia-smi -l 1
```

## Audio Settings

The listener is configured for:
- **Sample Rate**: 16000 Hz (16 kHz)
- **Channels**: 1 (Mono)
- **Format**: 16-bit PCM (s16le)
- **Buffer**: 3 seconds before processing
- **Silence Threshold**: RMS < 500 (skips silent audio)

## Testing

1. Start audio streaming (use one of the methods above)
2. Check Docker logs: `docker logs -f obs-socket-sentinel-obs-socket-sentinel-1`
3. Speak a command (e.g., "kill", "death")
4. Watch logs for transcription and action trigger

Expected log output:
```
[voice] 🎤 Starting continuous voice listener on 0.0.0.0:5555
[voice] 📡 Listening for audio on UDP 0.0.0.0:5555
[voice] 🎤 Transcribing audio...
[voice] 📝 Transcribed: 'kill'
[voice] ✅ Auto-triggering action: hunt_showdown/kill
```

## Troubleshooting

### "GPU not available, using CPU"
- Verify NVIDIA drivers: `nvidia-smi`
- Check Docker runtime: `docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi`
- Ensure nvidia-container-toolkit is installed

### No audio received
- Check firewall allows UDP port 5555
- Verify IP address in stream command matches Docker host
- Test with netcat: `echo "test" | nc -u localhost 5555`
- Check logs: `docker logs obs-socket-sentinel-obs-socket-sentinel-1 | grep audio`

### Commands not recognized
- Check transcription in logs to see what was heard
- Speak clearly and at normal volume
- Add more synonyms to `voice_commands.py`
- Ensure current game is set correctly

### High CPU/GPU usage
- Adjust buffer_duration (default 3 seconds)
- Lower silence_threshold to skip more audio
- Use smaller Whisper model (currently "base")

## Performance

With RTX 3090:
- **Transcription Speed**: ~0.1-0.3 seconds (10-30x faster than CPU)
- **Latency**: ~3.5 seconds total (3s buffering + 0.5s processing)
- **VRAM Usage**: ~500MB
- **GPU Utilization**: 5-10% during transcription

## Advanced Configuration

Edit `voice_listener.py` to customize:

```python
# Change buffer duration
self.buffer_duration = 3.0  # seconds (default: 3)

# Adjust silence threshold
self.silence_threshold = 500  # RMS (default: 500)

# Use larger Whisper model for better accuracy
self.whisper_model = WhisperModel("medium", device="cuda", compute_type="float16")
```

## Network Audio Sources

### OBS Virtual Audio Output
1. Install VB-Audio Virtual Cable
2. Set as OBS monitor device
3. Stream that device to container

### VoiceMeeter
1. Configure output routing
2. Stream specific channel to UDP

### System Audio Loopback
1. Use Stereo Mix (Windows) or equivalent
2. Stream mixed audio (game + mic)

---

**Status**: ✅ Ready for deployment  
**GPU**: RTX 3090 (CUDA 11.8+)  
**Network**: UDP port 5555  
**Processing**: Real-time continuous monitoring
