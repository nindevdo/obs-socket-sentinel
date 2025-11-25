#!/usr/bin/env python3
"""
Test script for global achievement percentages endpoint.
Run this inside the running container to test achievement percentages.
"""

import urllib.request
import urllib.parse
import json
import time
import sys
import os

def send_achievement_percentages():
    """Send test achievement percentages data."""
    
    print("📊 Testing Achievement Percentages Display")
    print("=" * 40)
    
    # Test payload matching the expected structure
    payload = {
        "steam_id": "76561198123456789",
        "app_id": "440", 
        "game_name": "Team Fortress 2",
        "achievements": [
            {
                "name": "TF_GET_HEALPOINTS", 
                "display_name": "Master Medic", 
                "description": "Accumulate 25000 heal points in a single life",
                "icon": "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/apps/440/achievements/TF_GET_HEALPOINTS.jpg",
                "icon_gray": "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/apps/440/achievements/TF_GET_HEALPOINTS_gray.jpg",
                "percent": "89.9"
            },
            {
                "name": "TF_WIN_2FORT", 
                "display_name": "2Fort Fortress",
                "description": "Play a complete round on 2Fort",
                "icon": "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/apps/440/achievements/TF_WIN_2FORT.jpg",
                "icon_gray": "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/apps/440/achievements/TF_WIN_2FORT_gray.jpg",
                "percent": "53.6"
            },
            {
                "name": "TF_PLAY_GAME_FRIENDS", 
                "display_name": "Team Player",
                "description": "Accumulate 1000 minutes of playtime with friends",
                "icon": "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/apps/440/achievements/TF_PLAY_GAME_FRIENDS.jpg",
                "icon_gray": "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/apps/440/achievements/TF_PLAY_GAME_FRIENDS_gray.jpg",
                "percent": "12.3"
            },
            {
                "name": "TF_GET_HEADSHOTS", 
                "display_name": "Sniper Elite",
                "description": "Get 25 headshots as a Sniper",
                "icon": "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/apps/440/achievements/TF_GET_HEADSHOTS.jpg",
                "icon_gray": "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/apps/440/achievements/TF_GET_HEADSHOTS_gray.jpg",
                "percent": "76.8"
            }
        ],
        "timestamp": int(time.time()),
        "timestamp_iso": time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime()),
        "total_achievements": 4
    }
    
    try:
        print("📤 Sending achievement percentages...")
        print(f"   Game: {payload['game_name']}")
        print(f"   Achievements: {payload['total_achievements']}")
        
        data = json.dumps(payload).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {os.getenv("SS_TOKEN", "test_token")}'
        }
        
        req = urllib.request.Request('http://localhost:8088/global-achievement-percentages', data=data, headers=headers, method='POST')
        
        with urllib.request.urlopen(req, timeout=5) as response:
            result = response.read().decode()
            
            if response.status == 200:
                print("✅ Achievement percentages sent successfully!")
                print(f"   Response: {result}")
            else:
                print(f"❌ Failed with status {response.status}: {result}")
                return False
        
        # Check overlay
        print("🔍 Checking overlay...")
        time.sleep(1)
        
        with urllib.request.urlopen('http://localhost:8088/overlay', timeout=5) as response:
            data = json.loads(response.read().decode())
            
            if data.get('global_achievement_percentages'):
                percentages_data = data['global_achievement_percentages']
                remaining_time = percentages_data.get('remaining_time', 0)
                
                print("✅ Achievement percentages found in overlay!")
                print(f"   Game: {percentages_data.get('game_name')}")
                print(f"   Achievements: {len(percentages_data.get('achievements', []))}")
                print(f"   Remaining: {remaining_time:.1f}s")
                print(f"\n🌐 View at: http://localhost:8088")
                return True
            else:
                print("❌ No achievement percentages found in overlay")
                return False
                
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    send_achievement_percentages()