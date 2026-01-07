#!/usr/bin/env python3
"""
Test script to send test audio to voice listener
Generates a simple tone and sends it via UDP
"""

import socket
import numpy as np
import time

UDP_IP = "localhost"
UDP_PORT = 5555
SAMPLE_RATE = 16000
DURATION = 3  # seconds

print(f"Sending test audio to {UDP_IP}:{UDP_PORT}")
print("This will send 3 seconds of silence to test the connection...")

# Generate silent audio (all zeros)
samples = np.zeros(SAMPLE_RATE * DURATION, dtype=np.int16)

# Create UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Send in chunks
CHUNK_SIZE = 1024
for i in range(0, len(samples), CHUNK_SIZE):
    chunk = samples[i:i+CHUNK_SIZE]
    sock.sendto(chunk.tobytes(), (UDP_IP, UDP_PORT))
    time.sleep(CHUNK_SIZE / SAMPLE_RATE)  # Simulate real-time

sock.close()
print("✅ Test audio sent! Check Docker logs for reception.")
