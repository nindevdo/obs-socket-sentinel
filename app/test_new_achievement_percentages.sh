#!/bin/bash

echo "🏆 Testing New Achievement Percentages Structure"
echo "=================================================="

# New structure matching the actual payload
payload='{
  "steam_id": "user_id_123",
  "app_id": "440", 
  "game_name": "Team Fortress 2",
  "achievements": [
    {"name": "TF_GET_HEALPOINTS", "percent": "89.9"},
    {"name": "TF_WIN_2FORT", "percent": "53.6"}
  ],
  "timestamp": '$(date +%s)',
  "timestamp_iso": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'",
  "total_achievements": 2
}'

echo "🎮 Game: Team Fortress 2"
echo "📊 Total Achievements: 2"
echo "  1. TF_GET_HEALPOINTS - 89.9%"
echo "  2. TF_WIN_2FORT - 53.6%"
echo ""

if [ -z "$SOCKET_SENTINEL_AUTH_TOKEN" ]; then
    echo "❌ Error: SOCKET_SENTINEL_AUTH_TOKEN environment variable not set"
    exit 1
fi

echo "📡 Sending POST request to /global-achievement-percentages"

# Send the request
response=$(curl -s -w "%{http_code}" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $SOCKET_SENTINEL_AUTH_TOKEN" \
  -d "$payload" \
  http://localhost:8088/global-achievement-percentages)

status_code="${response: -3}"
response_body="${response%???}"

echo "📥 Response: $status_code"

if [ "$status_code" = "200" ]; then
    echo "✅ Request successful!"
    
    # Wait a moment then check overlay
    sleep 2
    
    # Check if data appears in overlay
    echo "🔍 Checking overlay for achievement percentages..."
    overlay_response=$(curl -s http://localhost:8088/overlay)
    
    if echo "$overlay_response" | jq -e '.achievement_percentages' > /dev/null 2>&1; then
        echo "✅ Achievement percentages found in overlay!"
        
        game_name=$(echo "$overlay_response" | jq -r '.achievement_percentages.game_name // "Unknown"')
        echo "🎮 Game: $game_name"
        
        # Extract achievements count
        achievements_count=$(echo "$overlay_response" | jq '.achievement_percentages.achievements | length')
        echo "📊 Showing $achievements_count achievements:"
        
        # List achievements
        echo "$overlay_response" | jq -r '.achievement_percentages.achievements[] | "  \(.name) (\(.percent)%)"' 2>/dev/null || echo "  (Could not parse achievements)"
        
        remaining=$(echo "$overlay_response" | jq -r '.achievement_percentages.remaining_time // 0')
        echo "⏰ Remaining display time: ${remaining}s"
        echo "🎉 Test completed successfully!"
    else
        echo "❌ No achievement percentages found in overlay"
        echo "Overlay response: $overlay_response" | head -c 200
    fi
else
    echo "❌ Request failed: $status_code"
    echo "Response: $response_body"
fi