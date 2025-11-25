#!/usr/bin/env python3
"""
Test script to simulate the Lua YAML parser logic
"""

import re

def parse_yaml_like_lua(yaml_text):
    """Simulate the Lua YAML parser logic"""
    games = {}
    current_game = None
    in_games_section = False
    in_actions = False
    in_scenes = False
    
    print("🔍 Parsing YAML line by line:")
    
    for line_num, line in enumerate(yaml_text.split('\n'), 1):
        original_line = line
        trimmed = line.strip()
        
        # Calculate indentation
        leading_spaces = len(line) - len(line.lstrip())
        
        # Debug output for first 20 lines
        if line_num <= 20:
            print(f"{line_num:2d}: {leading_spaces}sp | {repr(trimmed)}")
        
        if not trimmed or trimmed.startswith('#'):
            continue
            
        if trimmed == "games:":
            in_games_section = True
            in_actions = False
            in_scenes = False
            current_game = None
            print(f"    → Found games section")
            
        elif in_games_section and leading_spaces == 2 and re.match(r'^(\w+):$', trimmed):
            # Game name under games: section
            current_game = re.match(r'^(\w+):$', trimmed).group(1)
            games[current_game] = {"actions": [], "scenes": []}
            in_actions = False
            in_scenes = False
            print(f"    → Found game: {current_game}")
            
        elif current_game and leading_spaces == 4 and trimmed == "actions:":
            in_actions = True
            in_scenes = False
            print(f"    → Found actions section for {current_game}")
            
        elif current_game and leading_spaces == 4 and trimmed == "scenes:":
            in_actions = False
            in_scenes = True
            print(f"    → Found scenes section for {current_game}")
            
        elif in_actions and current_game and leading_spaces == 6 and re.match(r'^(\w+):\s*', trimmed):
            # Action definition
            action = re.match(r'^(\w+):\s*', trimmed).group(1)
            games[current_game]["actions"].append(action)
            if line_num <= 30:  # Only print first few
                print(f"    → Added action: {action}")
                
        elif in_scenes and current_game and leading_spaces >= 6 and trimmed.startswith('- '):
            # Scene list item
            scene = trimmed[2:].strip()
            games[current_game]["scenes"].append(scene)
            print(f"    → Added scene: {scene}")
    
    return games

# Test with actual config
import urllib.request, os

print("🧪 Testing YAML Parser Logic")
print("=" * 50)

try:
    headers = {'Authorization': f'Bearer {os.getenv("SS_TOKEN", "rematch_garage_culinary_unluckily_unclamped_expansive")}'}
    req = urllib.request.Request('http://localhost:8088/config', headers=headers)
    with urllib.request.urlopen(req) as response:
        config_text = response.read().decode()
        
        print(f"📄 Config size: {len(config_text)} characters")
        print(f"📄 Config lines: {len(config_text.splitlines())}")
        print()
        
        # Parse using our logic
        games = parse_yaml_like_lua(config_text)
        
        print("\n📊 PARSING RESULTS:")
        print(f"Games found: {len(games)}")
        
        for game_name, game_data in games.items():
            action_count = len(game_data["actions"]) 
            scene_count = len(game_data["scenes"])
            print(f"  {game_name}: {action_count} actions, {scene_count} scenes")
            
            if action_count > 0:
                print(f"    Actions: {', '.join(game_data['actions'][:10])}")
                if action_count > 10:
                    print(f"    ... and {action_count - 10} more")
                    
        print(f"\n✅ Parser should work correctly!")
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()