#!/bin/bash
set -e

# YouTube Playlist Poster - Docker Entry Point
# This script runs the YouTube playlist poster from within the obs-socket-sentinel container

echo "🎬 YouTube Playlist to Discord Poster"
echo "====================================="

# Check if we're running in the container
if [ ! -f "/app/youtube_playlist_poster.py" ]; then
    echo "❗ Error: This script must be run from within the obs-socket-sentinel Docker container"
    echo "   Usage from host: docker exec obs-socket-sentinel-obs-socket-sentinel-1 /app/post-playlist.sh <playlist_url> [max_videos]"
    exit 1
fi

# Validate arguments
if [ $# -lt 1 ]; then
    echo "❗ Usage: $0 <playlist_url> [max_videos]"
    echo ""
    echo "Examples:"
    echo "  $0 'https://www.youtube.com/playlist?list=PLrAXtmRdnEQy6nuLMCSM05Zo1Jzwg_kkF'"
    echo "  $0 'https://www.youtube.com/playlist?list=PLrAXtmRdnEQy6nuLMCSM05Zo1Jzwg_kkF' 25"
    echo ""
    echo "Environment variables required:"
    echo "  DISCORD_BOT_TOKEN - Discord bot token"
    echo "  DISCORD_CHANNEL_ID - Discord channel ID"
    echo ""
    echo "Note: If max_videos is not specified, ALL videos in the playlist will be posted."
    echo "      Duplicate checking is always enabled to prevent reposting existing videos."
    exit 1
fi

PLAYLIST_URL="$1"
MAX_VIDEOS="${2:-}"

echo "📋 Playlist URL: $PLAYLIST_URL"
if [ -n "$MAX_VIDEOS" ]; then
    echo "📊 Max videos: $MAX_VIDEOS"
else
    echo "📊 Max videos: Default (50)"
fi

# Check environment variables
if [ -z "$DISCORD_BOT_TOKEN" ]; then
    echo "❗ Error: DISCORD_BOT_TOKEN environment variable is not set"
    exit 1
fi

if [ -z "$DISCORD_CHANNEL_ID" ]; then
    echo "❗ Error: DISCORD_CHANNEL_ID environment variable is not set"
    exit 1
fi

echo "✅ Environment variables configured"
echo "🚀 Starting playlist posting..."
echo ""

# Run the Python script
cd /app
if [ -n "$MAX_VIDEOS" ]; then
    python youtube_playlist_poster.py "$PLAYLIST_URL" "$MAX_VIDEOS"
else
    python youtube_playlist_poster.py "$PLAYLIST_URL"
fi

exit_code=$?

echo ""
if [ $exit_code -eq 0 ]; then
    echo "✅ Playlist posting completed successfully!"
else
    echo "❌ Playlist posting failed with exit code $exit_code"
fi

exit $exit_code