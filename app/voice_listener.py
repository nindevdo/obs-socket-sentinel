#!/usr/bin/env python3
"""
Continuous Voice Listener for Socket Sentinel
Monitors network audio stream and processes voice commands
"""

import asyncio
import logging
import os
import socket
import wave
import io
import numpy as np
from typing import Optional, Callable
from pathlib import Path

logger = logging.getLogger(__name__)

# Global Whisper model instance (shared across browser and UDP audio)
whisper_model = None

class ContinuousVoiceListener:
    """Listens to network audio stream and processes voice commands"""
    
    def __init__(self, 
                 audio_host: str = "0.0.0.0",
                 audio_port: int = 5555,
                 sample_rate: int = 16000,
                 channels: int = 1):
        """
        Initialize voice listener
        
        Args:
            audio_host: Host to bind to for receiving audio
            audio_port: Port to listen on for audio stream
            sample_rate: Audio sample rate in Hz
            channels: Number of audio channels (1=mono, 2=stereo)
        """
        self.audio_host = audio_host
        self.audio_port = audio_port
        self.sample_rate = sample_rate
        self.channels = channels
        
        self.is_running = False
        self.whisper_model = None
        self.command_callback: Optional[Callable] = None
        
        # Audio buffering
        self.audio_buffer = []
        self.buffer_duration = 3.0  # seconds of audio to buffer before processing
        self.silence_threshold = 2000  # RMS threshold for silence detection (increased to avoid noise)
        self.last_transcribe_time = 0  # Cooldown to prevent spam
        self.transcribe_cooldown = 2.0  # Minimum seconds between transcriptions
        
    async def initialize_whisper(self):
        """Initialize Whisper model with GPU support"""
        global whisper_model
        from faster_whisper import WhisperModel
        import os
        
        # Use small model for better accuracy (still fast on GPU)
        # base = fastest but least accurate
        # small = good balance of speed/accuracy
        # medium/large = most accurate but slower
        
        # Set cache directory to persistent volume
        cache_dir = os.getenv("HF_HOME", "/models/huggingface")
        os.makedirs(cache_dir, exist_ok=True)
        
        logger.info(f"[voice] Initializing Whisper model on GPU (cache: {cache_dir})...")
        whisper_model = WhisperModel(
            "small",
            device="cuda",
            compute_type="float16",
            download_root=cache_dir  # Cache models here
        )
        self.whisper_model = whisper_model
        logger.info("[voice] ✅ Whisper model loaded on GPU")
    
    def set_command_callback(self, callback: Callable):
        """Set callback function to be called when command is detected"""
        self.command_callback = callback
    
    async def start_listening(self):
        """Start continuous audio monitoring"""
        if not self.whisper_model:
            await self.initialize_whisper()
        
        self.is_running = True
        logger.info(f"[voice] 🎤 Starting continuous voice listener on {self.audio_host}:{self.audio_port}")
        
        # Start UDP server to receive audio
        await self.run_audio_receiver()
    
    async def stop_listening(self):
        """Stop continuous monitoring"""
        self.is_running = False
        logger.info("[voice] 🛑 Stopped continuous voice listener")
    
    async def run_audio_receiver(self):
        """Run UDP server to receive audio stream"""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(False)
        
        try:
            sock.bind((self.audio_host, self.audio_port))
            logger.info(f"[voice] 📡 Listening for audio on UDP {self.audio_host}:{self.audio_port}")
            
            loop = asyncio.get_event_loop()
            
            while self.is_running:
                try:
                    # Receive audio data
                    data = await loop.sock_recv(sock, 4096)
                    
                    if data:
                        await self.process_audio_chunk(data)
                    
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.debug(f"[voice] Audio receive error: {e}")
                    await asyncio.sleep(0.01)
                    
        finally:
            sock.close()
    
    async def process_audio_chunk(self, audio_data: bytes):
        """Process incoming audio chunk"""
        # Convert bytes to numpy array
        audio_np = np.frombuffer(audio_data, dtype=np.int16)
        
        # Add to buffer
        self.audio_buffer.append(audio_np)
        
        # Calculate total buffered duration
        total_samples = sum(len(chunk) for chunk in self.audio_buffer)
        buffered_duration = total_samples / self.sample_rate
        
        # Process when we have enough audio
        if buffered_duration >= self.buffer_duration:
            await self.process_buffered_audio()
    
    async def process_buffered_audio(self):
        """Process accumulated audio buffer"""
        if not self.audio_buffer:
            return
        
        # Check cooldown
        import time
        now = time.time()
        if now - self.last_transcribe_time < self.transcribe_cooldown:
            logger.debug(f"[voice] Skipping - cooldown active ({self.transcribe_cooldown}s)")
            self.audio_buffer.clear()
            return
        
        # Concatenate all buffered chunks
        full_audio = np.concatenate(self.audio_buffer)
        
        # Check for silence (skip processing if too quiet)
        rms = np.sqrt(np.mean(full_audio.astype(float)**2))
        if rms < self.silence_threshold:
            logger.debug(f"[voice] Skipping silent audio (RMS={rms:.1f})")
            self.audio_buffer.clear()
            return
        
        # Update last transcribe time
        self.last_transcribe_time = now
        
        # Clear buffer
        self.audio_buffer.clear()
        
        # Save to temp file for Whisper
        temp_audio_path = f"/tmp/voice_stream_{int(now)}.wav"
        
        try:
            # Write WAV file
            with wave.open(temp_audio_path, 'wb') as wav_file:
                wav_file.setnchannels(self.channels)
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(self.sample_rate)
                wav_file.writeframes(full_audio.tobytes())
            
            # Transcribe
            logger.info("[voice] 🎤 Transcribing audio...")
            segments, info = self.whisper_model.transcribe(
                temp_audio_path,
                language="en",
                vad_filter=True,  # Voice Activity Detection
                beam_size=5
            )
            
            # Extract text
            text = " ".join([segment.text for segment in segments]).strip()
            
            if text:
                logger.info(f"[voice] 📝 Transcribed: '{text}'")
                
                # Call command callback if set
                if self.command_callback:
                    await self.command_callback(text)
            
        except Exception as e:
            logger.error(f"[voice] Transcription error: {e}")
        
        finally:
            # Cleanup temp file
            try:
                os.unlink(temp_audio_path)
            except:
                pass


# Global listener instance
_voice_listener: Optional[ContinuousVoiceListener] = None


async def get_voice_listener() -> Optional[ContinuousVoiceListener]:
    """Get global voice listener instance (returns None if not created)"""
    global _voice_listener
    return _voice_listener


def set_voice_listener(listener: ContinuousVoiceListener):
    """Set the global voice listener instance"""
    global _voice_listener
    _voice_listener = listener
