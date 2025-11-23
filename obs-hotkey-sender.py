#!/usr/bin/env python3
"""
OBS Socket Sentinel - Hotkey Sender (Python)

A Python script that replaces the Lua script for OBS.
Monitors OBS WebSocket for scene changes and provides hotkey functionality
to send actions to the Socket Sentinel server with proper authentication.

Features:
- Secure token authentication (SS_TOKEN)
- Scene-based action gating
- Dynamic config loading from server
- Better error handling and logging
- Flexible hotkey management
"""

import asyncio
import json
import logging
import os
import socket
import sys
import time
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Set

try:
    import obsws_python as obs
    import requests
    import keyboard
except ImportError as e:
    print(f"Missing required dependency: {e}")
    print("Please install required packages:")
    print("pip install obsws-python requests keyboard pyyaml")
    sys.exit(1)

# Configuration
DEFAULT_HOST = "127.0.0.1"
DEFAULT_TCP_PORT = 5678
DEFAULT_HTTP_PORT = 8088
DEFAULT_OBS_HOST = "localhost"
DEFAULT_OBS_PORT = 4455
DEFAULT_OBS_PASSWORD = ""

# Global state
games_config: Dict = {}
current_scene: str = ""
hotkey_bindings: Dict[str, str] = {}  # hotkey -> action_key
obs_client: Optional[obs.ReqClient] = None
current_game: Optional[str] = None


class Config:
    """Configuration management with secure token handling"""
    def __init__(self):
        self.host = os.getenv("SENTINEL_HOST", DEFAULT_HOST)
        self.tcp_port = int(os.getenv("SENTINEL_TCP_PORT", DEFAULT_TCP_PORT))
        self.http_port = int(os.getenv("SENTINEL_HTTP_PORT", DEFAULT_HTTP_PORT))
        self.ss_token = os.getenv("SS_TOKEN", "").strip()
        
        # OBS connection settings
        self.obs_host = os.getenv("OBS_HOST", DEFAULT_OBS_HOST)
        self.obs_port = int(os.getenv("OBS_PORT", DEFAULT_OBS_PORT))
        self.obs_password = os.getenv("OBS_PASSWORD", DEFAULT_OBS_PASSWORD)
        
        # Validate required settings
        if not self.ss_token:
            logging.warning("⚠️  SS_TOKEN not set - requests may fail if server requires authentication")
    
    def get_server_url(self) -> str:
        return f"http://{self.host}:{self.http_port}"
    
    def get_auth_headers(self) -> Dict[str, str]:
        if self.ss_token:
            return {"Authorization": f"Bearer {self.ss_token}"}
        return {}


