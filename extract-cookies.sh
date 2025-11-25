#!/bin/bash

# Script to extract YouTube cookies and place them in the app directory
# This script should be run on the host machine, not in the container

echo "🍪 YouTube Cookie Extraction Helper"
echo "=================================="
echo ""

COOKIES_FILE="./app/cookies.txt"

echo "This script will help you extract YouTube cookies for yt-dlp."
echo "You have several options:"
echo ""
echo "1. Use browser extension (Recommended):"
echo "   - Install 'Get cookies.txt LOCALLY' extension in Chrome/Firefox"
echo "   - Visit youtube.com and log in"
echo "   - Click the extension icon and export cookies"
echo "   - Save as '$COOKIES_FILE'"
echo ""
echo "2. Use yt-dlp with browser extraction (if you have Chrome locally):"
echo "   yt-dlp --cookies-from-browser chrome --cookies '$COOKIES_FILE' --skip-download https://www.youtube.com/watch?v=dQw4w9WgXcQ"
echo ""
echo "3. Manual cookie export:"
echo "   - Open Chrome Developer Tools (F12)"
echo "   - Go to youtube.com and log in"
echo "   - In Network tab, find any request to youtube.com"
echo "   - Copy the 'Cookie' header value"
echo "   - Convert to Netscape format and save to '$COOKIES_FILE'"
echo ""

if [ -f "$COOKIES_FILE" ]; then
    echo "✅ Cookies file already exists at $COOKIES_FILE"
    echo "File size: $(wc -c < "$COOKIES_FILE") bytes"
    echo "Lines: $(wc -l < "$COOKIES_FILE")"
    echo ""
    echo "To update cookies, replace this file with new cookies."
else
    echo "❌ No cookies file found at $COOKIES_FILE"
    echo ""
    echo "After obtaining cookies, place them at: $COOKIES_FILE"
fi

echo ""
echo "Once you have cookies in place, restart the container:"
echo "docker-compose restart obs-socket-sentinel"
echo ""
echo "The application will automatically detect and use the cookies file."