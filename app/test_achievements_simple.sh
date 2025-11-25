#!/bin/bash

echo "Testing achievement percentages endpoint..."

curl -X POST http://localhost:8088/global-achievement-percentages \
  -H "Authorization: Bearer your-secret-token" \
  -H "Content-Type: application/json" \
  -d '{
    "steam_id": "76561198012345678",
    "app_id": "440", 
    "game_name": "Team Fortress 2",
    "achievements": [
      {"name": "TF_GET_HEALPOINTS", "percent": "89.9"},
      {"name": "TF_WIN_2FORT", "percent": "53.6"}
    ],
    "timestamp": 1732571754,
    "timestamp_iso": "2025-11-25T20:55:54.805Z",
    "total_achievements": 2
  }'

echo -e "\nTest completed!"