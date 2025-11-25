#!/usr/bin/env python3
"""
YouTube Playlist to Discord Poster

This module extracts all video URLs from a YouTube playlist and posts them
individually to the configured Discord channel for use with obs-socket-sentinel.
"""

import asyncio
import logging
import os
import sys
import time
from typing import List, Optional, Dict, Any

import aiohttp
import yt_dlp  # type: ignore


# Discord configuration - inherit from main app environment
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID", "").strip()

# Rate limiting to avoid hitting Discord API limits
DISCORD_POST_DELAY = 2.0  # seconds between posts
# Removed MAX_VIDEOS_PER_BATCH - no limits on playlist size


class YouTubePlaylistPoster:
    """Handles extracting YouTube playlist videos and posting them to Discord."""
    
    def __init__(self, bot_token: str, channel_id: str):
        self.bot_token = bot_token
        self.channel_id = channel_id
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def extract_playlist_videos(self, playlist_url: str) -> List[Dict[str, Any]]:
        """
        Extract all video URLs and metadata from a YouTube playlist.
        Returns list of video info dicts.
        """
        if not playlist_url:
            raise ValueError("Playlist URL is required")
        
        logging.info(f"🎬 Extracting videos from playlist: {playlist_url}")
        
        # Configure yt-dlp to extract playlist information without downloading
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,  # Only extract URLs, don't download metadata for each video
            'ignoreerrors': True,  # Skip unavailable videos
        }
        
        # Add cookies if available
        cookies_file = "/app/cookies.txt"
        if os.path.exists(cookies_file):
            ydl_opts["cookiefile"] = cookies_file
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(playlist_url, download=False)
                
                if not info:
                    raise ValueError(f"Could not extract playlist info from: {playlist_url}")
                
                entries = info.get('entries', [])
                if not entries:
                    raise ValueError(f"No videos found in playlist: {playlist_url}")
                
                # Convert to video URLs
                videos = []
                for entry in entries:
                    if not entry:
                        continue
                    
                    video_id = entry.get('id')
                    title = entry.get('title', f'Video {video_id}')
                    
                    if video_id:
                        # Convert to standard YouTube watch URL
                        video_url = f"https://www.youtube.com/watch?v={video_id}"
                        videos.append({
                            'url': video_url,
                            'title': title,
                            'id': video_id
                        })
                
                logging.info(f"📊 Extracted {len(videos)} videos from playlist")
                return videos
                
        except Exception as e:
            logging.error(f"❗ Failed to extract playlist: {e}")
            raise
    
    async def get_existing_youtube_urls(self, limit: int = 100) -> set[str]:
        """
        Fetch existing YouTube URLs from Discord channel to avoid duplicates.
        Returns a set of YouTube URLs that have already been posted.
        Note: Discord API limits message fetching to 100 messages per request.
        """
        if not self.session:
            raise RuntimeError("Session not initialized - use async context manager")
            
        # Discord API limits to 100 messages maximum
        api_limit = min(limit, 100)
            
        existing_urls = set()
        url = f"https://discord.com/api/v10/channels/{self.channel_id}/messages?limit={api_limit}"
        headers = {
            "Authorization": f"Bot {self.bot_token}",
            "User-Agent": "obs-socket-sentinel-playlist-poster/1.0"
        }
        
        try:
            logging.info(f"🔍 Checking last {api_limit} messages in Discord channel for duplicates...")
            async with self.session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    messages = await resp.json()
                    
                    youtube_patterns = [
                        r'https://www\.youtube\.com/watch\?v=([a-zA-Z0-9_-]+)',
                        r'https://youtu\.be/([a-zA-Z0-9_-]+)',
                        r'youtube\.com/watch\?v=([a-zA-Z0-9_-]+)',
                        r'youtu\.be/([a-zA-Z0-9_-]+)'
                    ]
                    
                    import re
                    for message in messages:
                        content = message.get('content', '')
                        
                        # Check for YouTube URLs in message content
                        for pattern in youtube_patterns:
                            matches = re.findall(pattern, content)
                            for video_id in matches:
                                # Normalize to standard format
                                standard_url = f"https://www.youtube.com/watch?v={video_id}"
                                existing_urls.add(standard_url)
                    
                    logging.info(f"📊 Found {len(existing_urls)} existing YouTube videos in last {api_limit} messages")
                    return existing_urls
                    
                else:
                    error_text = await resp.text()
                    logging.warning(f"❗ Failed to fetch existing messages: {resp.status} - {error_text}")
                    return set()
                    
        except Exception as e:
            logging.error(f"❗ Error checking existing messages: {e}")
            return set()

    async def post_message_to_discord(self, content: str) -> bool:
        """
        Post a message to the configured Discord channel.
        Returns True if successful, False otherwise.
        """
        if not self.session:
            raise RuntimeError("Session not initialized - use async context manager")
        
        url = f"https://discord.com/api/v10/channels/{self.channel_id}/messages"
        headers = {
            "Authorization": f"Bot {self.bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "obs-socket-sentinel-playlist-poster/1.0"
        }
        
        payload = {
            "content": content
        }
        
        try:
            async with self.session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200 or resp.status == 204:
                    logging.debug(f"✅ Posted message: {content[:50]}...")
                    return True
                else:
                    error_text = await resp.text()
                    logging.error(f"❗ Discord API error {resp.status}: {error_text}")
                    return False
                    
        except Exception as e:
            logging.error(f"❗ Failed to post message to Discord: {e}")
            return False
    
    async def post_playlist_videos(
        self, 
        playlist_url: str, 
        max_videos: Optional[int] = None,
        delay: float = DISCORD_POST_DELAY,
        check_duplicates: bool = True
    ) -> int:
        """
        Extract videos from playlist and post each one to Discord channel.
        Skips videos that are already posted if check_duplicates is True.
        Returns number of successfully posted videos.
        """
        # Extract videos from playlist
        try:
            videos = self.extract_playlist_videos(playlist_url)
        except Exception as e:
            logging.error(f"❗ Failed to extract playlist videos: {e}")
            return 0
        
        if not videos:
            logging.warning("⚠️ No videos found in playlist")
            return 0
        
        # Check for existing videos to avoid duplicates
        existing_urls = set()
        if check_duplicates:
            existing_urls = await self.get_existing_youtube_urls()
        
        # Filter out duplicates
        if existing_urls:
            original_count = len(videos)
            videos = [v for v in videos if v['url'] not in existing_urls]
            duplicates_found = original_count - len(videos)
            
            if duplicates_found > 0:
                logging.info(f"⚠️ Skipping {duplicates_found} duplicate videos already in channel")
            
            if not videos:
                logging.info("ℹ️ All videos from playlist are already posted in Discord channel")
                return 0
        
        # Apply limit if specified
        if max_videos and max_videos > 0:
            videos = videos[:max_videos]
            logging.info(f"📊 Limited to first {len(videos)} new videos")
        
        # Post each video to Discord
        success_count = 0
        total_videos = len(videos)
        
        logging.info(f"📤 Starting to post {total_videos} new videos to Discord channel {self.channel_id}")
        
        for i, video in enumerate(videos, 1):
            video_url = video['url']
            video_title = video['title']
            
            # Create Discord message content
            message = f"{video_title}\n{video_url}"
            
            # Post to Discord
            success = await self.post_message_to_discord(message)
            
            if success:
                success_count += 1
                logging.info(f"✅ [{i}/{total_videos}] Posted: {video_title}")
            else:
                logging.error(f"❌ [{i}/{total_videos}] Failed to post: {video_title}")
            
            # Rate limiting - delay between posts
            if i < total_videos:  # Don't delay after the last post
                await asyncio.sleep(delay)
        
        logging.info(f"🎯 Successfully posted {success_count}/{total_videos} new videos")
        return success_count


