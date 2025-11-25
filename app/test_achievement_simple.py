#!/usr/bin/env python3
"""
Simple test script for achievement notifications.
Run this inside the running container to test achievements.
"""

import urllib.request
import urllib.parse
import json
import time
import sys
import os

def send_achievement(title=None):
    """Send a test achievement."""
    
    print("🏆 Testing Achievement Notification")
    print("=" * 40)
    
    # Use custom title or default
    achievement_title = title or "Test Achievement"
    
    achievement = {
        "achievement_title": achievement_title,
        "api_name": "TEST_ACHIEVEMENT",
        "description": "This is a test achievement notification",
        "icon": "data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjQiIGhlaWdodD0iNjQiIHZpZXdCb3g9IjAgMCA2NCA2NCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjY0IiBoZWlnaHQ9IjY0IiByeD0iOCIgZmlsbD0iI0ZGRDcwMCIvPgo8dGV4dCB4PSIzMiIgeT0iNDAiIGZvbnQtZmFtaWx5PSJzYW5zLXNlcmlmIiBmb250LXNpemU9IjI4IiBmaWxsPSIjMDAwIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj7wn44yPC90ZXh0Pgo8L3N2Zz4=",
        "icon_gray": "",
        "game_name": "Hunt: Showdown",
        "app_id": "594650",
        "unlock_time": int(time.time()),
        "steam_id": "76561198123456789",
    }
    
    try:
        # Send achievement
        print(f"📤 Sending: {achievement_title}")
        
        data = json.dumps(achievement).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {os.getenv("SS_TOKEN", "test_token")}'
        }
        
        req = urllib.request.Request('http://localhost:8088/achievement', data=data, headers=headers, method='POST')
        
        with urllib.request.urlopen(req, timeout=5) as response:
            result = response.read().decode()
            
            if response.status == 200:
                print("✅ Achievement sent successfully!")
                print(f"   Response: {result}")
            else:
                print(f"❌ Failed with status {response.status}: {result}")
                return False
        
        # Check overlay
        print("🔍 Checking overlay...")
        time.sleep(1)
        
        with urllib.request.urlopen('http://localhost:8088/overlay', timeout=5) as response:
            data = json.loads(response.read().decode())
            
            if data.get('achievement'):
                achievement_data = data['achievement']
                remaining_time = achievement_data.get('remaining_time', 0)
                
                print("✅ Achievement found in overlay!")
                print(f"   Title: {achievement_data.get('achievement_title')}")
                print(f"   Remaining: {remaining_time:.1f}s")
                print(f"\n🌐 View at: http://localhost:8088")
                return True
            else:
                print("❌ No achievement found in overlay")
                return False
                
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    title = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
    send_achievement(title)