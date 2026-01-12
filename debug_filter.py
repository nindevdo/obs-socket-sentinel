#!/usr/bin/env python3
"""
Debug script to inspect OBS filter properties
Run this to see what properties your filter actually has
"""
import asyncio
import os
import sys

sys.path.insert(0, '/app')

async def inspect_filter():
    from obs_controller import get_obs_controller
    
    obs = await get_obs_controller()
    
    if not obs.connected:
        print("❌ OBS not connected")
        return
    
    # Get camera source name from environment or use default
    camera_source = os.getenv("OBS_CAMERA_SOURCE", "Video Capture Device")
    filter_name = os.getenv("OBS_COLOR_FILTER", "gb-color")
    
    print(f"\n🔍 Inspecting filter '{filter_name}' on source '{camera_source}'")
    print("=" * 60)
    
    try:
        loop = asyncio.get_event_loop()
        
        # Get filter info
        filter_info = await loop.run_in_executor(
            None,
            lambda: obs.client.get_source_filter(camera_source, filter_name)
        )
        
        print(f"\n✅ Filter found!")
        print(f"Enabled: {filter_info.filter_enabled}")
        print(f"Kind: {filter_info.filter_kind}")
        print(f"Index: {filter_info.filter_index}")
        
        # Print all settings
        if hasattr(filter_info, 'filter_settings'):
            print(f"\n📋 Filter Settings:")
            print("-" * 60)
            settings = filter_info.filter_settings
            for key, value in settings.items():
                print(f"  {key}: {value} (type: {type(value).__name__})")
        else:
            print("\n⚠️  No filter_settings attribute")
        
        # Try to list all filters on the source
        print(f"\n📋 All filters on '{camera_source}':")
        print("-" * 60)
        filters_list = await obs.get_source_filters(camera_source)
        for f in filters_list:
            fname = f.get('filterName', 'Unknown')
            fkind = f.get('filterKind', 'Unknown')
            fenabled = f.get('filterEnabled', False)
            print(f"  - {fname} ({fkind}) - {'ON' if fenabled else 'OFF'}")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(inspect_filter())
