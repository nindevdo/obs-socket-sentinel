#!/usr/bin/env python3
"""
Test script for undo functionality in OBS Socket Sentinel.
This script simulates sending actions and then undoing them.
"""

import socket
import time
import json
import sys

def send_tcp_action(host="127.0.0.1", port=5678, action="kill", game="hunt_showdown"):
    """Send an action via TCP to the socket sentinel."""
    try:
        payload = f"game={game}\naction={action}\n"
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((host, port))
        sock.send(payload.encode('utf-8'))
        sock.close()
        print(f"✅ Sent: {action} for {game}")
        return True
    except Exception as e:
        print(f"❌ Failed to send {action}: {e}")
        return False

def get_overlay_state(host="127.0.0.1", port=8088):
    """Get the current overlay state via HTTP."""
    try:
        import urllib.request
        
        url = f"http://{host}:{port}/overlay"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data
    except Exception as e:
        print(f"❌ Failed to get overlay state: {e}")
        return None

def test_undo_functionality():
    """Test the undo functionality with a series of actions."""
    print("🧪 Testing OBS Socket Sentinel Undo Functionality")
    print("=" * 50)
    
    # Test scenario 1: Single action + undo
    print("\n1️⃣ Testing single action + undo")
    send_tcp_action(action="kill")
    time.sleep(1)
    
    state = get_overlay_state()
    if state:
        print(f"   After kill: {state.get('text', 'N/A')}")
    
    send_tcp_action(action="undo")
    time.sleep(1)
    
    state = get_overlay_state()
    if state:
        print(f"   After undo: {state.get('text', 'N/A')}")
    
    # Test scenario 2: Multiple actions + undo
    print("\n2️⃣ Testing multiple actions + undo")
    send_tcp_action(action="kill")
    time.sleep(0.5)
    send_tcp_action(action="kill") 
    time.sleep(0.5)
    send_tcp_action(action="headshot")
    time.sleep(1)
    
    state = get_overlay_state()
    if state:
        print(f"   After 2 kills + headshot: {state.get('text', 'N/A')}")
    
    # Undo the headshot
    send_tcp_action(action="undo")
    time.sleep(1)
    
    state = get_overlay_state()
    if state:
        print(f"   After undo headshot: {state.get('text', 'N/A')}")
    
    # Undo a kill
    send_tcp_action(action="undo")
    time.sleep(1)
    
    state = get_overlay_state()
    if state:
        print(f"   After undo kill: {state.get('text', 'N/A')}")
    
    # Test scenario 3: Undo with empty history
    print("\n3️⃣ Testing undo with empty history")
    send_tcp_action(action="clear")  # Clear everything
    time.sleep(1)
    send_tcp_action(action="undo")   # Try to undo with empty history
    time.sleep(1)
    
    state = get_overlay_state()
    if state:
        print(f"   After undo on empty history: {state.get('text', 'N/A')}")
    
    print("\n✅ Undo functionality test complete!")
    print("\nNote: Make sure OBS Socket Sentinel is running before testing.")

if __name__ == "__main__":
    test_undo_functionality()