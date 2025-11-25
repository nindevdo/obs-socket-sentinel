#!/usr/bin/env python3
"""
Simple test script for playtime notifications.
Run this inside the running container to test playtime display.
"""

import urllib.request
import urllib.parse
import json
import time
import sys
import os

def send_playtime(game_name=None, hours=None):
    """Send a test playtime notification."""
    
    print("⏰ Testing Playtime Notification")
    print("=" * 40)
    
    # Use custom values or defaults
    game_name = game_name or "Hunt: Showdown"
    total_hours = hours or 42.5
    total_minutes = int(total_hours * 60)
    
    # Calculate readable time (simplified version)
    if total_hours < 1:
        readable_time = f"{total_minutes} minutes"
    elif total_hours < 24:
        readable_time = f"{total_hours:.1f} hours"
    else:
        days = int(total_hours // 24)
        remaining_hours = total_hours % 24
        if remaining_hours > 0:
            readable_time = f"{days} days, {remaining_hours:.1f} hours"
        else:
            readable_time = f"{days} days"
    
    playtime_data = {
        "steam_id": "76561198123456789",
        "app_id": "594650",
        "game_name": game_name,
        "total_playtime_minutes": total_minutes,
        "total_playtime_hours": total_hours,
        "total_playtime_readable": readable_time,
        "timestamp": time.time(),
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "playing"
    }
    
    try:
        print(f"📤 Sending playtime for: {game_name}")
        print(f"   ⏰ Total time: {readable_time} ({total_hours} hours)")
        print("   📏 This will display in TOP-LEFT corner for 5 minutes")
        
        data = json.dumps(playtime_data).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {os.getenv("SS_TOKEN", "test_token")}'
        }
        
        req = urllib.request.Request('http://localhost:8088/playtime', data=data, headers=headers, method='POST')
        
        with urllib.request.urlopen(req, timeout=5) as response:
            result = response.read().decode()
            
            if response.status == 200:
                print("✅ Playtime sent successfully!")
                print(f"   Response: {result}")
            else:
                print(f"❌ Failed with status {response.status}: {result}")
                return False
        
        # Check overlay
        print("🔍 Checking overlay...")
        time.sleep(1)
        
        with urllib.request.urlopen('http://localhost:8088/overlay', timeout=5) as response:
            data = json.loads(response.read().decode())
            
            if data.get('playtime'):
                playtime_data = data['playtime']
                remaining_time = playtime_data.get('remaining_time', 0)
                
                print("✅ Playtime found in overlay!")
                print(f"   Game: {playtime_data.get('game_name')}")
                print(f"   Time: {playtime_data.get('total_playtime_readable')}")
                print(f"   Remaining: {remaining_time:.1f}s")
                print(f"\n🌐 View at: http://localhost:8088")
                print("   Look for the BLUE notification in the TOP-LEFT corner")
                return True
            else:
                print("❌ No playtime found in overlay")
                return False
                
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--help" or sys.argv[1] == "-h":
            print("Usage: python test_playtime_simple.py [game_name] [hours]")
            print("Examples:")
            print("  python test_playtime_simple.py")
            print("  python test_playtime_simple.py 'Cyberpunk 2077' 156.7")
            print("  python test_playtime_simple.py 'Elden Ring' 89.2")
            sys.exit(0)
    
    game_name = sys.argv[1] if len(sys.argv) > 1 else None
    hours = float(sys.argv[2]) if len(sys.argv) > 2 else None
    
    send_playtime(game_name, hours)