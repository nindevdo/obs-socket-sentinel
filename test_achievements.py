#!/usr/bin/env python3
"""
Test script for Steam achievement notification endpoint.
This script simulates posting achievement data to the /achievement endpoint.
"""

import json
import time
import sys
import urllib.request
import urllib.parse

def send_achievement_notification(
    host="127.0.0.1", 
    port=8088, 
    auth_token=None,
    achievement_data=None
):
    """Send an achievement notification via POST to the /achievement endpoint."""
    
    if not achievement_data:
        # Default test achievement data
        achievement_data = {
            "achievement_title": "First Steps",
            "api_name": "FIRST_STEPS", 
            "description": "Complete the tutorial level",
            "icon": "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/apps/123456/achievement_first_steps.jpg",
            "icon_gray": "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/apps/123456/achievement_first_steps_gray.jpg",
            "game_name": "Test Game 2024",
            "app_id": "123456",
            "unlock_time": int(time.time()),
            "unlock_time_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "unlock_time_readable": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "steam_id": "76561198000000000",
        }
    
    try:
        url = f"http://{host}:{port}/achievement"
        data = json.dumps(achievement_data).encode('utf-8')
        
        headers = {
            'Content-Type': 'application/json',
            'Content-Length': str(len(data))
        }
        
        if auth_token:
            headers['Authorization'] = f'Bearer {auth_token}'
        
        req = urllib.request.Request(url, data=data, headers=headers, method='POST')
        
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())
            print(f"✅ Achievement sent successfully: {result}")
            return True
            
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else 'No error body'
        print(f"❌ HTTP Error {e.code}: {error_body}")
        return False
    except Exception as e:
        print(f"❌ Failed to send achievement: {e}")
        return False

def test_achievement_notifications():
    """Test the achievement notification system with various scenarios."""
    print("🏆 Testing OBS Socket Sentinel Achievement Notifications")
    print("=" * 60)
    
    # Test 1: Simple achievement without auth
    print("\n1️⃣ Testing achievement without auth token")
    success = send_achievement_notification()
    if not success:
        print("   Note: If auth is enabled, this test will fail (expected)")
    
    # Test 2: Achievement with auth token (if SS_TOKEN is set)
    auth_token = input("\n2️⃣ Enter SS_TOKEN (or press Enter to skip): ").strip()
    if auth_token:
        print(f"   Testing with auth token: {auth_token[:8]}...")
        send_achievement_notification(auth_token=auth_token)
    else:
        print("   Skipping auth test")
    
    # Test 3: Custom achievement data
    print("\n3️⃣ Testing custom achievement")
    custom_achievement = {
        "achievement_title": "Speed Demon",
        "api_name": "SPEED_DEMON",
        "description": "Complete a level in under 30 seconds",
        "icon": "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHZpZXdCb3g9IjAgMCA2NCA2NCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjY0IiBoZWlnaHQ9IjY0IiByeD0iOCIgZmlsbD0iI0ZGRDcwMCIvPgo8dGV4dCB4PSIzMiIgeT0iNDAiIGZvbnQtZmFtaWx5PSJzYW5zLXNlcmlmIiBmb250LXNpemU9IjI4IiBmaWxsPSIjMDAwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj7wn5iqPC90ZXh0Pgo8L3N2Zz4=",
        "icon_gray": "",
        "game_name": "Hunt: Showdown",
        "app_id": "594650", 
        "unlock_time": int(time.time()),
        "unlock_time_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "unlock_time_readable": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "steam_id": "76561198123456789",
    }
    
    send_achievement_notification(
        auth_token=auth_token if auth_token else None,
        achievement_data=custom_achievement
    )
    
    # Test 4: Multiple achievements in sequence
    print("\n4️⃣ Testing multiple achievements (spaced 3 seconds apart)")
    achievements = [
        {
            "achievement_title": "Marksman",
            "api_name": "MARKSMAN", 
            "description": "Get 10 headshots in a single match",
            "icon": "",
            "icon_gray": "",
            "game_name": "Hunt: Showdown",
            "app_id": "594650",
            "unlock_time": int(time.time()),
            "unlock_time_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "unlock_time_readable": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "steam_id": "76561198123456789",
        },
        {
            "achievement_title": "Survivor",
            "api_name": "SURVIVOR",
            "description": "Extract from 100 matches",
            "icon": "",
            "icon_gray": "",
            "game_name": "Hunt: Showdown", 
            "app_id": "594650",
            "unlock_time": int(time.time()) + 3,
            "unlock_time_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "unlock_time_readable": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            "steam_id": "76561198123456789",
        }
    ]
    
    for i, achievement in enumerate(achievements, 1):
        print(f"   Sending achievement {i}/{len(achievements)}: {achievement['achievement_title']}")
        send_achievement_notification(
            auth_token=auth_token if auth_token else None,
            achievement_data=achievement
        )
        if i < len(achievements):
            print("   Waiting 3 seconds...")
            time.sleep(3)
    
    print("\n✅ Achievement notification tests complete!")
    print("\nNote: Check the OBS overlay to see if notifications appeared correctly.")

if __name__ == "__main__":
    test_achievement_notifications()