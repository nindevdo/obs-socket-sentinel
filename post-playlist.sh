#!/bin/bash
set -e

# YouTube Playlist Poster - Host Wrapper Script
# This script runs the playlist poster from the host by executing it inside the Docker container

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER_NAME="obs-socket-sentinel-obs-socket-sentinel-1"

echo "🎬 YouTube Playlist to Discord Poster (Host Wrapper)"
echo "=================================================="

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "❗ Error: Docker is not installed or not in PATH"
    exit 1
fi

# Check if we're in the right directory (should contain docker-compose.yml)
if [ ! -f "$SCRIPT_DIR/docker-compose.yml" ]; then
    echo "❗ Error: This script must be run from the obs-socket-sentinel directory"
    echo "   Current directory: $SCRIPT_DIR"
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
    echo "This will post each video from the YouTube playlist as individual messages"
    echo "to the Discord channel configured in your .env file."
    echo ""
    echo "If max_videos is not specified, ALL videos in the playlist will be posted."
    echo "Duplicate checking is always enabled to prevent reposting existing videos."
    exit 1
fi

PLAYLIST_URL="$1"
MAX_VIDEOS="${2:-}"

# Check if container is running
if ! docker ps --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
    echo "❗ Error: Container '${CONTAINER_NAME}' is not running"
    echo "   Start it with: docker-compose up -d"
    exit 1
fi

echo "✅ Container '${CONTAINER_NAME}' is running"
echo "📋 Playlist URL: $PLAYLIST_URL"
if [ -n "$MAX_VIDEOS" ]; then
    echo "📊 Max videos: $MAX_VIDEOS"
else
    echo "📊 Max videos: Default (50)"
fi
echo ""
echo "🚀 Executing playlist poster inside container..."
echo ""

# Execute the script inside the container
docker exec "$CONTAINER_NAME" /app/post-playlist.sh "$@"

exit_code=$?

echo ""
if [ $exit_code -eq 0 ]; then
    echo "🎉 Playlist posting completed successfully!"
    echo ""
    echo "📺 The videos have been posted to your Discord channel and will be available"
    echo "   for use with obs-socket-sentinel reactions and emoji triggers."
else
    echo "❌ Playlist posting failed with exit code $exit_code"
fi

exit $exit_code