def setup_logging():
    """Setup logging with appropriate format"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("obs-hotkey-sender.log")
        ]
    )


def normalize_name(name: str) -> str:
    """Normalize scene/game names for comparison"""
    if not name:
        return ""
    return name.lower().replace(" ", "_").replace("-", "_")


def load_config_from_server(config: Config) -> Optional[Dict]:
    """Load YAML configuration from the Socket Sentinel server"""
    try:
        url = f"{config.get_server_url()}/config"
        headers = config.get_auth_headers()
        
        logging.info(f"📡 Fetching config from {url}")
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 401:
            logging.error("🚫 Authentication failed - check SS_TOKEN")
            return None
        elif response.status_code != 200:
            logging.error(f"❌ Config fetch failed: HTTP {response.status_code}")
            return None
        
        # Parse YAML
        config_data = yaml.safe_load(response.text)
        games = config_data.get("games", {})
        
        if not games:
            logging.error("❌ No games found in server config")
            return None
            
        logging.info(f"✅ Loaded config with {len(games)} games: {list(games.keys())}")
        return games
        
    except requests.exceptions.ConnectionError:
        logging.error(f"❌ Could not connect to server at {config.get_server_url()}")
        return None
    except requests.exceptions.Timeout:
        logging.error("❌ Timeout fetching config from server")
        return None
    except yaml.YAMLError as e:
        logging.error(f"❌ Invalid YAML in server config: {e}")
        return None
    except Exception as e:
        logging.error(f"❌ Unexpected error loading config: {e}")
        return None


def send_tcp_message(config: Config, game_key: str, action: str) -> bool:
    """Send action message to Socket Sentinel server via TCP"""
    try:
        # Prepare payload with authentication
        payload_lines = []
        if config.ss_token:
            payload_lines.append(f"token={config.ss_token}")
        payload_lines.append(f"game={game_key}")
        payload_lines.append(f"action={action}")
        payload = "\n".join(payload_lines) + "\n"
        
        # Send via TCP
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((config.host, config.tcp_port))
        sock.send(payload.encode('utf-8'))
        sock.close()
        
        logging.info(f"📤 Sent: game={game_key} action={action} → {config.host}:{config.tcp_port}")
        return True
        
    except socket.error as e:
        logging.error(f"❌ TCP send failed: {e}")
        return False
    except Exception as e:
        logging.error(f"❌ Unexpected error sending TCP message: {e}")
        return False


def connect_to_obs(config: Config) -> Optional[obs.ReqClient]:
    """Connect to OBS WebSocket"""
    try:
        logging.info(f"🔌 Connecting to OBS at {config.obs_host}:{config.obs_port}")
        client = obs.ReqClient(
            host=config.obs_host,
            port=config.obs_port,
            password=config.obs_password
        )
        
        # Test connection
        version_info = client.get_version()
        logging.info(f"✅ Connected to OBS {version_info.obs_version}")
        return client
        
    except Exception as e:
        logging.error(f"❌ Failed to connect to OBS: {e}")
        return None


def get_current_scene_name(obs_client: obs.ReqClient) -> Optional[str]:
    """Get the current active scene name from OBS"""
    try:
        resp = obs_client.get_current_program_scene()
        return resp.current_program_scene_name
    except Exception as e:
        logging.warning(f"⚠️  Could not get current scene: {e}")
        return None


def determine_current_game(scene_name: str, games: Dict) -> Optional[str]:
    """Determine which game is active based on scene name"""
    if not scene_name:
        return None
    
    normalized_scene = normalize_name(scene_name)
    
    # Direct match first
    for game_key in games.keys():
        if normalize_name(game_key) == normalized_scene:
            return game_key
    
    # Partial match
    for game_key in games.keys():
        if normalize_name(game_key) in normalized_scene:
            return game_key
    
    return None


def setup_default_hotkeys(games: Dict) -> Dict[str, tuple]:
    """Setup default hotkey bindings for all game actions"""
    hotkeys = {}
    
    # Default hotkey mappings (can be customized)
    default_mappings = {
        'kill': 'f1',
        'death': 'f2', 
        'headshot': 'f3',
        'downed': 'f4',
        'revive': 'f5',
        'start': 'f9',
        'clear': 'f10',
        'run_start': 'ctrl+f1',
        'run_end': 'ctrl+f2'
    }
    
    for game_key, game_config in games.items():
        actions = game_config.get('actions', {})
        for action_key in actions.keys():
            if action_key in default_mappings:
                hotkey = default_mappings[action_key]
                hotkeys[hotkey] = (game_key, action_key)
                logging.info(f"🔑 Mapped {hotkey} → {game_key}:{action_key}")
    
    return hotkeys


def handle_hotkey(config: Config, game_key: str, action_key: str, current_scene: str):
    """Handle a hotkey press"""
    global current_game
    
    # Scene gating: only allow actions for the current game
    scene_game = determine_current_game(current_scene, games_config)
    
    if scene_game != game_key:
        logging.info(f"🚫 Ignoring {game_key}:{action_key} - current scene '{current_scene}' maps to game '{scene_game}'")
        return
    
    logging.info(f"🎯 Executing {game_key}:{action_key} for scene '{current_scene}'")
    success = send_tcp_message(config, game_key, action_key)
    
    if not success:
        logging.warning(f"⚠️  Failed to send action {game_key}:{action_key}")


def register_hotkeys(config: Config, hotkey_mappings: Dict[str, tuple]):
    """Register all hotkeys with the keyboard library"""
    for hotkey, (game_key, action_key) in hotkey_mappings.items():
        try:
            keyboard.add_hotkey(
                hotkey,
                lambda g=game_key, a=action_key: handle_hotkey(config, g, a, current_scene)
            )
            logging.info(f"✅ Registered hotkey: {hotkey} → {game_key}:{action_key}")
        except Exception as e:
            logging.error(f"❌ Failed to register hotkey {hotkey}: {e}")


def monitor_scene_changes(obs_client: obs.ReqClient):
    """Monitor OBS scene changes"""
    global current_scene, current_game
    
    while True:
        try:
            new_scene = get_current_scene_name(obs_client)
            if new_scene and new_scene != current_scene:
                current_scene = new_scene
                current_game = determine_current_game(current_scene, games_config)
                
                logging.info(f"📺 Scene changed: '{current_scene}' → game: {current_game or 'unknown'}")
            
            time.sleep(1)  # Check every second
            
        except KeyboardInterrupt:
            break
        except Exception as e:
            logging.warning(f"⚠️  Scene monitoring error: {e}")
            time.sleep(5)  # Wait longer on error


def main():
    global games_config, obs_client, current_scene
    
    setup_logging()
    config = Config()
    
    logging.info("🚀 OBS Hotkey Sender starting...")
    logging.info(f"🔗 Target server: {config.get_server_url()}")
    logging.info(f"🎮 OBS connection: {config.obs_host}:{config.obs_port}")
    
    # Load configuration from server
    games_config = load_config_from_server(config)
    if not games_config:
        logging.error("❌ Could not load configuration. Exiting.")
        sys.exit(1)
    
    # Connect to OBS
    obs_client = connect_to_obs(config)
    if not obs_client:
        logging.error("❌ Could not connect to OBS. Exiting.")
        sys.exit(1)
    
    # Get initial scene
    current_scene = get_current_scene_name(obs_client) or ""
    if current_scene:
        logging.info(f"📺 Current scene: '{current_scene}'")
    
    # Setup hotkeys
    hotkey_mappings = setup_default_hotkeys(games_config)
    if not hotkey_mappings:
        logging.error("❌ No hotkeys configured. Exiting.")
        sys.exit(1)
    
    register_hotkeys(config, hotkey_mappings)
    
    logging.info("✅ Hotkey sender ready! Press Ctrl+C to quit.")
    
    try:
        # Start monitoring scene changes in background
        import threading
        monitor_thread = threading.Thread(target=monitor_scene_changes, args=(obs_client,))
        monitor_thread.daemon = True
        monitor_thread.start()
        
        # Keep the main thread alive for hotkey detection
        keyboard.wait()
        
    except KeyboardInterrupt:
        logging.info("👋 Shutting down...")
    except Exception as e:
        logging.error(f"❌ Unexpected error: {e}")
    finally:
        if obs_client:
            obs_client.disconnect()


if __name__ == "__main__":
    main()