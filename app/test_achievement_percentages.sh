#!/bin/bash

# Test script for /global-achievement-percentages endpoint

AUTH_TOKEN=${AUTH_TOKEN:-"your-secret-token"}

echo "🎮 Achievement Percentages Test Script"
echo "======================================================"
echo "🧪 Testing achievement percentages endpoint..."

# Test payload matching the actual structure
curl -v -X POST http://localhost:8088/global-achievement-percentages \
  -H "Authorization: Bearer $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "steam_id": "76561198012345678",
    "app_id": "440", 
    "game_name": "Team Fortress 2",
    "achievements": [
      {"name": "TF_GET_HEALPOINTS", "percent": "89.9"},
      {"name": "TF_WIN_2FORT", "percent": "53.6"},
      {"name": "TF_PLAY_GAME_FRIENDS", "percent": "12.3"},
      {"name": "TF_GET_HEADSHOTS", "percent": "76.8"}
    ],
    "timestamp": 1732571754,
    "timestamp_iso": "2025-11-25T20:55:54.805Z",
    "total_achievements": 4
  }'

echo -e "\n\n✅ Achievement percentages test completed!"
echo "💡 Check the OBS overlay for the achievement progress display"
echo -e "\n📋 To run this test:"
echo "  docker exec -it obs-socket-sentinel-1 bash test_achievement_percentages.sh"