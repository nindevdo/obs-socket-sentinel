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

logger = logging.getLogger(__name__)

class OBSController:
    """Manages connection to OBS WebSocket and provides control methods"""
    
    def __init__(self, host: str = "localhost", port: int = 4455, password: str = ""):
        self.host = host
        self.port = port
        self.password = password
        self.client: Optional[ReqClient] = None
        self.connected = False
        
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
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to OBS: {e}")
            self.connected = False
    
    def _connect_sync(self):
        """Synchronous connect for obsws-python"""
        self.client = ReqClient(host=self.host, port=self.port, password=self.password)
        self.connected = True
            
    async def disconnect(self):
        """Disconnect from OBS WebSocket"""
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
    
    async def create_stream_marker(self, description: str = "Highlight") -> bool:
        """Create a stream marker (bookmark) and save replay buffer if available"""
        if not self.connected or not self.client:
            return False
            
        try:
            import time
            timestamp = time.strftime("%H:%M:%S")
            
            # Try to save replay buffer if it's running
            replay_saved = False
            try:
                replay_status = self.client.get_replay_buffer_status()
                if replay_status and replay_status.output_active:
                    # Replay buffer is active, save it
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self.client.save_replay_buffer)
                    logger.info(f"💾 Replay buffer saved at [{timestamp}]")
                    replay_saved = True
                else:
                    logger.debug("Replay buffer not active, skipping save")
            except Exception as replay_error:
                logger.debug(f"Replay buffer not available: {replay_error}")
            
            # Check if streaming is active and log marker
            stream_status = self.client.get_stream_status()
            if stream_status and stream_status.output_active:
                logger.info(f"🔖 Stream Marker: [{timestamp}] {description}")
                
                # In the future, this could integrate with Twitch/YouTube APIs for actual markers
                # For now, we're logging the marker with timestamp
                return True
            elif replay_saved:
                # Even if not streaming, if we saved replay, consider it a success
                logger.info(f"🔖 Highlight saved: [{timestamp}] {description}")
                return True
            else:
                logger.warning("Not streaming and replay buffer not active")
                return False
                
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


async def handle_obs_action(action: str, obs_ctrl: OBSController) -> bool:
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
    
    # Stream markers
    elif action == "obs_mark_stream" or action == "obs_clip_that":
        return await obs_ctrl.create_stream_marker("Highlight")
    
    return False
