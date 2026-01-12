#!/usr/bin/env python3
"""
Twitch API Integration for Socket Sentinel
Handles stream markers and clip creation
"""

import os
import logging
import aiohttp
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Twitch API credentials from environment
TWITCH_CLIENT_ID = os.getenv("TWITCH_API_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_API_CLIENT_SECRET", "")
TWITCH_BROADCASTER_ID = os.getenv("TWITCH_BROADCASTER_ID", "")

# Twitch API endpoints
TWITCH_API_BASE = "https://api.twitch.tv/helix"
TWITCH_OAUTH_URL = "https://id.twitch.tv/oauth2/token"

# Cache for OAuth token
_twitch_token: Optional[str] = None


async def get_twitch_oauth_token() -> Optional[str]:
    """Get OAuth token for Twitch API using client credentials flow"""
    global _twitch_token
    
    # Return cached token if available
    if _twitch_token:
        return _twitch_token
    
    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        logger.warning("Twitch credentials not configured")
        return None
    
    try:
        async with aiohttp.ClientSession() as session:
            params = {
                "client_id": TWITCH_CLIENT_ID,
                "client_secret": TWITCH_CLIENT_SECRET,
                "grant_type": "client_credentials"
            }
            
            async with session.post(TWITCH_OAUTH_URL, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    _twitch_token = data.get("access_token")
                    logger.info("✅ Obtained Twitch OAuth token")
                    return _twitch_token
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to get Twitch OAuth token: {response.status} - {error_text}")
                    return None
    except Exception as e:
        logger.error(f"Error getting Twitch OAuth token: {e}")
        return None


async def create_twitch_stream_marker(description: str = "Highlight") -> bool:
    """
    Create a stream marker on Twitch
    
    Args:
        description: Description for the marker (max 140 characters)
    
    Returns:
        True if successful, False otherwise
    """
    if not TWITCH_BROADCASTER_ID:
        logger.debug("TWITCH_BROADCASTER_ID not configured, skipping Twitch marker")
        return False
    
    token = await get_twitch_oauth_token()
    if not token:
        return False
    
    try:
        # Twitch marker descriptions are limited to 140 characters
        description = description[:140]
        
        url = f"{TWITCH_API_BASE}/streams/markers"
        headers = {
            "Authorization": f"Bearer {token}",
            "Client-Id": TWITCH_CLIENT_ID,
            "Content-Type": "application/json"
        }
        
        payload = {
            "user_id": TWITCH_BROADCASTER_ID,
            "description": description
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    marker_id = data.get("data", [{}])[0].get("id", "unknown")
                    logger.info(f"✅ Created Twitch stream marker: {description} (ID: {marker_id})")
                    return True
                elif response.status == 404:
                    logger.warning("Stream not live or broadcaster not found")
                    return False
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to create Twitch marker: {response.status} - {error_text}")
                    return False
                    
    except Exception as e:
        logger.error(f"Error creating Twitch stream marker: {e}")
        return False


async def create_twitch_clip(description: Optional[str] = None) -> Optional[str]:
    """
    Create a clip on Twitch
    
    Args:
        description: Optional description for the clip
    
    Returns:
        Clip edit URL if successful, None otherwise
    """
    if not TWITCH_BROADCASTER_ID:
        logger.debug("TWITCH_BROADCASTER_ID not configured, skipping Twitch clip")
        return None
    
    token = await get_twitch_oauth_token()
    if not token:
        return None
    
    try:
        url = f"{TWITCH_API_BASE}/clips"
        headers = {
            "Authorization": f"Bearer {token}",
            "Client-Id": TWITCH_CLIENT_ID,
            "Content-Type": "application/json"
        }
        
        params = {
            "broadcaster_id": TWITCH_BROADCASTER_ID
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, params=params) as response:
                if response.status == 202:  # Twitch returns 202 Accepted for clips
                    data = await response.json()
                    clip_data = data.get("data", [{}])[0]
                    edit_url = clip_data.get("edit_url", "")
                    clip_id = clip_data.get("id", "unknown")
                    
                    logger.info(f"✅ Created Twitch clip (ID: {clip_id})")
                    if description:
                        logger.info(f"   Description: {description}")
                    logger.info(f"   Edit URL: {edit_url}")
                    
                    return edit_url
                elif response.status == 404:
                    logger.warning("Stream not live or broadcaster not found")
                    return None
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to create Twitch clip: {response.status} - {error_text}")
                    return None
                    
    except Exception as e:
        logger.error(f"Error creating Twitch clip: {e}")
        return None
