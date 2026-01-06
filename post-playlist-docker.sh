#!/bin/bash
# Wrapper script to post YouTube playlists to Discord from the host machine

set -e

echo "🎬 YouTube Playlist to Discord Poster"
echo "====================================="

# Check if playlist URL is provided
if [ $# -lt 1 ]; then
    echo "❗ Usage: $0 <playlist_url> [max_videos]"
    echo ""
    echo "Examples:"
    echo "  $0 'https://www.youtube.com/playlist?list=PLrAXtmRdnEQy6nuLMCSM05Zo1Jzwg_kkF'"
    echo "  $0 'https://www.youtube.com/playlist?list=PLrAXtmRdnEQy6nuLMCSM05Zo1Jzwg_kkF' 25"
    echo ""
    echo "Note: This runs inside the Docker container"
    exit 1
fi

PLAYLIST_URL="$1"
MAX_VIDEOS="${2:-}"

# Get the container name
CONTAINER_NAME="obs-socket-sentinel-obs-socket-sentinel-1"

# Check if container is running
if ! docker ps | grep -q "$CONTAINER_NAME"; then
    echo "❌ Error: Container $CONTAINER_NAME is not running"
    echo "   Start it with: docker compose up -d"
    exit 1
fi

echo "📋 Playlist URL: $PLAYLIST_URL"
if [ -n "$MAX_VIDEOS" ]; then
    echo "📊 Max videos: $MAX_VIDEOS"
    echo "🚀 Executing in Docker container..."
    docker exec "$CONTAINER_NAME" /app/post-playlist.sh "$PLAYLIST_URL" "$MAX_VIDEOS"
else
    echo "📊 Max videos: Default (50)"
    echo "🚀 Executing in Docker container..."
    docker exec "$CONTAINER_NAME" /app/post-playlist.sh "$PLAYLIST_URL"
fi
