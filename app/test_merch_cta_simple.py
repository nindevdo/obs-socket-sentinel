#!/usr/bin/env python3
"""
Simple test script for merch CTA notification.
Run this inside the running container to test merch CTA.
"""

import urllib.request
import json
import sys
import os

def test_merch_cta():
    """Trigger merch CTA via HTTP POST endpoint."""
    
    print("🛍️ Testing Merch CTA Notification")
    print("=" * 40)
    
    try:
        # Send POST to /merch-cta endpoint
        data = json.dumps({}).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {os.getenv("SS_TOKEN", "")}'
        }
        
        req = urllib.request.Request(
            'http://localhost:8088/merch-cta',
            data=data,
            headers=headers,
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.loads(response.read().decode())
            print(f"✅ {result.get('message', 'Merch CTA triggered!')}")
            print(f"   Duration: 12 seconds")
            print(f"   Display: Bottom of screen, purple gradient, horizontal layout")
            print(f"   Items: T-Shirts, Hoodies, Mugs, Hats, Bags")
            print(f"   QR Code: Right side with shop URL")
            print(f"   Sound: /sounds/merch-cta.mp3")
            print()
            print("💡 Tip: Watch your OBS overlay to see it appear!")
            return True
        
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error {e.code}: {e.read().decode()}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = test_merch_cta()
    sys.exit(0 if result else 1)
