#!/usr/bin/env python3
"""
Test script for news endpoint.
Run this inside the running container to test news notifications.
"""

import json
import urllib.request
import urllib.parse
import time
import os

def send_news():
    """Send test news data."""
    
    # Test news data based on the provided payload structure
    news_data = {
        "steam_id": "test_user_123",
        "app_id": "440", 
        "game_name": "Team Fortress 2",
        "news_items": [
            {
                "gid": "1816849002024663",
                "title": "TF2Maps.net 72 Hour Jam 2025",
                "url": "https://steamstore-a.akamaihd.net/news/externalpost/steam_community_announcements/1816849002024663",
                "is_external_url": True,
                "author": "erics",
                "contents": "It's the month before Smissmas, and TF2Maps.net is proud to announce the return of their beloved 72 Hour Jam! They're returning to support their friends over at Doctors Without Borders. Anyone who donates $5 or more to the drive before January 14 is eligible to receive this year's in-game charity item.",
                "feedlabel": "Community Announcements",
                "date": 1764101039,
                "feedname": "steam_community_announcements", 
                "feed_type": 1,
                "appid": 440
            },
            {
                "gid": "1816849002024672",
                "title": "Winter Sale Event Now Live!",
                "url": "https://steamstore-a.akamaihd.net/news/externalpost/tf2_blog/1816849002024672",
                "is_external_url": True,
                "author": "Valve",
                "contents": "The Steam Winter Sale is now live with amazing discounts on Team Fortress 2 items and other great games. Check out the special holiday cosmetics and weapons available for a limited time only!",
                "feedlabel": "TF2 Blog",
                "date": 1764100980,
                "feedname": "tf2_blog",
                "feed_type": 0,
                "appid": 440
            }
        ],
        "timestamp": int(time.time()),  # Use current timestamp for change detection
        "timestamp_iso": "2025-11-25T22:00:35.626Z",
        "new_items_count": 2,
        "total_items_fetched": 5
    }
    
    # Convert to JSON
    data = json.dumps(news_data).encode('utf-8')
    
    # Headers
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {os.getenv("SS_TOKEN", "test_token")}',
    }
    
    try:
        print("📤 Sending news...")
        print(f"📊 Data: {news_data['game_name']} - {len(news_data['news_items'])} items")
        for i, item in enumerate(news_data['news_items'], 1):
            print(f"  {i}. {item['title']} (by {item['author']})")
        
        # Send the request
        req = urllib.request.Request('http://localhost:8088/news', data=data, headers=headers, method='POST')
        
        with urllib.request.urlopen(req, timeout=10) as response:
            resp_data = response.read().decode('utf-8')
            print(f"✅ Response: {resp_data}")
            
            # Give some time for the notification to appear, then check overlay
            print("⏳ Waiting 2 seconds...")
            time.sleep(2)
            
            # Check overlay endpoint to verify
            try:
                with urllib.request.urlopen('http://localhost:8088/overlay', timeout=5) as overlay_resp:
                    overlay_data = json.loads(overlay_resp.read().decode('utf-8'))
                    
                    if overlay_data.get('news'):
                        news_info = overlay_data['news']
                        print(f"✅ News found in overlay!")
                        print(f"🎮 Game: {news_info.get('game_name', 'Unknown')}")
                        items = news_info.get('news_items', [])
                        print(f"📰 Items: {len(items)}")
                        for i, item in enumerate(items[:3], 1):  # Show first 3
                            print(f"  {i}. {item.get('title', 'Untitled')}")
                        if len(items) > 3:
                            print(f"  ... and {len(items)-3} more")
                        remaining = news_info.get('remaining_time', 0)
                        print(f"⏰ Remaining: {remaining/1000:.1f}s")
                    else:
                        print("❌ No news found in overlay")
                        
            except Exception as e:
                print(f"⚠️  Could not verify overlay: {e}")
                
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    send_news()