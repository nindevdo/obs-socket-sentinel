#!/bin/bash

# Test script for Three.js intro animation

# Get the SS_TOKEN from environment or .env file
if [ -z "$SS_TOKEN" ]; then
  if [ -f "/home/captain/Public/ghorg/nindevdo/obs-socket-sentinel/app/.env" ]; then
    export $(grep SS_TOKEN /home/captain/Public/ghorg/nindevdo/obs-socket-sentinel/app/.env | xargs)
  fi
fi

if [ -z "$SS_TOKEN" ]; then
  echo "Error: SS_TOKEN not set. Please set it in environment or .env file"
  exit 1
fi

echo "🎬 Testing Three.js Intro Animation..."
echo "Token: ${SS_TOKEN:0:10}..."

# Trigger intro action via HTTP POST
curl -X POST http://localhost:8088/action \
  -H "Authorization: Bearer $SS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "game": "hunt_showdown",
    "action": "intro"
  }'

echo ""
echo "✅ Intro triggered! Check OBS overlay for Three.js animation"
echo "The intro should display for 8 seconds with:"
echo "  - 3D text: 'The Cam Bros'"
echo "  - Fire particles animation"
echo "  - Rotating text with glow effect"
