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
            self.sources = state['sources']
            logger.info(f"📡 OBS State: {len(self.scenes)} scenes, {len(self.transitions)} transitions, {len(self.sources)} sources")
            
        except Exception as e:
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
        except:
            transitions = []
        
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
            scene_name = scene.get('sceneName', '')
            safe_name = f"scene_{scene_name.lower().replace(' ', '_')}"
            is_active = scene_name == self.current_scene
            actions['scenes'][safe_name] = {
                'label': f"🎬 {scene_name}",
                'active': is_active
            }
        
        # Transition actions
        for transition in self.transitions:
            safe_name = f"transition_{transition.lower().replace(' ', '_')}"
            actions['transitions'][safe_name] = {
                'label': f"✨ {transition}",
                'active': False
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
    
    return False
