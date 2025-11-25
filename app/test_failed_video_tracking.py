#!/usr/bin/env python3
"""
Test script to verify failed video tracking is working
"""

import asyncio
import sys
import os
sys.path.insert(0, '/app')

from main import add_failed_video, load_failed_videos, save_failed_videos, failed_video_urls

async def test_failed_video_tracking():
    print("🧪 Testing failed video tracking...")
    
    # Load existing failed videos
    await load_failed_videos()
    print(f"📋 Currently {len(failed_video_urls)} failed videos in memory")
    
    # Add a test failed video
    test_url = "https://www.youtube.com/watch?v=TEST_FAILED_VIDEO"
    await add_failed_video(test_url)
    print(f"✅ Added test URL: {test_url}")
    
    # Verify it's in memory
    if test_url in failed_video_urls:
        print(f"✅ Test URL found in memory: {len(failed_video_urls)} total")
    else:
        print(f"❌ Test URL NOT found in memory")
    
    # Reload and check persistence
    await load_failed_videos()
    if test_url in failed_video_urls:
        print(f"✅ Test URL persisted across reload: {len(failed_video_urls)} total")
    else:
        print(f"❌ Test URL NOT persisted")
    
    print("🏁 Failed video tracking test complete!")

if __name__ == "__main__":
    asyncio.run(test_failed_video_tracking())