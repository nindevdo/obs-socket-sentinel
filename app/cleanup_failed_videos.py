#!/usr/local/bin/python
"""
Discord Failed Video Cleanup Script

Reads the failed_videos.json log and optionally deletes those Discord messages
to clean up the channel from broken video links.

Usage:
  python cleanup_failed_videos.py --dry-run    # Show what would be deleted
  python cleanup_failed_videos.py --delete     # Actually delete the messages
  python cleanup_failed_videos.py --reset      # Clear the failed videos log
"""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import List, Set

import discord

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Load config from environment
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0"))
FAILED_VIDEOS_LOG = Path(os.getenv("DISCORD_VIDEO_CACHE_DIR", "/discord/discord_videos")) / "failed_videos.json"

async def load_failed_videos() -> tuple[Set[str], dict]:
    """Load the list of failed video URLs and their details."""
    try:
        if FAILED_VIDEOS_LOG.exists():
            with open(FAILED_VIDEOS_LOG, 'r') as f:
                data = json.load(f)
            
            # Handle both old and new format
            if 'failed_videos' in data:
                # New enhanced format
                failed_details = data['failed_videos']
                failed_urls = set(failed_details.keys())
                logging.info(f"📋 Loaded {len(failed_urls)} failed video URLs (enhanced format) from {FAILED_VIDEOS_LOG}")
                
                # Show statistics
                stats = data.get('statistics', {})
                if stats:
                    logging.info(f"📊 Statistics - Total attempts: {stats.get('total_failure_attempts', 'Unknown')}")
                    error_breakdown = stats.get('error_type_breakdown', {})
                    if error_breakdown:
                        top_errors = sorted(error_breakdown.items(), key=lambda x: x[1], reverse=True)[:3]
                        logging.info(f"🔍 Top error types: {', '.join(f'{k}({v})' for k, v in top_errors)}")
                
                return failed_urls, failed_details
                
            elif 'failed_urls' in data:
                # Old legacy format
                failed_urls = set(data['failed_urls'])
                failed_details = {}
                logging.info(f"📋 Loaded {len(failed_urls)} failed video URLs (legacy format) from {FAILED_VIDEOS_LOG}")
                return failed_urls, failed_details
            else:
                logging.warning(f"❌ Unknown format in failed videos log: {FAILED_VIDEOS_LOG}")
                return set(), {}
        else:
            logging.warning(f"❌ Failed videos log not found: {FAILED_VIDEOS_LOG}")
            return set(), {}
    except Exception as e:
        logging.error(f"❗ Error loading failed videos log: {e}")
        return set(), {}

async def find_messages_with_failed_videos(channel: discord.TextChannel, failed_urls: Set[str], failed_details: dict = None) -> List[tuple[discord.Message, str, str]]:
    """Find Discord messages that contain failed video URLs."""
    messages_to_delete = []
    
    logging.info(f"🔍 Scanning #{channel.name} for messages with failed videos...")
    
    message_count = 0
    async for message in channel.history(limit=None, oldest_first=False):
        message_count += 1
        if message_count % 100 == 0:
            logging.info(f"   Scanned {message_count} messages...")
        
        # Check if message contains any failed URLs
        message_content = message.content.lower()
        
        for failed_url in failed_urls:
            if failed_url.lower() in message_content:
                error_type = "unknown"
                if failed_details and failed_url in failed_details:
                    error_type = failed_details[failed_url].get('error_type', 'unknown')
                    
                messages_to_delete.append((message, failed_url, error_type))
                logging.info(f"🎯 Found message with failed video: {failed_url[:50]}... (ID: {message.id}, Error: {error_type})")
                break
        
        # Also check attachments
        for attachment in message.attachments:
            if attachment.url in failed_urls:
                error_type = "unknown"
                if failed_details and attachment.url in failed_details:
                    error_type = failed_details[attachment.url].get('error_type', 'unknown')
                    
                messages_to_delete.append((message, attachment.url, error_type))
                logging.info(f"🎯 Found attachment with failed video: {attachment.url[:50]}... (ID: {message.id}, Error: {error_type})")
                break
    
    logging.info(f"✅ Scan complete. Found {len(messages_to_delete)} messages to delete out of {message_count} total messages")
    return messages_to_delete

