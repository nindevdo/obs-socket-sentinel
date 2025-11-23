#!/bin/bash
# Install script for OBS Hotkey Sender dependencies

echo "🚀 Installing OBS Hotkey Sender dependencies..."

# Install Python dependencies
pip3 install obsws-python requests keyboard pyyaml

echo "✅ Dependencies installed!"
echo ""
echo "📋 Configuration required:"
echo "Set the following environment variables:"
echo "  SS_TOKEN=your-secure-token-here"
echo "  OBS_PASSWORD=your-obs-websocket-password"
echo ""
echo "🎯 Usage:"
echo "  python3 obs-hotkey-sender.py"