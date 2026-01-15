#!/usr/bin/env python3
"""
OBS WebSocket Integration for Socket Sentinel
Provides remote control of OBS scenes, sources, and transitions
"""

import asyncio
import logging
import os
from typing import Dict, List, Optional, Any
from obsws_python import ReqClient
from obsws_python.error import OBSSDKError
from twitch_api import create_twitch_stream_marker, create_twitch_clip

logger = logging.getLogger(__name__)

class OBSController:
    """Manages connection to OBS WebSocket and provides control methods"""
    
    def __init__(self, host: str = "localhost", port: int = 4455, password: str = ""):
        self.host = host
        self.port = port
        self.password = password
        self.client: Optional[ReqClient] = None
        self.connected = False
        self._reconnect_task = None
        self._should_reconnect = True
        
        # Cached OBS state
        self.scenes: List[Dict] = []
        self.current_scene: str = ""
        self.transitions: List[str] = []
        self.current_transition: str = ""
        self.sources: List[Dict] = []
    
    async def connect(self):
        """Connect to OBS WebSocket"""
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._connect_sync)
            logger.info(f"✅ Connected to OBS WebSocket at {self.host}:{self.port}")
            
            # Fetch initial state
            await self.refresh_state()
            
            # Start auto-reconnect task if not already running
            if not self._reconnect_task or self._reconnect_task.done():
                self._reconnect_task = asyncio.create_task(self._auto_reconnect_loop())
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to OBS: {e}")
            self.connected = False
    
    def _connect_sync(self):
        """Synchronous connect for obsws-python"""
        self.client = ReqClient(host=self.host, port=self.port, password=self.password)
        self.connected = True
            
    async def disconnect(self):
        """Disconnect from OBS WebSocket"""
        self._should_reconnect = False  # Stop auto-reconnect
        if self._reconnect_task:
            self._reconnect_task.cancel()
        
        if self.client:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._disconnect_sync)
                logger.info("Disconnected from OBS WebSocket")
            except Exception as e:
                logger.error(f"Error disconnecting from OBS: {e}")
    
    def _disconnect_sync(self):
        """Synchronous disconnect"""
        if self.client:
            self.client.disconnect()
            self.client = None
            self.connected = False
    
    def _is_connection_alive(self) -> bool:
        """Check if the connection is actually alive by testing it"""
        if not self.client or not self.connected:
            return False
        
        try:
            # Try a simple request to check if connection is alive
            self.client.get_version()
            return True
        except Exception as e:
            logger.debug(f"Connection check failed: {e}")
            return False
    
    async def _auto_reconnect_loop(self):
        """Background task that monitors connection and reconnects if needed"""
        logger.info("🔄 Auto-reconnect monitoring started")
        
        while self._should_reconnect:
            try:
                await asyncio.sleep(10)  # Check every 10 seconds
                
                if self.connected and not self._is_connection_alive():
                    logger.warning("⚠️ OBS connection lost, attempting to reconnect...")
                    self.connected = False
                    
                    # Clean up dead connection
                    try:
                        if self.client:
                            self.client = None
                    except:
                        pass
                    
                    # Try to reconnect
                    try:
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, self._connect_sync)
                        await self.refresh_state()
                        logger.info(f"✅ Reconnected to OBS at {self.host}:{self.port}")
                    except Exception as e:
                        logger.error(f"❌ Reconnection failed: {e}")
                        await asyncio.sleep(5)  # Wait before next retry
                        
            except asyncio.CancelledError:
                logger.info("Auto-reconnect task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in auto-reconnect loop: {e}")
                await asyncio.sleep(5)
    
    async def refresh_state(self):
        """Refresh cached OBS state (scenes, sources, transitions)"""
        if not self.connected or not self.client:
            return
            
        try:
            loop = asyncio.get_event_loop()
            state = await loop.run_in_executor(None, self._get_state_sync)
            self.scenes = state['scenes']
            self.current_scene = state['current_scene']
            self.transitions = state['transitions']
            self.current_transition = state['current_transition']
            self.sources = state['sources']
            logger.info(f"📡 OBS State: {len(self.scenes)} scenes, {len(self.transitions)} transitions, {len(self.sources)} sources")
            
        except Exception as e:
            # Check if it's a broken pipe error - attempt reconnection
            if "Broken pipe" in str(e) or "errno 32" in str(e).lower():
                logger.warning(f"Connection lost to OBS (broken pipe), attempting reconnect...")
                self.connected = False
                try:
                    await self.disconnect()
                    await asyncio.sleep(1)
                    await self.connect()
                except Exception as reconnect_error:
                    logger.error(f"Failed to reconnect to OBS: {reconnect_error}")
            else:
                logger.error(f"Error refreshing OBS state: {e}")
    
    def _get_state_sync(self) -> Dict[str, Any]:
        """Synchronously get OBS state"""
        # Get scenes
        scenes_resp = self.client.get_scene_list()
        scenes = scenes_resp.scenes if hasattr(scenes_resp, 'scenes') else []
        current_scene = scenes_resp.current_program_scene_name if hasattr(scenes_resp, 'current_program_scene_name') else ""
        
        # Get transitions
        try:
            trans_resp = self.client.get_scene_transition_list()
            transitions = [t['transitionName'] for t in trans_resp.transitions] if hasattr(trans_resp, 'transitions') else []
            current_transition = trans_resp.current_scene_transition_name if hasattr(trans_resp, 'current_scene_transition_name') else ""
        except:
            transitions = []
            current_transition = ""
        
        # Get sources
        try:
            sources_resp = self.client.get_input_list()
            sources = sources_resp.inputs if hasattr(sources_resp, 'inputs') else []
        except:
            sources = []
        
        return {
            'scenes': scenes,
            'current_scene': current_scene,
            'transitions': transitions,
            'current_transition': current_transition,
            'sources': sources
        }
    
    async def switch_scene(self, scene_name: str) -> bool:
        """Switch to a specific scene"""
        if not self.connected or not self.client:
            logger.error("OBS not connected")
            return False
            
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: self.client.set_current_program_scene(scene_name))
            self.current_scene = scene_name
            logger.info(f"🎬 Switched to scene: {scene_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to switch scene to {scene_name}: {e}")
            return False
    
    async def set_transition(self, transition_name: str) -> bool:
        """Set the current scene transition"""
        if not self.connected or not self.client:
            logger.error("OBS not connected")
            return False
            
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: self.client.set_current_scene_transition(transition_name))
            logger.info(f"✨ Set transition: {transition_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to set transition to {transition_name}: {e}")
            return False
    
    async def toggle_source_visibility(self, scene_name: str, source_name: str) -> bool:
        """Toggle visibility of a source in a scene"""
        if not self.connected or not self.client:
            logger.error("OBS not connected")
            return False
            
        try:
            loop = asyncio.get_event_loop()
            # Get scene item ID
            item_id = await loop.run_in_executor(None, self._get_scene_item_id, scene_name, source_name)
            if item_id == 0:
                return False
            
            # Get current visibility
            resp = await loop.run_in_executor(None, lambda: self.client.get_scene_item_enabled(scene_name, item_id))
            current_enabled = resp.scene_item_enabled if hasattr(resp, 'scene_item_enabled') else False
            
            # Toggle
            await loop.run_in_executor(None, lambda: self.client.set_scene_item_enabled(
                scene_name, item_id, not current_enabled
            ))
            
            logger.info(f"👁️ Toggled {source_name} in {scene_name}: {not current_enabled}")
            return True
        except Exception as e:
            logger.error(f"Failed to toggle source {source_name}: {e}")
            return False
    
    async def enable_source(self, scene_name: str, source_name: str) -> bool:
        """Enable (show) a source in a scene"""
        if not self.connected or not self.client:
            logger.error("OBS not connected")
            return False
            
        try:
            loop = asyncio.get_event_loop()
            item_id = await loop.run_in_executor(None, self._get_scene_item_id, scene_name, source_name)
            if item_id == 0:
                return False
            
            await loop.run_in_executor(None, lambda: self.client.set_scene_item_enabled(
                scene_name, item_id, True
            ))
            
            logger.info(f"👁️ Enabled {source_name} in {scene_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to enable source {source_name}: {e}")
            return False
    
    async def disable_source(self, scene_name: str, source_name: str) -> bool:
        """Disable (hide) a source in a scene"""
        if not self.connected or not self.client:
            logger.error("OBS not connected")
            return False
            
        try:
            loop = asyncio.get_event_loop()
            item_id = await loop.run_in_executor(None, self._get_scene_item_id, scene_name, source_name)
            if item_id == 0:
                return False
            
            await loop.run_in_executor(None, lambda: self.client.set_scene_item_enabled(
                scene_name, item_id, False
            ))
            
            logger.info(f"👁️ Disabled {source_name} in {scene_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to disable source {source_name}: {e}")
            return False
    
    async def start_streaming(self) -> bool:
        """Start streaming"""
        if not self.connected or not self.client:
            return False
            
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.client.start_stream)
            logger.info("🔴 Started streaming")
            await self.refresh_state()
            return True
        except Exception as e:
            logger.error(f"Failed to start streaming: {e}")
            return False
    
    async def stop_streaming(self) -> bool:
        """Stop streaming"""
        if not self.connected or not self.client:
            return False
            
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.client.stop_stream)
            logger.info("⏹️ Stopped streaming")
            await self.refresh_state()
            return True
        except Exception as e:
            logger.error(f"Failed to stop streaming: {e}")
            return False
    
    async def start_recording(self) -> bool:
        """Start recording"""
        if not self.connected or not self.client:
            return False
            
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.client.start_record)
            logger.info("🔴 Started recording")
            return True
        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            return False
    
    async def stop_recording(self) -> bool:
        """Stop recording"""
        if not self.connected or not self.client:
            return False
            
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.client.stop_record)
            logger.info("⏹️ Stopped recording")
            return True
        except Exception as e:
            logger.error(f"Failed to stop recording: {e}")
            return False
    
    async def start_replay_buffer(self) -> bool:
        """Start replay buffer"""
        if not self.connected or not self.client:
            return False
            
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.client.start_replay_buffer)
            logger.info("▶️ Started replay buffer")
            return True
        except Exception as e:
            logger.error(f"Failed to start replay buffer: {e}")
            return False
    
    async def stop_replay_buffer(self) -> bool:
        """Stop replay buffer"""
        if not self.connected or not self.client:
            return False
            
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.client.stop_replay_buffer)
            logger.info("⏹️ Stopped replay buffer")
            return True
        except Exception as e:
            logger.error(f"Failed to stop replay buffer: {e}")
            return False
    
    async def save_replay_buffer(self) -> bool:
        """Save replay buffer"""
        if not self.connected or not self.client:
            return False
            
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.client.save_replay_buffer)
            logger.info("💾 Saved replay buffer")
            return True
        except Exception as e:
            logger.error(f"Failed to save replay buffer: {e}")
            return False
    
    async def toggle_source_filter(self, source_name: str, filter_name: str) -> bool:
        """Toggle a filter on a source on/off"""
        if not self.connected or not self.client:
            logger.error("OBS not connected")
            return False
        
        try:
            loop = asyncio.get_event_loop()
            
            # Get current filter state
            filter_info = await loop.run_in_executor(
                None, 
                lambda: self.client.get_source_filter(source_name, filter_name)
            )
            
            current_enabled = filter_info.filter_enabled if hasattr(filter_info, 'filter_enabled') else False
            
            # Toggle the filter
            await loop.run_in_executor(
                None,
                lambda: self.client.set_source_filter_enabled(source_name, filter_name, not current_enabled)
            )
            
            status = "ON" if not current_enabled else "OFF"
            logger.info(f"🎨 Toggled filter '{filter_name}' on '{source_name}': {status}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to toggle filter '{filter_name}' on '{source_name}': {e}")
            return False
    
    async def enable_source_filter(self, source_name: str, filter_name: str) -> bool:
        """Enable a filter on a source"""
        if not self.connected or not self.client:
            logger.error("OBS not connected")
            return False
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.client.set_source_filter_enabled(source_name, filter_name, True)
            )
            logger.info(f"✅ Enabled filter '{filter_name}' on '{source_name}'")
            return True
        except Exception as e:
            logger.error(f"Failed to enable filter '{filter_name}': {e}")
            return False
    
    async def disable_source_filter(self, source_name: str, filter_name: str) -> bool:
        """Disable a filter on a source"""
        if not self.connected or not self.client:
            logger.error("OBS not connected")
            return False
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.client.set_source_filter_enabled(source_name, filter_name, False)
            )
            logger.info(f"❌ Disabled filter '{filter_name}' on '{source_name}'")
            return True
        except Exception as e:
            logger.error(f"Failed to disable filter '{filter_name}': {e}")
            return False
    
    async def get_source_filters(self, source_name: str) -> List[Dict]:
        """Get list of all filters on a source"""
        if not self.connected or not self.client:
            return []
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.client.get_source_filter_list(source_name)
            )
            
            filters = result.filters if hasattr(result, 'filters') else []
            logger.info(f"📋 Found {len(filters)} filters on '{source_name}'")
            return filters
            
        except Exception as e:
            logger.error(f"Failed to get filters for '{source_name}': {e}")
            return []
    
    async def set_color_correction_filter(self, source_name: str, filter_name: str, color_name: str) -> bool:
        """
        Set color correction filter to a specific color by updating its hex values
        
        Args:
            source_name: The source (e.g., camera) with the filter
            filter_name: The color correction filter name (e.g., "gb-color")
            color_name: The color to apply (e.g., "blue", "magenta", "cyan")
        
        Returns:
            True if successful, False otherwise
        """
        if not self.connected or not self.client:
            logger.error("OBS not connected")
            return False
        
        # Color palette for GB Camera shader - uses color_1 through color_4
        # These are the exact values from your working filters
        color_palette = {
            "blue": {
                "color_1": 4281077514,
                "color_2": 4285479707,
                "color_3": 4294951982,
                "color_4": 4294965176,
            },
            "mint": {
                "color_1": 4280033037,
                "color_2": 4286082847,
                "color_3": 4291154255,
                "color_4": 4294442457,
            },
            "cold": {
                "color_1": 4278913803,
                "color_2": 4280163870,
                "color_3": 4294933594,
                "color_4": 4294957519,
            },
            "moss": {
                "color_1": 4279705359,
                "color_2": 4283064109,
                "color_3": 4288139119,
                "color_4": 4293982694,
            },
            "purple": {
                "color_1": 4279894034,
                "color_2": 4282715946,
                "color_3": 4294921051,
                "color_4": 4294953151,
            },
            "purp": {  # Alias for purple
                "color_1": 4279894034,
                "color_2": 4282715946,
                "color_3": 4294921051,
                "color_4": 4294953151,
            },
            # Additional colors (custom palettes in ABGR format - not RGB!)
            "red": {
                "color_1": 4278849339,  # ABGR - Dark red
                "color_2": 4279181195,  # Medium-dark red
                "color_3": 4282141926,  # Bright red
                "color_4": 4289771775,  # Light red/pink
            },
            "orange": {
                "color_1": 4279246907,  # ABGR - Dark orange
                "color_2": 4280307851,  # Medium-dark orange
                "color_3": 4282881510,  # Bright orange
                "color_4": 4288731391,  # Light orange
            },
            "yellow": {
                "color_1": 4278860603,  # ABGR - Dark yellow
                "color_2": 4279208843,  # Medium yellow
                "color_3": 4282181350,  # Bright yellow
                "color_4": 4288741375,  # Light yellow
            },
            "green": {
                "color_1": 4278860559,  # ABGR - Dark green
                "color_2": 4279208735,  # Medium-dark green
                "color_3": 4282181196,  # Bright green
                "color_4": 4289789880,  # Light green
            },
            "magenta": {
                "color_1": 4282059323,  # ABGR - Dark magenta
                "color_2": 4287303563,  # Medium magenta
                "color_3": 4293278950,  # Bright magenta
                "color_4": 4294942975,  # Light magenta
            },
            "cyan": {
                "color_1": 4282071818,  # ABGR - Dark cyan
                "color_2": 4287335183,  # Medium cyan
                "color_3": 4293322300,  # Bright cyan
                "color_4": 4294967200,  # Light cyan
            },
            "pink": {
                "color_1": 4280289851,  # ABGR - Dark pink
                "color_2": 4283436939,  # Medium pink
                "color_3": 4287642854,  # Bright pink
                "color_4": 4291862783,  # Light pink
            },
            "normal": {
                "color_1": 0xFF000000,
                "color_2": 0xFF555555,
                "color_3": 0xFFAAAAAA,
                "color_4": 0xFFFFFFFF,
            },
        }
        
        if color_name not in color_palette:
            logger.error(f"Unknown color '{color_name}'. Available: {list(color_palette.keys())}")
            return False
        
        try:
            loop = asyncio.get_event_loop()
            color_settings = color_palette[color_name]
            
            # Update the filter settings with new color values
            await loop.run_in_executor(
                None,
                lambda: self.client.set_source_filter_settings(
                    source_name,
                    filter_name,
                    color_settings,
                    overlay=True  # Only update specified keys, keep other settings
                )
            )
            
            logger.info(f"🎨 Applied color '{color_name}' to filter '{filter_name}' on '{source_name}'")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set color '{color_name}' on filter '{filter_name}': {e}")
            return False
    
    async def switch_color_filter(self, source_name: str, color_name: str, filter_prefix: str = "gb-color") -> bool:
        """
        Switch to a specific color filter by enabling it and disabling all others with same prefix
        
        Args:
            source_name: The source (e.g., camera) to apply filters to
            color_name: The color to enable (e.g., "blue", "magenta")
            filter_prefix: The filter name prefix (default: "gb-color")
        
        Returns:
            True if successful, False otherwise
        """
        if not self.connected or not self.client:
            logger.error("OBS not connected")
            return False
        
        try:
            loop = asyncio.get_event_loop()
            
            # Get all filters on the source
            filters = await self.get_source_filters(source_name)
            
            target_filter_name = f"{filter_prefix} {color_name}"
            color_filters = []
            target_found = False
            
            # Find all color filters
            for filter_info in filters:
                filter_name = filter_info.get('filterName', '')
                if filter_name.startswith(filter_prefix):
                    color_filters.append(filter_name)
                    if filter_name.lower() == target_filter_name.lower():
                        target_found = True
            
            if not target_found:
                logger.warning(f"⚠️ Filter '{target_filter_name}' not found on '{source_name}'. Available: {color_filters}")
                return False
            
            logger.info(f"🎨 Switching to color '{color_name}' on '{source_name}' (disabling {len(color_filters)-1} other colors)")
            
            # Disable all color filters, then enable the target one
            for filter_name in color_filters:
                if filter_name.lower() == target_filter_name.lower():
                    # Enable target filter
                    await loop.run_in_executor(
                        None,
                        lambda fn=filter_name: self.client.set_source_filter_enabled(source_name, fn, True)
                    )
                    logger.info(f"✅ Enabled '{filter_name}'")
                else:
                    # Disable other color filters
                    await loop.run_in_executor(
                        None,
                        lambda fn=filter_name: self.client.set_source_filter_enabled(source_name, fn, False)
                    )
                    logger.debug(f"❌ Disabled '{filter_name}'")
            
            logger.info(f"🎨 Color switched to '{color_name}' on '{source_name}'")
            return True
            
        except Exception as e:
            logger.error(f"Failed to switch color filter to '{color_name}': {e}")
            return False
    
    async def create_stream_marker(self, description: str = "Highlight") -> bool:
        """Create a stream marker (bookmark) and save replay buffer if available"""
        if not self.connected or not self.client:
            return False
            
        try:
            import time
            timestamp = time.strftime("%H:%M:%S")
            
            success = False
            
            # ALWAYS try to save replay buffer if it's running (regardless of streaming)
            replay_saved = False
            try:
                replay_status = self.client.get_replay_buffer_status()
                if replay_status and replay_status.output_active:
                    # Replay buffer is active, save it
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self.client.save_replay_buffer)
                    logger.info(f"💾 Replay buffer saved at [{timestamp}]")
                    replay_saved = True
                    success = True
                else:
                    logger.debug("Replay buffer not active, skipping save")
            except Exception as replay_error:
                logger.debug(f"Replay buffer not available: {replay_error}")
            
            # Check if streaming is active for Twitch actions
            is_streaming = False
            try:
                stream_status = self.client.get_stream_status()
                is_streaming = stream_status and stream_status.output_active
            except Exception as stream_error:
                logger.debug(f"Could not check stream status: {stream_error}")
            
            if is_streaming:
                logger.info(f"🔖 Stream Marker: [{timestamp}] {description}")
                
                # Try Twitch stream marker
                try:
                    marker_result = await create_twitch_stream_marker(description)
                    if marker_result:
                        logger.info(f"✅ Twitch stream marker created: {description}")
                        success = True
                    else:
                        logger.warning("⚠️ Twitch marker creation failed (check credentials/stream)")
                except Exception as twitch_error:
                    logger.error(f"Failed to create Twitch marker: {twitch_error}")
                
                # Try Twitch clip
                try:
                    clip_result = await create_twitch_clip(description)
                    if clip_result and "edit_url" in clip_result:
                        logger.info(f"🎬 Twitch clip created: {clip_result['edit_url']}")
                        success = True
                    else:
                        logger.warning("⚠️ Twitch clip creation failed")
                except Exception as clip_error:
                    logger.error(f"Failed to create Twitch clip: {clip_error}")
                
                # TODO: Add YouTube clip/marker support here when available
            
            # Report result
            if replay_saved and not is_streaming:
                logger.info(f"🔖 Highlight saved to replay buffer: [{timestamp}] {description}")
            elif not success:
                logger.warning("❌ No actions succeeded (not streaming, no replay buffer)")
            
            return success
                
        except Exception as e:
            logger.error(f"Failed to create stream marker: {e}")
            return False
    
    def _get_scene_item_id(self, scene_name: str, source_name: str) -> int:
        """Get scene item ID for a source in a scene"""
        try:
            resp = self.client.get_scene_item_id(scene_name, source_name, 0)
            return resp.scene_item_id if hasattr(resp, 'scene_item_id') else 0
        except Exception as e:
            logger.error(f"Failed to get scene item ID: {e}")
            return 0
    
    def get_dynamic_actions(self) -> Dict[str, Any]:
        """Generate dynamic actions from current OBS state grouped by type"""
        actions = {
            'scenes': {},
            'transitions': {},
            'controls': {}
        }
        
        logger.info(f"[get_dynamic_actions] scenes type: {type(self.scenes)}, count: {len(self.scenes) if self.scenes else 0}")
        if self.scenes and len(self.scenes) > 0:
            logger.info(f"[get_dynamic_actions] First scene: {self.scenes[0]}")
        
        # Get current recording/streaming status without using asyncio in sync context
        is_recording = False
        is_streaming = False
        try:
            if self.client:
                record_status = self.client.get_record_status()
                stream_status = self.client.get_stream_status()
                is_recording = record_status.output_active if record_status else False
                is_streaming = stream_status.output_active if stream_status else False
        except Exception as e:
            logger.warning(f"Could not get OBS status: {e}")
        
        # Scene switching actions
        for scene in self.scenes:
            scene_name = scene.get('sceneName', '') if isinstance(scene, dict) else (scene.sceneName if hasattr(scene, 'sceneName') else str(scene))
            safe_name = f"scene_{scene_name.lower().replace(' ', '_')}"
            is_active = scene_name == self.current_scene
            actions['scenes'][safe_name] = {
                'label': f"🎬 {scene_name}",
                'active': is_active
            }
        
        logger.info(f"[get_dynamic_actions] Generated {len(actions['scenes'])} scenes, {len(actions['transitions'])} transitions")
        
        # Transition actions
        for transition in self.transitions:
            safe_name = f"transition_{transition.lower().replace(' ', '_')}"
            is_active = transition == self.current_transition
            actions['transitions'][safe_name] = {
                'label': f"✨ {transition}",
                'active': is_active
            }
        
        # Streaming/Recording controls - toggle buttons
        actions['controls']['obs_toggle_stream'] = {
            'label': f"{'⏹️ Stop' if is_streaming else '🔴 Start'} Stream",
            'active': is_streaming,
            'streaming': is_streaming
        }
        actions['controls']['obs_toggle_record'] = {
            'label': f"{'⏹️ Stop' if is_recording else '🔴 Start'} Record",
            'active': is_recording,
            'recording': is_recording
        }
        
        # Replay buffer controls
        # Note: We can't easily check replay buffer status without async, so these are always available
        actions['controls']['obs_start_replay_buffer'] = {
            'label': '▶️ Start Buffer',
            'active': False
        }
        actions['controls']['obs_stop_replay_buffer'] = {
            'label': '⏹️ Stop Buffer',
            'active': False
        }
        actions['controls']['obs_save_replay'] = {
            'label': '💾 Save Replay',
            'active': False
        }
        
        return actions


