#!/usr/bin/env python3

import requests
import json
import time
import sys
import os

def test_new_achievement_percentages():
    """Test the new achievement percentages endpoint with the correct payload structure."""
    
    print("🏆 Testing New Achievement Percentages Structure")
    print("=" * 60)
    
    # New structure matching the actual payload
    percentages_data = {
        "steam_id": "user_id_123",
        "app_id": "440",
        "game_name": "Team Fortress 2",
        "achievements": [
            {"name": "TF_GET_HEALPOINTS", "percent": "89.9"},
            {"name": "TF_WIN_2FORT", "percent": "53.6"}
        ],
        "timestamp": int(time.time()),
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_achievements": 2
    }
    
    print(f"🎮 Game: {percentages_data['game_name']}")
    print(f"📊 Total Achievements: {percentages_data['total_achievements']}")
    for i, achievement in enumerate(percentages_data['achievements'], 1):
        print(f"  {i}. {achievement['name']} - {achievement['percent']}%")
    print()
    
    # Get auth token
    auth_token = os.getenv('SOCKET_SENTINEL_AUTH_TOKEN')
    if not auth_token:
        print("❌ Error: SOCKET_SENTINEL_AUTH_TOKEN environment variable not set")
        return False
    
    try:
        # Create request
        url = 'http://localhost:8088/global-achievement-percentages'
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {auth_token}'
        }
        
        print(f"📡 Sending POST request to {url}")
        
        # Send request
        response = requests.post(url, json=percentages_data, headers=headers, timeout=10)
        
        print(f"📥 Response: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ Request successful!")
            
            # Wait a moment then check overlay
            time.sleep(2)
            
            # Check if data appears in overlay
            overlay_response = requests.get('http://localhost:8088/overlay', timeout=5)
            if overlay_response.status_code == 200:
                overlay_data = overlay_response.json()
                
                if overlay_data.get('achievement_percentages'):
                    percentages_info = overlay_data['achievement_percentages']
                    print("✅ Achievement percentages found in overlay!")
                    
                    print(f"🎮 Game: {percentages_info.get('game_name')}")
                    achievements = percentages_info.get('achievements', [])
                    print(f"📊 Showing {len(achievements)} achievements:")
                    for i, achievement in enumerate(achievements, 1):
                        print(f"  {i}. {achievement.get('name')} ({achievement.get('percent')}%)")
                    
                    remaining = percentages_info.get('remaining_time', 0)
                    print(f"⏰ Remaining display time: {remaining:.1f}s")
                    return True
                else:
                    print("❌ No achievement percentages found in overlay")
            else:
                print(f"❌ Failed to check overlay: {overlay_response.status_code}")
                
        else:
            print(f"❌ Request failed: {response.status_code}")
            try:
                error_data = response.json()
                print(f"Error: {error_data}")
            except:
                print(f"Error body: {response.text}")
                
        return False
        
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False

if __name__ == "__main__":
    test_new_achievement_percentages()