async def delete_messages(messages: List[tuple[discord.Message, str, str]], dry_run: bool = True) -> None:
    """Delete the specified Discord messages."""
    if not messages:
        logging.info("✅ No messages to delete")
        return
    
    if dry_run:
        logging.info(f"🧪 DRY RUN: Would delete {len(messages)} messages:")
        for i, (msg, failed_url, error_type) in enumerate(messages[:10]):  # Show first 10
            logging.info(f"   {i+1}. Message {msg.id}: {msg.content[:80]}...")
            logging.info(f"       Failed URL: {failed_url[:60]}... (Error: {error_type})")
        if len(messages) > 10:
            logging.info(f"   ... and {len(messages) - 10} more messages")
        logging.info("🧪 DRY RUN: Use --delete to actually delete these messages")
        return
    
    logging.info(f"🗑️ DELETING {len(messages)} messages...")
    
    deleted_count = 0
    failed_count = 0
    
    for i, (message, failed_url, error_type) in enumerate(messages):
        try:
            await message.delete()
            deleted_count += 1
            logging.info(f"✅ Deleted message {i+1}/{len(messages)}: {message.id} (contained {failed_url[:40]}..., {error_type})")
            
        except discord.NotFound:
            logging.warning(f"⚠️ Message {message.id} already deleted")
            deleted_count += 1  # Count as success
        except discord.Forbidden:
            logging.error(f"❌ No permission to delete message {message.id}")
            failed_count += 1
        except Exception as e:
            logging.error(f"❌ Error deleting message {message.id}: {e}")
            failed_count += 1
        
        # Add 2 second delay after each delete for gentler rate limiting
        await asyncio.sleep(1)
    
    logging.info(f"🏁 Deletion complete: {deleted_count} deleted, {failed_count} failed")

async def reset_failed_videos_log() -> None:
    """Reset/clear the failed videos log."""
    try:
        if FAILED_VIDEOS_LOG.exists():
            FAILED_VIDEOS_LOG.unlink()
            logging.info(f"🗑️ Cleared failed videos log: {FAILED_VIDEOS_LOG}")
        else:
            logging.info(f"ℹ️ Failed videos log doesn't exist: {FAILED_VIDEOS_LOG}")
    except Exception as e:
        logging.error(f"❗ Error clearing failed videos log: {e}")

async def main():
    parser = argparse.ArgumentParser(description="Cleanup failed Discord videos")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    group.add_argument("--delete", action="store_true", help="Actually delete the messages")
    group.add_argument("--reset", action="store_true", help="Clear the failed videos log")
    
    args = parser.parse_args()
    
    if args.reset:
        await reset_failed_videos_log()
        return
    
    # Validate environment
    if not DISCORD_BOT_TOKEN:
        logging.error("❌ DISCORD_BOT_TOKEN environment variable not set")
        return
    
    if not DISCORD_CHANNEL_ID:
        logging.error("❌ DISCORD_CHANNEL_ID environment variable not set")
        return
    
    # Load failed videos
    failed_urls, failed_details = await load_failed_videos()
    if not failed_urls:
        logging.info("✅ No failed videos to clean up")
        return
    
    # Connect to Discord
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    
    @client.event
    async def on_ready():
        logging.info(f"🤖 Connected to Discord as {client.user}")
        
        try:
            channel = client.get_channel(DISCORD_CHANNEL_ID)
            if not channel:
                logging.error(f"❌ Channel {DISCORD_CHANNEL_ID} not found")
                await client.close()
                return
            
            # Find messages with failed videos
            messages_to_delete = await find_messages_with_failed_videos(channel, failed_urls, failed_details)
            
            # Delete or show what would be deleted
            await delete_messages(messages_to_delete, dry_run=args.dry_run)
            
        except Exception as e:
            logging.error(f"❗ Error during cleanup: {e}", exc_info=True)
        finally:
            await client.close()
    
    # Start the bot
    try:
        await client.start(DISCORD_BOT_TOKEN)
    except Exception as e:
        logging.error(f"❗ Error connecting to Discord: {e}")

if __name__ == "__main__":
    asyncio.run(main())