# Global OBS controller instance
_obs_controller: Optional[OBSController] = None


async def get_obs_controller() -> Optional[OBSController]:
    """Get or create the global OBS controller instance"""
    global _obs_controller
    
    if _obs_controller is None:
        # Use existing OBS_IP environment variable
        host = os.getenv("OBS_IP", "localhost")
        port = int(os.getenv("OBS_PORT", "4455"))
        password = os.getenv("OBS_PASSWORD", "")
        
        _obs_controller = OBSController(host, port, password)
        await _obs_controller.connect()
    
    return _obs_controller


async def handle_obs_action(action: str, obs_ctrl: OBSController, description: str = "Highlight") -> bool:
    """Handle OBS-related actions"""
    
    # Scene switching
    if action.startswith("scene_"):
        scene_name = action.replace("scene_", "").replace("_", " ").title()
        # Try to find exact match from cached scenes
        for scene in obs_ctrl.scenes:
            if scene.get('sceneName', '').lower() == scene_name.lower():
                return await obs_ctrl.switch_scene(scene['sceneName'])
        return False
    
    # Transition switching
    elif action.startswith("transition_"):
        transition_name = action.replace("transition_", "").replace("_", " ").title()
        for transition in obs_ctrl.transitions:
            if transition.lower() == transition_name.lower():
                return await obs_ctrl.set_transition(transition)
        return False
    
    # Streaming controls - support both toggle and explicit actions
    elif action == "obs_toggle_stream":
        # Check current status and toggle
        try:
            if obs_ctrl.client:
                stream_status = obs_ctrl.client.get_stream_status()
                is_streaming = stream_status.output_active if stream_status else False
                if is_streaming:
                    return await obs_ctrl.stop_streaming()
                else:
                    return await obs_ctrl.start_streaming()
            return False
        except Exception as e:
            logger.error(f"Failed to toggle stream: {e}")
            return False
    elif action == "obs_start_stream":
        return await obs_ctrl.start_streaming()
    elif action == "obs_stop_stream":
        return await obs_ctrl.stop_streaming()
    
    # Recording controls - support both toggle and explicit actions
    elif action == "obs_toggle_record":
        # Check current status and toggle
        try:
            if obs_ctrl.client:
                record_status = obs_ctrl.client.get_record_status()
                is_recording = record_status.output_active if record_status else False
                if is_recording:
                    return await obs_ctrl.stop_recording()
                else:
                    return await obs_ctrl.start_recording()
            return False
        except Exception as e:
            logger.error(f"Failed to toggle recording: {e}")
            return False
    elif action == "obs_start_record":
        return await obs_ctrl.start_recording()
    elif action == "obs_stop_record":
        return await obs_ctrl.stop_recording()
    
    # Replay buffer controls
    elif action == "obs_start_replay_buffer":
        return await obs_ctrl.start_replay_buffer()
    elif action == "obs_stop_replay_buffer":
        return await obs_ctrl.stop_replay_buffer()
    elif action == "obs_save_replay":
        return await obs_ctrl.save_replay_buffer()
    
    # Stream markers - now with custom description
    elif action == "obs_mark_stream" or action == "obs_clip_that":
        return await obs_ctrl.create_stream_marker(description)
    
    # Camera visibility controls
    elif action == "obs_camera_on":
        camera_source = os.getenv("OBS_CAMERA_SOURCE", "videocamera")
        current_scene = obs_ctrl.current_scene
        if current_scene:
            result = await obs_ctrl.enable_source(current_scene, camera_source)
            if result:
                logger.info(f"📹 Camera turned ON")
            return result
        return False
    
    elif action == "obs_camera_off":
        camera_source = os.getenv("OBS_CAMERA_SOURCE", "videocamera")
        current_scene = obs_ctrl.current_scene
        if current_scene:
            result = await obs_ctrl.disable_source(current_scene, camera_source)
            if result:
                logger.info(f"📹 Camera turned OFF")
            return result
        return False
    
    elif action == "obs_camera_toggle":
        camera_source = os.getenv("OBS_CAMERA_SOURCE", "videocamera")
        current_scene = obs_ctrl.current_scene
        if current_scene:
            result = await obs_ctrl.toggle_source_visibility(current_scene, camera_source)
            if result:
                logger.info(f"📹 Camera toggled")
            return result
        return False
    
    return False