async def main():
    """CLI entry point for posting YouTube playlists to Discord."""
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    # Validate environment
    if not DISCORD_BOT_TOKEN:
        logging.error("❗ DISCORD_BOT_TOKEN environment variable is required")
        return 1
    
    if not DISCORD_CHANNEL_ID:
        logging.error("❗ DISCORD_CHANNEL_ID environment variable is required")
        return 1
    
    # Parse command line arguments
    if len(sys.argv) < 2:
        logging.error("❗ Usage: python youtube_playlist_poster.py <playlist_url> [max_videos]")
        logging.error("   Example: python youtube_playlist_poster.py 'https://www.youtube.com/playlist?list=PLrAXtmRdnEQy6nuLMCSM05Zo1Jzwg_kkF' 25")
        logging.error("   Note: If max_videos is not specified, all videos in the playlist will be posted")
        return 1
    
    playlist_url = sys.argv[1]
    max_videos = None
    
    # Parse remaining arguments
    for arg in sys.argv[2:]:
        if arg.isdigit():
            max_videos = int(arg)
            if max_videos <= 0:
                logging.error("❗ max_videos must be a positive integer")
                return 1
        else:
            logging.error(f"❗ Unknown argument: {arg}")
            return 1
    
    # Apply safety limit - REMOVED: Now supports unlimited videos
    if max_videos and max_videos > 0:
        logging.info(f"📊 User requested limit: {max_videos} videos")
    else:
        logging.info(f"📊 No limit specified - will post all new videos from playlist")
    
    # Post playlist to Discord
    try:
        async with YouTubePlaylistPoster(DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID) as poster:
            success_count = await poster.post_playlist_videos(
                playlist_url=playlist_url,
                max_videos=max_videos,
                delay=DISCORD_POST_DELAY,
                check_duplicates=True  # Always check duplicates
            )
            
            if success_count > 0:
                logging.info(f"🎉 Successfully posted {success_count} videos from playlist!")
                return 0
            else:
                logging.error(f"❌ Failed to post any videos from playlist")
                return 1
                
    except KeyboardInterrupt:
        logging.info("⏹️ Interrupted by user")
        return 130
    except Exception as e:
        logging.error(f"❗ Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))