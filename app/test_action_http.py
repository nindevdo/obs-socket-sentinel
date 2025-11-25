#!/usr/bin/env python3
"""
Simple test script for HTTP action endpoint.
Run this to test the new secure HTTP action system.
"""

import urllib.request
import urllib.parse
import json
import time
import sys
import os

def send_action(action=None, game=None):
    """Send a test action via HTTP POST."""
    
    print("🎯 Testing HTTP Action Endpoint")
    print("=" * 40)
    
    # Use custom values or defaults
    action = action or "kill"
    game = game or "hunt_showdown"
    
    action_data = {
        "action": action,
        "game": game
    }
    
    try:
        print(f"📤 Sending action: {action}")
        print(f"   🎮 Game: {game}")
        print("   🔒 Using secure HTTP POST (replaces insecure TCP)")
        
        data = json.dumps(action_data).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {os.getenv("SS_TOKEN", "test_token")}'
        }
        
        req = urllib.request.Request('http://localhost:8088/action', data=data, headers=headers, method='POST')
        
        with urllib.request.urlopen(req, timeout=5) as response:
            result = response.read().decode()
            
            if response.status == 200:
                print("✅ Action sent successfully!")
                print(f"   Response: {result}")
                
                # Parse response to get details
                resp_data = json.loads(result)
                print(f"   Action: {resp_data.get('action')}")
                print(f"   Game: {resp_data.get('game')}")
                return True
            else:
                print(f"❌ Failed with status {response.status}: {result}")
                return False
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if "401" in str(e):
            print("   Check your SS_TOKEN environment variable")
        elif "400" in str(e):
            print("   Check your action/game parameters")
        return False

def test_invalid_action():
    """Test error handling with invalid action."""
    print("\n🧪 Testing Error Handling")
    print("=" * 30)
    
    try:
        action_data = {"action": "invalid_action", "game": "test_game"}
        data = json.dumps(action_data).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {os.getenv("SS_TOKEN", "test_token")}'
        }
        
        req = urllib.request.Request('http://localhost:8088/action', data=data, headers=headers, method='POST')
        
        with urllib.request.urlopen(req, timeout=5) as response:
            result = response.read().decode()
            print(f"❌ Expected error but got success: {result}")
            
    except urllib.error.HTTPError as e:
        if e.code == 400:
            error_response = e.read().decode()
            print(f"✅ Correctly rejected invalid action: {error_response}")
        else:
            print(f"❌ Unexpected error code {e.code}: {e.read().decode()}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--help" or sys.argv[1] == "-h":
            print("Usage: python test_action_http.py [action] [game]")
            print("Examples:")
            print("  python test_action_http.py")
            print("  python test_action_http.py kill hunt_showdown")
            print("  python test_action_http.py headshot")
            print("  python test_action_http.py death pubg")
            sys.exit(0)
    
    action = sys.argv[1] if len(sys.argv) > 1 else None
    game = sys.argv[2] if len(sys.argv) > 2 else None
    
    # Test valid action
    success = send_action(action, game)
    
    # Test invalid action
    if success:
        test_invalid_action()
        print(f"\n🌐 Check overlay at: http://localhost:8088")
        print("   The action should be reflected in the display")