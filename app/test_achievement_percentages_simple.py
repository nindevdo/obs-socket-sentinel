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
            {"name": "TF_GET_HEALPOINTS", "percent": "89.9"},
            {"name": "TF_WIN_2FORT", "percent": "53.6"},
            {"name": "TF_PLAY_GAME_FRIENDS", "percent": "12.3"},
            {"name": "TF_GET_HEADSHOTS", "percent": "76.8"}
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