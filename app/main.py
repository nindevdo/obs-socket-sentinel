#!/usr/bin/env python3
from pathlib import Path
import asyncio
import unicodedata
import json
import logging
import mimetypes
import os
import random
import subprocess
import time
from typing import Dict, List, Any, Optional

import aiohttp  # make sure this is installed in the container
import yaml     # pip install pyyaml
import hashlib  # for stable cache filenames
import re       # for YouTube detection

# -----------------------------
# CONFIG / GLOBALS
# -----------------------------
# Task reference so we can cancel/replace timers
overlay_clear_task: Optional[asyncio.Task] = None

# Global references for overlay media
last_sound: Optional[str] = None        # URL string for sound (Discord cached)
last_meme_url: Optional[str] = None     # URL string for meme image/gif (Discord)
last_video_url: Optional[str] = None    # URL string for video (YouTube/direct)
last_video_duration: Optional[float] = None  # Seconds, if known
last_audio_duration: Optional[float] = None  # Audio duration for proper timing

# Recently played media tracking to avoid repetition
recent_media_history: Dict[str, List[str]] = {}  # action_key -> list of recent URLs
RECENT_MEDIA_HISTORY_SIZE = 5  # Remember last 5 items per action

# Where we consider the "recordings/markers" root
WATCH_DIR = Path(os.getenv("WATCH_DIR", "/markers"))

# HTML template file inside the container/project
TEMPLATE_FILE = Path(os.getenv("TEMPLATE_FILE", "/app/overlay_template.html"))

# Legacy env for chapter file; we now use only its *directory*
CHAPTER_FILE_ENV = Path(os.getenv("CHAPTER_FILE", str(WATCH_DIR / "chapters.txt")))
CHAPTER_DIR = CHAPTER_FILE_ENV.parent

# TCP listener (must match Lua / docker-compose)
HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
PORT = int(os.getenv("LISTEN_PORT", "5678"))

# HTTP server for Browser Source
HTTP_HOST = os.getenv("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("HTTP_PORT", "8088"))

# Discord config (for emoji-tagged memes & sounds)
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID", "").strip()
DISCORD_MESSAGES_LIMIT = int(os.getenv("DISCORD_MESSAGES_LIMIT", "100"))

# YAML config path (required)
CONFIG_PATH = Path(os.getenv("SENTINEL_CONFIG", "/app/config.yaml"))

# Discord sound file cache (persistent)
DISCORD_SOUND_CACHE_DIR = Path(
    os.getenv("DISCORD_SOUND_CACHE_DIR", "/discord/discord_sounds")
)

# Discord video file cache (persistent)
DISCORD_VIDEO_CACHE_DIR = Path(
    os.getenv("DISCORD_VIDEO_CACHE_DIR", "/discord/discord_videos")
)

# Loaded from YAML
GAMES_CONFIG: Dict[str, Dict[str, Any]] = {}
GAME_EMOJI_MAP: Dict[str, set] = {}
ALL_ACTION_KEYS: set[str] = set()  # union of all games' actions
DEFAULT_PROJECT_NAME: Optional[str] = None  # used as fallback for chapters / overlay

# -----------------------------
# RUNTIME STATE
# -----------------------------
action_counts: Dict[tuple[str, str], int] = {}  # (project_key, action) -> count
state_lock = asyncio.Lock()
last_overlay_output: str = ""           # current overlay text
last_action: str = ""                   # last action key
last_project: str = ""                  # last project/game key used for overlay

# Chapter file/session state
current_chapter_file: Optional[Path] = None
session_start_wall: Optional[float] = None  # time.time() when "start" was received
CURRENT_SESSION_PROJECT: Optional[str] = None  # game key for current recording session

# -----------------------------
# RUN TRACKING STATE
# -----------------------------
# Which actions count as kills / deaths for run stats
RUN_KILL_ACTIONS = {"kill", "headshot"}
RUN_DEATH_ACTIONS = {"death", "downed"}

# Per-project run counters + current run
run_counters: Dict[str, int] = {}                      # project -> last run number
current_run_by_project: Dict[str, Optional[int]] = {}  # project -> current run number or None

# Per-project+run stats
# key: (project, run_number)
# value: {
#   "kills": int,
#   "deaths": int,
#   "headshots": int,
#   "events": int,
#   "started_at": float,
# }
run_stats_by_project: Dict[tuple[str, int], Dict[str, Any]] = {}

# Finished run history per project (for recap panel)
# project -> [ { "run": int, "kills": int, "deaths": int, "headshots": int, "kd": float } ]
run_history_by_project: Dict[str, List[Dict[str, Any]]] = {}

# How long we show the run recap panel after a run ends
RUN_PANEL_DURATION_SECONDS = 180  # 3 minutes
run_panel_visible_until: Optional[float] = None

# Max number of runs to *display* in the panel (backend-side visual cap)
MAX_VISIBLE_RUNS = 10

# Discord meme/sound cache
discord_messages_cache: List[dict] = []         # all messages from channel
discord_game_caches: Dict[str, List[dict]] = {} # per-game filtered messages
discord_cache_lock = asyncio.Lock()             # to avoid concurrent rebuilds

YOUTUBE_RE = re.compile(r"(youtube\.com|youtu\.be)", re.IGNORECASE)


def apply_anti_repetition_weighting(weighted_candidates: Dict[str, float], action_key: str) -> Dict[str, float]:
    """
    Apply anti-repetition weighting to reduce chances of recently played media.
    Items played more recently get higher penalty.
    """
    if not weighted_candidates:
        return weighted_candidates
        
    recent_list = recent_media_history.get(action_key, [])
    if not recent_list:
        return weighted_candidates
    
    adjusted_candidates = {}
    for url, weight in weighted_candidates.items():
        adjusted_weight = weight
        
        # Check if this URL was recently played
        if url in recent_list:
            # Apply penalty based on recency (most recent = highest penalty)
            recency_index = recent_list.index(url)  # 0 = most recent
            penalty_factor = 1.0 - (0.8 - (recency_index * 0.15))  # 20%, 35%, 50%, 65%, 80% weight
            adjusted_weight = weight * max(0.2, penalty_factor)
            
        adjusted_candidates[url] = adjusted_weight
        
    return adjusted_candidates


def track_played_media(url: str, action_key: str) -> None:
    """
    Track a played media URL to avoid repetition.
    Maintains a rolling history per action.
    """
    if not url or not action_key:
        return
        
    # Get or create history list for this action
    if action_key not in recent_media_history:
        recent_media_history[action_key] = []
    
    history = recent_media_history[action_key]
    
    # Remove if already in list (move to front)
    if url in history:
        history.remove(url)
    
    # Add to front
    history.insert(0, url)
    
    # Trim to size limit
    if len(history) > RECENT_MEDIA_HISTORY_SIZE:
        history[:] = history[:RECENT_MEDIA_HISTORY_SIZE]

# -----------------------------
# LOGGING
# -----------------------------
logging.basicConfig(
    level=logging.INFO,  # set to DEBUG while tuning if you want more logs
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# -----------------------------
# EMOJI / CONFIG HELPERS
# -----------------------------
def normalize_emoji(s: str) -> str:
    """
    Normalize emoji strings so Discord unicode reactions and our mapping line up.
    Strips variation selectors and skin tone modifiers, and applies NFKD.
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    cleaned = []
    for ch in s:
        code = ord(ch)
        # Strip variation selectors
        if code in (0xFE0E, 0xFE0F):
            continue
        # Strip skin tone modifiers
        if 0x1F3FB <= code <= 0x1F3FF:
            continue
        cleaned.append(ch)
    return "".join(cleaned)


def _normalize_name(name: str) -> str:
    if not name:
        return ""
    name = name.lower()
    # strip spaces, underscores, dashes
    return "".join(ch for ch in name if ch.isalnum())


def resolve_game_key(name: Optional[str]) -> Optional[str]:
    """
    Case/format-insensitive lookup of a game key from GAMES_CONFIG.
    """
    if not name:
        return None
    target = _normalize_name(name)
    for key in GAMES_CONFIG.keys():
        if _normalize_name(key) == target:
            return key
    return None


def get_action_emoji(action_key: str, project: Optional[str]) -> str:
    """
    Look up the emoji for a given action under a specific project/game.
    If project doesn't resolve, returns empty string.
    """
    game_key = resolve_game_key(project)
    if not game_key:
        return ""
    game_conf = GAMES_CONFIG.get(game_key, {})
    actions = game_conf.get("actions") or {}
    emoji = actions.get(action_key)
    return emoji or ""


def load_overlay_config() -> None:
    """
    Load YAML config and build:
      - GAMES_CONFIG
      - GAME_EMOJI_MAP
      - ALL_ACTION_KEYS
      - DEFAULT_PROJECT_NAME (from env PROJECT_NAME or first game)

    NOTE: YAML no longer needs (or uses) 'project_name'.
          Only 'games' is required.
    """
    global GAMES_CONFIG, GAME_EMOJI_MAP, ALL_ACTION_KEYS, DEFAULT_PROJECT_NAME

    if not CONFIG_PATH.exists():
        logging.error(f"❌ Config file {CONFIG_PATH} not found. This app requires a YAML config.")
        raise SystemExit(1)

    try:
        cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        logging.info(f"🧾 Loaded config from {CONFIG_PATH}")
    except Exception as e:
        logging.error(f"❌ Failed to read/parse config YAML {CONFIG_PATH}: {e}", exc_info=True)
        raise SystemExit(1)

    GAMES_CONFIG = cfg.get("games", {}) or {}
    if not GAMES_CONFIG:
        logging.error("❌ Config must define 'games' with at least one game.")
        raise SystemExit(1)

    # Build emoji map per game
    GAME_EMOJI_MAP = {}
    for game_key, gconf in GAMES_CONFIG.items():
        emojis = gconf.get("emoji") or []
        if isinstance(emojis, str):
            emojis = [emojis]
        norm_set = {normalize_emoji(e) for e in emojis if e}
        if norm_set:
            GAME_EMOJI_MAP[game_key] = norm_set

    # Build union of all action keys
    ALL_ACTION_KEYS = set()
    for gconf in GAMES_CONFIG.values():
        acts = gconf.get("actions") or {}
        ALL_ACTION_KEYS.update(acts.keys())

    if not ALL_ACTION_KEYS:
        logging.error("❌ No actions defined under any games.*.actions.")
        raise SystemExit(1)

    # Choose a default project name (for chapters, and as fallback)
    effective = os.getenv("PROJECT_NAME", "").strip() or None

    if effective:
        resolved = resolve_game_key(effective)
    else:
        # Fallback to "first game" in YAML
        resolved = next(iter(GAMES_CONFIG.keys()))

    if not resolved:
        logging.error(
            f"❌ Default project '{effective}' not found in config.games. "
            f"Available games: {list(GAMES_CONFIG.keys())}"
        )
        raise SystemExit(1)

    DEFAULT_PROJECT_NAME = resolved
    logging.info(f"🎮 DEFAULT_PROJECT_NAME = {DEFAULT_PROJECT_NAME}")
    logging.info(f"🎮 All games: {list(GAMES_CONFIG.keys())}")


# -----------------------------
# CACHE CLEANUP
# -----------------------------
async def cleanup_old_cache_files() -> None:
    """
    Periodically clean up old cached files to prevent disk space issues.
    Also removes invalid video files (too short or corrupted).
    """
    try:
        import time
        cutoff_time = time.time() - (24 * 60 * 60)  # 24 hours ago
        
        for cache_dir in [DISCORD_SOUND_CACHE_DIR, DISCORD_VIDEO_CACHE_DIR]:
            if not cache_dir.exists():
                continue
                
            cleaned_count = 0
            invalid_count = 0
            
            for file_path in cache_dir.glob("*"):
                try:
                    if not file_path.is_file():
                        continue
                        
                    # Check age
                    if file_path.stat().st_mtime < cutoff_time:
                        file_path.unlink()
                        cleaned_count += 1
                        continue
                        
                    # For video files, also check if they're corrupted (not short)
                    if cache_dir == DISCORD_VIDEO_CACHE_DIR and file_path.suffix == ".mp4":
                        duration = await get_video_duration_from_file(str(file_path))
                        if duration is None:  # Only remove if we can't read duration (corrupted)
                            file_path.unlink()
                            invalid_count += 1
                            logging.info(f"🗑️ [cache] Removed corrupted video file: {file_path}")
                        # Accept all videos with readable duration, even very short ones
                            
                except Exception as e:
                    logging.warning(f"Failed to clean cache file {file_path}: {e}")
                    
            if cleaned_count > 0:
                logging.info(f"🧹 [cache] Cleaned {cleaned_count} old files from {cache_dir}")
            if invalid_count > 0:
                logging.info(f"🗑️ [cache] Removed {invalid_count} invalid video files from {cache_dir}")
                
    except Exception as e:
        logging.error(f"❗ [cache] Error during cache cleanup: {e}")


async def cache_cleanup_task() -> None:
    """
    Background task that periodically cleans up old cache files.
    """
    while True:
        await asyncio.sleep(60 * 60)  # Run every hour
        await cleanup_old_cache_files()


# -----------------------------
# DISCORD CACHE BUILDING
# -----------------------------
def _build_game_caches_from_messages(messages: List[dict]) -> Dict[str, List[dict]]:
    """
    Build a per-game message cache from the full messages list.

    A message belongs to a game if it has at least one reaction whose
    emoji matches one of that game's configured emojis (GAME_EMOJI_MAP).
    """
    if not GAME_EMOJI_MAP:
        logging.info("[discord] No GAME_EMOJI_MAP defined; skipping per-game cache build.")
        return {}

    game_caches: Dict[str, List[dict]] = {g: [] for g in GAME_EMOJI_MAP.keys()}

    for msg in messages:
        reactions = msg.get("reactions") or []
        msg_game_keys = set()

        for r in reactions:
            emoji_obj = r.get("emoji") or {}
            name = emoji_obj.get("name") or ""
            emoji_id = emoji_obj.get("id")

            # Only consider unicode emoji for game-tagging
            if emoji_id is not None:
                continue

            norm = normalize_emoji(name)
            if not norm:
                continue

            for game_key, emoji_set in GAME_EMOJI_MAP.items():
                if norm in emoji_set:
                    msg_game_keys.add(game_key)

        for gk in msg_game_keys:
            game_caches.setdefault(gk, []).append(msg)

    for gk, lst in game_caches.items():
        logging.info(f"[discord] Game cache for '{gk}' has {len(lst)} messages.")

    return game_caches


async def refresh_discord_messages_cache() -> None:
    """
    Fetch messages from the configured Discord channel and cache them in memory.
    Also builds per-game caches using GAME_EMOJI_MAP.
    """
    global discord_messages_cache, discord_game_caches

    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        logging.debug("[discord] Missing bot token or channel id; skipping cache refresh.")
        return

    async with discord_cache_lock:
        api_url = (
            f"https://discord.com/api/v10/channels/"
            f"{DISCORD_CHANNEL_ID}/messages?limit={DISCORD_MESSAGES_LIMIT}"
        )
        headers = {
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            "User-Agent": "obs-socket-sentinel (emoji-meme/sound fetcher, cached)",
        }

        logging.info(
            f"[discord] Refreshing message cache from channel {DISCORD_CHANNEL_ID} "
            f"(limit={DISCORD_MESSAGES_LIMIT})"
        )

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, headers=headers, timeout=10) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logging.warning(
                            f"[discord] Cache refresh got non-200 response {resp.status}: {text[:200]}"
                        )
                        return
                    messages = await resp.json()
        except Exception as e:
            logging.error(f"[discord] Error refreshing message cache: {e}", exc_info=True)
            return

        discord_messages_cache = messages or []
        logging.info(
            f"[discord] Cache refresh complete: {len(discord_messages_cache)} messages cached."
        )

        # Rebuild per-game caches (used by memes; sounds may ignore this)
        discord_game_caches = _build_game_caches_from_messages(discord_messages_cache)


async def warm_cache_all_media() -> None:
    """
    Pre-download ALL media files from Discord messages to local cache for fast playback.
    This ensures no delays during live streaming - everything plays from local files.
    """
    if not discord_messages_cache:
        logging.info("[warm_cache] No messages to warm cache from")
        return
        
    logging.info(f"[warm_cache] Starting warm cache of all media from {len(discord_messages_cache)} messages")
    
    # Collect all media URLs from all messages with deduplication
    audio_urls = set()
    video_urls = set()
    
    VIDEO_EXTS = (".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv")
    AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".webm")
    
    def normalize_url(url: str) -> str:
        """Normalize URL by removing query parameters that don't affect content"""
        import urllib.parse
        import re
        parsed = urllib.parse.urlparse(url)
        
        # For YouTube URLs, normalize to canonical format
        if "youtube.com" in url or "youtu.be" in url:
            video_id = None
            
            # Extract video ID from different YouTube URL formats
            if "watch" in parsed.path and parsed.query:
                # https://www.youtube.com/watch?v=VIDEO_ID
                query_params = urllib.parse.parse_qs(parsed.query)
                if 'v' in query_params:
                    video_id = query_params['v'][0]
            elif "/embed/" in parsed.path:
                # https://www.youtube.com/embed/VIDEO_ID
                video_id = parsed.path.split('/embed/')[-1].split('/')[0]
            elif "/shorts/" in parsed.path:
                # https://www.youtube.com/shorts/VIDEO_ID  
                video_id = parsed.path.split('/shorts/')[-1].split('/')[0]
            elif "youtu.be" in parsed.netloc:
                # https://youtu.be/VIDEO_ID
                video_id = parsed.path.lstrip('/').split('/')[0]
            
            if video_id:
                # Normalize ALL YouTube URLs to watch format for consistent hashing
                return f"https://www.youtube.com/watch?v={video_id}"
            else:
                return url  # Return as-is if video ID can't be extracted
                
        elif "tenor.com" in url:
            # For Tenor, we can remove query params
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        # For Discord CDN, keep the URL as-is since query params matter for auth
        elif "discord" in parsed.netloc:
            return url
        else:
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    
    for msg in discord_messages_cache:
        # Process attachments
        for att in msg.get("attachments", []):
            url = (att.get("url") or "").strip()
            if not url:
                continue
                
            fname = (att.get("filename") or "").lower()
            ctype = (att.get("content_type") or "").lower()
            
            # Check if it's audio
            if (ctype.startswith("audio/") or 
                fname.endswith(AUDIO_EXTS) or 
                any(ext in url.lower() for ext in AUDIO_EXTS)):
                audio_urls.add(url)  # Keep Discord URLs as-is for auth
                
            # Check if it's video  
            elif (ctype.startswith("video/") or 
                  fname.endswith(VIDEO_EXTS) or 
                  any(ext in url.lower() for ext in VIDEO_EXTS)):
                video_urls.add(url)  # Keep Discord URLs as-is for auth
        
        # Process embeds
        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()
            
            # Check for YouTube URLs
            if emb_url and YOUTUBE_RE.search(emb_url):
                video_urls.add(normalize_url(emb_url))  # Normalize YouTube URLs
            elif emb_url and any(ext in emb_url.lower() for ext in VIDEO_EXTS):
                video_urls.add(normalize_url(emb_url))  # Normalize other video URLs
            elif emb_url and any(ext in emb_url.lower() for ext in AUDIO_EXTS):
                audio_urls.add(normalize_url(emb_url))  # Normalize other audio URLs
                
            # Check embed video/audio objects
            video_obj = emb.get("video") or {}
            v_url = (video_obj.get("url") or "").strip()
            if v_url:
                if any(ext in v_url.lower() for ext in VIDEO_EXTS) or YOUTUBE_RE.search(v_url):
                    video_urls.add(normalize_url(v_url))
                    
            audio_obj = emb.get("audio") or {}
            a_url = (audio_obj.get("url") or "").strip()
            if a_url and any(ext in a_url.lower() for ext in AUDIO_EXTS):
                audio_urls.add(normalize_url(a_url))
        
        # Check content for direct links
        content = (msg.get("content") or "").strip()
        if "http" in content:
            parts = content.split()
            for part in parts:
                if not part.startswith("http"):
                    continue
                    
                lower_part = part.lower()
                if any(ext in lower_part for ext in AUDIO_EXTS):
                    audio_urls.add(normalize_url(part))
                elif any(ext in lower_part for ext in VIDEO_EXTS) or YOUTUBE_RE.search(part):
                    video_urls.add(normalize_url(part))
    
    logging.info(f"[warm_cache] Found {len(audio_urls)} unique audio URLs and {len(video_urls)} unique video URLs")
    
    # Pre-cache all audio files with better error handling
    audio_cached = 0
    audio_skipped = 0
    audio_failed = 0
    
    for url in audio_urls:
        try:
            h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
            base_part = url.split("?", 1)[0]
            _, ext = os.path.splitext(os.path.basename(base_part))
            if not ext:
                ext = ".ogg"
            fs_path = DISCORD_SOUND_CACHE_DIR / f"{h}{ext}"
            
            if fs_path.exists() and fs_path.stat().st_size > 0:
                audio_skipped += 1
                continue
                
            result = await cache_discord_audio(url)
            if result:
                audio_cached += 1
            else:
                audio_failed += 1
                logging.warning(f"[warm_cache] Failed to cache audio: {url}")
        except Exception as e:
            audio_failed += 1
            logging.error(f"[warm_cache] Error caching audio {url}: {e}")
    
    # Pre-cache all video files with better error handling
    video_cached = 0
    video_skipped = 0
    video_failed = 0
    
    for url in video_urls:
        try:
            h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
            fs_path = DISCORD_VIDEO_CACHE_DIR / f"{h}.mp4"
            
            if fs_path.exists() and fs_path.stat().st_size > 0:
                # Validate existing cached video
                duration = await get_video_duration_from_file(str(fs_path))
                if duration is not None and duration > 0:  # Accept any positive duration
                    video_skipped += 1
                    continue
                else:
                    # Remove invalid cached video (corrupted, not short)
                    try:
                        fs_path.unlink()
                        logging.info(f"🗑️ [warm_cache] Removed corrupted cached video: {fs_path}")
                    except Exception:
                        pass
                
            result, duration = await cache_discord_video(url)
            if result and duration is not None:
                video_cached += 1
            else:
                video_failed += 1
                logging.warning(f"[warm_cache] Failed to cache video: {url}")
        except Exception as e:
            video_failed += 1
            logging.error(f"[warm_cache] Error caching video {url}: {e}")
    
    logging.info(f"[warm_cache] Complete! Audio: {audio_cached} cached, {audio_skipped} skipped, {audio_failed} failed. Video: {video_cached} cached, {video_skipped} skipped, {video_failed} failed")


async def discord_cache_refresher_task(interval_seconds: int = 600) -> None:
    """
    Background task that periodically rebuilds the Discord message cache and warm-caches all media.
    Default: every 600 seconds (10 minutes).
    """
    while True:
        try:
            await refresh_discord_messages_cache()
            # After refreshing messages, warm cache all media
            await warm_cache_all_media()
        except Exception as e:
            logging.error(f"[discord] Error in periodic cache refresh: {e}", exc_info=True)
        await asyncio.sleep(interval_seconds)


def _select_messages_for_project(project: Optional[str]) -> List[dict]:
    """
    Return the list of messages appropriate for a given project/game.
    Rules:
      - If we have per-game caches and a game cache for that project, use it.
      - Else if per-game caches exist but no cache for that project, return [].
      - Else fall back to full cache (no game filtering).
    """
    if not discord_messages_cache:
        return []

    if not discord_game_caches:
        # no per-game filtering available
        return discord_messages_cache

    if not project:
        # with per-game caches, but no explicit project, we can't disambiguate → []
        logging.info("[discord] No project provided; with per-game caches this returns [].")
        return []

    key = resolve_game_key(project)
    if not key:
        logging.info(f"[discord] Unknown project '{project}'; no per-game cache.")
        return []
    msgs = discord_game_caches.get(key)
    if msgs is None:
        logging.info(f"[discord] No per-game cache for '{key}'; no memes will be selected.")
        return []
    return msgs


# -----------------------------
# CACHED MEDIA LOOKUP (NO DOWNLOADS)
# -----------------------------
async def get_cached_discord_sound(action_key: str, project: Optional[str]) -> Optional[str]:
    """
    Look up a random cached sound for the action/project, but don't download anything.
    Only returns sounds that are already cached locally.
    """
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        return None

    target_emoji = get_action_emoji(action_key, project)
    if not target_emoji:
        return None

    normalized_target = normalize_emoji(target_emoji)
    messages = _select_messages_for_project(project)
    if not messages:
        return None

    # Build list of candidate URLs (same logic as fetch_random_discord_sound)
    weighted_candidates: Dict[str, float] = {}
    AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".webm")

    for msg in messages:
        reactions = msg.get("reactions") or []
        match_weight = 0

        for r in reactions:
            emoji_obj = r.get("emoji") or {}
            name = emoji_obj.get("name") or ""
            emoji_id = emoji_obj.get("id")
            count = r.get("count") or 0

            if count <= 0:
                continue

            matched = False
            if emoji_id is None:
                norm_name = normalize_emoji(name)
                if norm_name == normalized_target:
                    matched = True
            else:
                if name.lower() == action_key.lower():
                    matched = True

            if matched:
                match_weight += count  # Sum all matching emoji reactions

        if match_weight <= 0:
            continue

        # Check attachments
        for att in msg.get("attachments", []):
            url = (att.get("url") or "").strip()
            fname = (att.get("filename") or "").lower()
            ctype = (att.get("content_type") or "").lower()

            if not url:
                continue

            if (ctype.startswith("audio/") or 
                fname.endswith(AUDIO_EXTS) or 
                any(ext in url.lower() for ext in AUDIO_EXTS)):
                
                # Check if this URL is already cached
                h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
                base_part = url.split("?", 1)[0]
                _, ext = os.path.splitext(os.path.basename(base_part))
                if not ext:
                    ext = ".ogg"
                fs_path = DISCORD_SOUND_CACHE_DIR / f"{h}{ext}"
                
                if fs_path.exists() and fs_path.stat().st_size > 0:
                    prev = weighted_candidates.get(f"/dsounds/{h}{ext}", 0.0)
                    weighted_candidates[f"/dsounds/{h}{ext}"] = prev + match_weight

        # Check embeds and content (similar pattern)
        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()
            if emb_url and any(ext in emb_url.lower() for ext in AUDIO_EXTS):
                h = hashlib.sha256(emb_url.encode("utf-8")).hexdigest()[:32]
                base_part = emb_url.split("?", 1)[0]
                _, ext = os.path.splitext(os.path.basename(base_part))
                if not ext:
                    ext = ".ogg"
                fs_path = DISCORD_SOUND_CACHE_DIR / f"{h}{ext}"
                
                if fs_path.exists() and fs_path.stat().st_size > 0:
                    prev = weighted_candidates.get(f"/dsounds/{h}{ext}", 0.0)
                    weighted_candidates[f"/dsounds/{h}{ext}"] = prev + match_weight

    if not weighted_candidates:
        return None

    # Apply anti-repetition weighting to avoid playing same sounds repeatedly
    weighted_candidates = apply_anti_repetition_weighting(weighted_candidates, action_key)

    # Weighted random choice from cached candidates
    items = list(weighted_candidates.items())
    total_weight = sum(w for _, w in items)
    r = random.uniform(0, total_weight)
    upto = 0.0
    for url, w in items:
        upto += w
        if r <= upto:
            # Track this selection to avoid repetition
            track_played_media(url, action_key)
            return url

    # Fallback selection
    chosen = random.choice(list(weighted_candidates.keys()))
    track_played_media(chosen, action_key)
    return chosen


async def get_cached_discord_meme(action_key: str, project: Optional[str]) -> Optional[str]:
    """
    Look up a random cached meme for the action/project, but don't download anything.
    Returns the original URL since memes are served directly (not cached locally).
    """
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        return None

    target_emoji = get_action_emoji(action_key, project)
    if not target_emoji:
        return None

    normalized_target = normalize_emoji(target_emoji)
    messages = _select_messages_for_project(project)
    if not messages:
        return None

    # Build list of candidate meme URLs (same logic as fetch_random_discord_meme)
    weighted_candidates: Dict[str, float] = {}

    for msg in messages:
        reactions = msg.get("reactions") or []
        match_weight = 0

        for r in reactions:
            emoji_obj = r.get("emoji") or {}
            name = emoji_obj.get("name") or ""
            emoji_id = emoji_obj.get("id")
            count = r.get("count") or 0

            if count <= 0:
                continue

            matched = False
            if emoji_id is None:
                norm_name = normalize_emoji(name)
                if norm_name == normalized_target:
                    matched = True
            else:
                if name.lower() == action_key.lower():
                    matched = True

            if matched:
                match_weight += count  # Sum all matching emoji reactions

        if match_weight <= 0:
            continue

        # Check attachments for images/gifs
        for att in msg.get("attachments", []):
            url = (att.get("url") or "").strip()
            fname = (att.get("filename") or "").lower()
            ctype = (att.get("content_type") or "").lower()

            if not url:
                continue

            if (ctype.startswith("image/") or 
                fname.endswith((".gif", ".webp", ".png", ".jpg", ".jpeg")) or 
                any(ext in url.lower() for ext in [".gif", ".webp", ".png", ".jpg", ".jpeg"])):
                url = _normalize_meme_url(url)
                prev = weighted_candidates.get(url, 0.0)
                weighted_candidates[url] = prev + match_weight

        # Check embeds for images/gifs
        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()
            img = emb.get("image") or {}
            thumb = emb.get("thumbnail") or {}

            for label, img_obj in (("image", img), ("thumb", thumb)):
                u = (img_obj.get("url") or img_obj.get("proxy_url") or "").strip()
                if u and any(ext in u.lower() for ext in [".gif", ".webp", ".png", ".jpg", ".jpeg"]):
                    u = _normalize_meme_url(u)
                    prev = weighted_candidates.get(u, 0.0)
                    weighted_candidates[u] = prev + match_weight

            if emb_url and ("tenor.com/view" in emb_url.lower() or 
                           any(ext in emb_url.lower() for ext in [".gif", ".webp"])):
                emb_url = _normalize_meme_url(emb_url)
                prev = weighted_candidates.get(emb_url, 0.0)
                weighted_candidates[emb_url] = prev + match_weight

    if not weighted_candidates:
        return None

    # Apply anti-repetition weighting to avoid playing same memes repeatedly  
    weighted_candidates = apply_anti_repetition_weighting(weighted_candidates, action_key)

    # Weighted random choice
    items = list(weighted_candidates.items())
    total_weight = sum(w for _, w in items)
    r = random.uniform(0, total_weight)
    upto = 0.0
    for url, w in items:
        upto += w
        if r <= upto:
            # Track this selection to avoid repetition
            track_played_media(url, action_key)
            return url

    # Fallback selection
    chosen = random.choice(list(weighted_candidates.keys()))
    track_played_media(chosen, action_key)
    return chosen


async def get_cached_discord_video(action_key: str, project: Optional[str]) -> tuple[Optional[str], Optional[float], Optional[str]]:
    """
    Look up a random cached video for the action/project, but don't download anything.
    Only returns videos that are already cached locally AND have valid duration.
    Returns: (cached_url, duration, original_source_url)
    """
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        return None, None, None

    target_emoji = get_action_emoji(action_key, project)
    if not target_emoji:
        logging.info(f"[video] No target emoji found for action={action_key} project={project}")
        return None, None, None

    normalized_target = normalize_emoji(target_emoji)
    logging.info(f"[video] Looking for videos with emoji '{target_emoji}' (normalized: '{normalized_target}') for action={action_key}")
    
    messages = _select_messages_for_project(project)
    if not messages:
        logging.info(f"[video] No messages found for project={project}")
        return None, None, None

    logging.info(f"[video] Checking {len(messages)} messages for project={project}")

    # Build list of candidate video URLs (same logic as fetch_random_discord_video)
    weighted_candidates: Dict[str, tuple[float, float, str]] = {}  # cache_url -> (weight, duration, original_url)
    VIDEO_EXTS = (".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv")

    for msg in messages:
        msg_id = msg.get("id", "unknown")
        reactions = msg.get("reactions") or []
        match_weight = 0
        
        # Debug: check if this message has any videos at all
        has_video_content = False
        for att in msg.get("attachments", []):
            url = (att.get("url") or "").strip()
            fname = (att.get("filename") or "").lower()
            ctype = (att.get("content_type") or "").lower()
            if (ctype.startswith("video/") or 
                fname.endswith(VIDEO_EXTS) or 
                any(ext in url.lower() for ext in VIDEO_EXTS)):
                has_video_content = True
                break
        
        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()
            if emb_url and (any(ext in emb_url.lower() for ext in VIDEO_EXTS) or YOUTUBE_RE.search(emb_url)):
                has_video_content = True
                break
        
        if has_video_content:
            logging.info(f"[video] Message {msg_id} has video content, checking reactions...")

        for r in reactions:
            emoji_obj = r.get("emoji") or {}
            name = emoji_obj.get("name") or ""
            emoji_id = emoji_obj.get("id")
            count = r.get("count") or 0

            if count <= 0:
                continue

            matched = False
            if emoji_id is None:
                norm_name = normalize_emoji(name)
                if has_video_content:
                    logging.info(f"[video] Message {msg_id}: checking reaction '{name}' (normalized: '{norm_name}') vs target '{normalized_target}'")
                if norm_name == normalized_target:
                    matched = True
                    if has_video_content:
                        logging.info(f"[video] Message {msg_id}: EMOJI MATCH! '{name}' matched target '{target_emoji}'")
            else:
                if name.lower() == action_key.lower():
                    matched = True
                    if has_video_content:
                        logging.info(f"[video] Message {msg_id}: CUSTOM EMOJI MATCH! '{name}' matched action '{action_key}'")

            if matched:
                match_weight += count  # Sum all matching emoji reactions

        if match_weight <= 0:
            if has_video_content:
                logging.info(f"[video] Message {msg_id} has video content but no matching reactions (weight={match_weight})")
            continue
        
        if has_video_content:
            logging.info(f"[video] Message {msg_id} has video content AND matching reactions (weight={match_weight})")

        # Check attachments for videos
        for att in msg.get("attachments", []):
            url = (att.get("url") or "").strip()
            fname = (att.get("filename") or "").lower()
            ctype = (att.get("content_type") or "").lower()

            if not url:
                continue

            if (ctype.startswith("video/") or 
                fname.endswith(VIDEO_EXTS) or 
                any(ext in url.lower() for ext in VIDEO_EXTS)):
                
                # Check if this video is already cached AND valid
                h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
                fs_path = DISCORD_VIDEO_CACHE_DIR / f"{h}.mp4"
                
                logging.info(f"[video] Message {msg_id}: checking attachment video {url[:50]}... -> {fs_path}")
                logging.info(f"[video] Message {msg_id}: full attachment URL for hash: {url}")
                logging.info(f"[video] Message {msg_id}: calculated hash: {h}")
                
                if fs_path.exists() and fs_path.stat().st_size > 0:
                    duration = await get_video_duration_from_file(str(fs_path))
                    logging.info(f"[video] Message {msg_id}: cached file exists, duration={duration}")
                    if duration is not None and duration > 0:  # Accept any positive duration
                        cache_url = f"/dvideos/{h}.mp4"
                        prev_weight, _, _ = weighted_candidates.get(cache_url, (0.0, 0.0, url))
                        weighted_candidates[cache_url] = (prev_weight + match_weight, duration, url)
                        logging.info(f"[video] Message {msg_id}: ADDED video candidate {cache_url} (weight={prev_weight + match_weight}, duration={duration})")
                    else:
                        logging.warning(f"[video] Message {msg_id}: cached file has invalid duration ({duration})")
                else:
                    logging.info(f"[video] Message {msg_id}: cached file NOT found or empty at {fs_path}")

        # Check embeds for videos (including YouTube)
        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()
            if emb_url and (any(ext in emb_url.lower() for ext in VIDEO_EXTS) or YOUTUBE_RE.search(emb_url)):
                h = hashlib.sha256(emb_url.encode("utf-8")).hexdigest()[:32]
                fs_path = DISCORD_VIDEO_CACHE_DIR / f"{h}.mp4"
                
                logging.info(f"[video] Message {msg_id}: checking embed video {emb_url[:50]}... -> {fs_path}")
                logging.info(f"[video] Message {msg_id}: full embed URL for hash: {emb_url}")
                logging.info(f"[video] Message {msg_id}: calculated hash: {h}")
                
                if fs_path.exists() and fs_path.stat().st_size > 0:
                    duration = await get_video_duration_from_file(str(fs_path))
                    logging.info(f"[video] Message {msg_id}: cached file exists, duration={duration}")
                    if duration is not None and duration > 0:  # Accept any positive duration
                        cache_url = f"/dvideos/{h}.mp4"
                        prev_weight, _, _ = weighted_candidates.get(cache_url, (0.0, 0.0, emb_url))
                        weighted_candidates[cache_url] = (prev_weight + match_weight, duration, emb_url)
                        logging.info(f"[video] Message {msg_id}: ADDED video candidate {cache_url} (weight={prev_weight + match_weight}, duration={duration})")
                    else:
                        logging.warning(f"[video] Message {msg_id}: cached file has invalid duration ({duration})")
                else:
                    logging.info(f"[video] Message {msg_id}: cached file NOT found or empty at {fs_path}")
                    # Let's also check what files ARE in the cache directory
                    try:
                        cache_files = list(DISCORD_VIDEO_CACHE_DIR.glob("*.mp4"))
                        logging.info(f"[video] Cache directory has {len(cache_files)} files: {[f.name for f in cache_files[:5]]}")
                    except Exception:
                        pass

    if not weighted_candidates:
        logging.info(f"[video] No valid cached videos found for action={action_key} project={project}")
        return None, None, None

    # Apply anti-repetition weighting to avoid playing same videos repeatedly
    # Convert tuple format to simple format for anti-repetition processing
    simple_candidates = {url: weight for url, (weight, _, _) in weighted_candidates.items()}
    simple_candidates = apply_anti_repetition_weighting(simple_candidates, action_key)
    # Convert back to tuple format
    adjusted_candidates = {url: (simple_candidates[url], weighted_candidates[url][1], weighted_candidates[url][2]) for url in simple_candidates}

    # Weighted random choice from cached candidates
    items = list(adjusted_candidates.items())
    total_weight = sum(weight for _, (weight, _, _) in items)
    r = random.uniform(0, total_weight)
    upto = 0.0
    for url, (weight, duration, original_url) in items:
        upto += weight
        if r <= upto:
            logging.info(f"📺 [cache] Selected cached video for action={action_key}: {url} (duration={duration}s)")
            # Track this selection to avoid repetition
            track_played_media(url, action_key)
            return url, duration, original_url

    # Fallback
    chosen_url, (_, chosen_duration, chosen_original) = random.choice(items)
    logging.info(f"📺 [cache] Fallback selected cached video for action={action_key}: {chosen_url} (duration={chosen_duration}s)")
    track_played_media(chosen_url, action_key)
    return chosen_url, chosen_duration, chosen_original


# -----------------------------
# WEIGHT-AWARE CACHED MEDIA FUNCTIONS  
# -----------------------------

async def get_cached_discord_sound_with_weight(action_key: str, project: Optional[str]) -> tuple[Optional[str], float]:
    """
    Look up a random cached audio for the action/project with emoji weight.
    Returns: (cached_url, total_weight)
    """
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        return None, 0.0

    target_emoji = get_action_emoji(action_key, project)
    if not target_emoji:
        return None, 0.0

    normalized_target = normalize_emoji(target_emoji)
    messages = _select_messages_for_project(project)
    if not messages:
        return None, 0.0

    weighted_candidates: Dict[str, float] = {}
    AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac")

    for msg in messages:
        reactions = msg.get("reactions") or []
        match_weight = 0

        # Calculate emoji weight for this message
        for r in reactions:
            emoji_obj = r.get("emoji") or {}
            name = emoji_obj.get("name") or ""
            emoji_id = emoji_obj.get("id")
            count = r.get("count") or 0

            if count <= 0:
                continue

            matched = False
            if emoji_id is None:
                norm_name = normalize_emoji(name)
                if norm_name == normalized_target:
                    matched = True
            else:
                if name.lower() == action_key.lower():
                    matched = True

            if matched:
                match_weight += count

        if match_weight <= 0:
            continue

        # Check attachments for audio with this weight
        for att in msg.get("attachments", []):
            url = (att.get("url") or "").strip()
            fname = (att.get("filename") or "").lower()
            ctype = (att.get("content_type") or "").lower()

            if not url:
                continue

            if (ctype.startswith("audio/") or 
                fname.endswith(AUDIO_EXTS) or 
                any(ext in url.lower() for ext in AUDIO_EXTS)):
                
                # Check if cached locally
                h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
                base_part = url.split("?", 1)[0]
                _, ext = os.path.splitext(os.path.basename(base_part))
                if not ext:
                    ext = ".ogg"
                fs_path = DISCORD_SOUND_CACHE_DIR / f"{h}{ext}"
                
                if fs_path.exists() and fs_path.stat().st_size > 0:
                    cache_url = f"/dsounds/{h}{ext}"
                    # Accumulate weight for same URL from multiple messages
                    weighted_candidates[cache_url] = weighted_candidates.get(cache_url, 0.0) + match_weight

        # Check embeds for audio
        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()
            if emb_url and any(ext in emb_url.lower() for ext in AUDIO_EXTS):
                h = hashlib.sha256(emb_url.encode("utf-8")).hexdigest()[:32]
                base_part = emb_url.split("?", 1)[0]
                _, ext = os.path.splitext(os.path.basename(base_part))
                if not ext:
                    ext = ".ogg"
                fs_path = DISCORD_SOUND_CACHE_DIR / f"{h}{ext}"
                
                if fs_path.exists() and fs_path.stat().st_size > 0:
                    cache_url = f"/dsounds/{h}{ext}"
                    weighted_candidates[cache_url] = weighted_candidates.get(cache_url, 0.0) + match_weight

    if not weighted_candidates:
        return None, 0.0

    # Apply anti-repetition and weighted selection
    weighted_candidates = apply_anti_repetition_weighting(weighted_candidates, action_key)
    
    # Weighted random choice
    items = list(weighted_candidates.items())
    total_weight = sum(w for _, w in items)
    r = random.uniform(0, total_weight)
    upto = 0.0
    for url, w in items:
        upto += w
        if r <= upto:
            track_played_media(url, action_key)
            return url, w

    # Fallback
    chosen_url, chosen_weight = random.choice(items)
    track_played_media(chosen_url, action_key)
    return chosen_url, chosen_weight


async def get_cached_discord_meme_with_weight(action_key: str, project: Optional[str]) -> tuple[Optional[str], float]:
    """
    Look up a random cached meme for the action/project with emoji weight.
    Returns: (cached_url, total_weight)
    """
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        return None, 0.0

    target_emoji = get_action_emoji(action_key, project)
    if not target_emoji:
        return None, 0.0

    normalized_target = normalize_emoji(target_emoji)
    messages = _select_messages_for_project(project)
    if not messages:
        return None, 0.0

    weighted_candidates: Dict[str, float] = {}

    for msg in messages:
        reactions = msg.get("reactions") or []
        match_weight = 0

        # Calculate emoji weight for this message
        for r in reactions:
            emoji_obj = r.get("emoji") or {}
            name = emoji_obj.get("name") or ""
            emoji_id = emoji_obj.get("id")
            count = r.get("count") or 0

            if count <= 0:
                continue

            matched = False
            if emoji_id is None:
                norm_name = normalize_emoji(name)
                if norm_name == normalized_target:
                    matched = True
            else:
                if name.lower() == action_key.lower():
                    matched = True

            if matched:
                match_weight += count

        if match_weight <= 0:
            continue

        # Check attachments for images
        for att in msg.get("attachments", []):
            url = (att.get("url") or "").strip()
            fname = (att.get("filename") or "").lower()
            ctype = (att.get("content_type") or "").lower()

            if not url:
                continue

            if any(ext in fname for ext in [".gif", ".webp", ".png", ".jpg", ".jpeg"]):
                weighted_candidates[url] = weighted_candidates.get(url, 0.0) + match_weight

        # Check embeds for images/GIFs
        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()
            
            # Check various embed URL types  
            for label, u in [
                ("url", emb.get("url")),
                ("image.url", emb.get("image", {}).get("url")),
                ("thumbnail.url", emb.get("thumbnail", {}).get("url")),
                ("video.thumbnail_url", emb.get("video", {}).get("thumbnail_url"))
            ]:
                if u and any(ext in u.lower() for ext in [".gif", ".webp", ".png", ".jpg", ".jpeg"]):
                    # CRITICAL: Exclude YouTube thumbnails - these should be handled by video logic, not meme logic
                    if "ytimg.com" in u.lower() or "youtube.com" in u.lower():
                        continue  # Skip YouTube thumbnails
                    weighted_candidates[u] = weighted_candidates.get(u, 0.0) + match_weight

            if emb_url and (
                "tenor.com/view" in emb_url.lower()
                or any(ext in emb_url.lower() for ext in [".gif", ".webp"])
            ):
                weighted_candidates[emb_url] = weighted_candidates.get(emb_url, 0.0) + match_weight

    if not weighted_candidates:
        return None, 0.0

    # Apply anti-repetition and weighted selection
    weighted_candidates = apply_anti_repetition_weighting(weighted_candidates, action_key)
    
    # Weighted random choice
    items = list(weighted_candidates.items())
    total_weight = sum(w for _, w in items)
    r = random.uniform(0, total_weight)
    upto = 0.0
    for url, w in items:
        upto += w
        if r <= upto:
            track_played_media(url, action_key)
            return url, w

    # Fallback
    chosen_url, chosen_weight = random.choice(items)
    track_played_media(chosen_url, action_key)
    return chosen_url, chosen_weight


async def get_cached_discord_video_with_weight(action_key: str, project: Optional[str]) -> tuple[Optional[str], float, Optional[float], Optional[str]]:
    """
    Look up a random cached video for the action/project with emoji weight.
    Returns: (cached_url, total_weight, duration, original_source_url)
    """
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        return None, 0.0, None, None

    target_emoji = get_action_emoji(action_key, project)
    if not target_emoji:
        return None, 0.0, None, None

    normalized_target = normalize_emoji(target_emoji)
    messages = _select_messages_for_project(project)
    if not messages:
        return None, 0.0, None, None

    # cache_url -> (weight, duration, original_url)
    weighted_candidates: Dict[str, tuple[float, float, str]] = {}
    VIDEO_EXTS = (".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv")

    for msg in messages:
        reactions = msg.get("reactions") or []
        match_weight = 0

        # Calculate emoji weight for this message
        for r in reactions:
            emoji_obj = r.get("emoji") or {}
            name = emoji_obj.get("name") or ""
            emoji_id = emoji_obj.get("id")
            count = r.get("count") or 0

            if count <= 0:
                continue

            matched = False
            if emoji_id is None:
                norm_name = normalize_emoji(name)
                if norm_name == normalized_target:
                    matched = True
            else:
                if name.lower() == action_key.lower():
                    matched = True

            if matched:
                match_weight += count

        if match_weight <= 0:
            continue

        # Check attachments for videos
        for att in msg.get("attachments", []):
            url = (att.get("url") or "").strip()
            fname = (att.get("filename") or "").lower()
            ctype = (att.get("content_type") or "").lower()

            if not url:
                continue

            if (ctype.startswith("video/") or 
                fname.endswith(VIDEO_EXTS) or 
                any(ext in url.lower() for ext in VIDEO_EXTS)):
                
                h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
                fs_path = DISCORD_VIDEO_CACHE_DIR / f"{h}.mp4"
                
                if fs_path.exists() and fs_path.stat().st_size > 0:
                    duration = await get_video_duration_from_file(str(fs_path))
                    if duration is not None and duration > 0:
                        cache_url = f"/dvideos/{h}.mp4"
                        prev_weight, _, _ = weighted_candidates.get(cache_url, (0.0, duration, url))
                        weighted_candidates[cache_url] = (prev_weight + match_weight, duration, url)

        # Check embeds for videos (including YouTube)
        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()
            if emb_url and (any(ext in emb_url.lower() for ext in VIDEO_EXTS) or YOUTUBE_RE.search(emb_url)):
                h = hashlib.sha256(emb_url.encode("utf-8")).hexdigest()[:32]
                fs_path = DISCORD_VIDEO_CACHE_DIR / f"{h}.mp4"
                
                if fs_path.exists() and fs_path.stat().st_size > 0:
                    duration = await get_video_duration_from_file(str(fs_path))
                    if duration is not None and duration > 0:
                        cache_url = f"/dvideos/{h}.mp4"
                        prev_weight, _, _ = weighted_candidates.get(cache_url, (0.0, duration, emb_url))
                        weighted_candidates[cache_url] = (prev_weight + match_weight, duration, emb_url)

    if not weighted_candidates:
        return None, 0.0, None, None

    # Apply anti-repetition weighting
    simple_candidates = {url: weight for url, (weight, _, _) in weighted_candidates.items()}
    simple_candidates = apply_anti_repetition_weighting(simple_candidates, action_key)
    adjusted_candidates = {url: (simple_candidates[url], weighted_candidates[url][1], weighted_candidates[url][2]) for url in simple_candidates}

    # Weighted random choice
    items = list(adjusted_candidates.items())
    total_weight = sum(weight for _, (weight, _, _) in items)
    r = random.uniform(0, total_weight)
    upto = 0.0
    for url, (weight, duration, original_url) in items:
        upto += weight
        if r <= upto:
            track_played_media(url, action_key)
            return url, weight, duration, original_url

    # Fallback
    chosen_url, (chosen_weight, chosen_duration, chosen_original) = random.choice(items)
    track_played_media(chosen_url, action_key)
    return chosen_url, chosen_weight, chosen_duration, chosen_original



# -----------------------------
# DISCORD MEME SELECTION
# -----------------------------
def _normalize_meme_url(url: str) -> str:
    """
    Try to turn Tenor links into real animated URLs where we can.
    """
    if not url:
        return url

    url_stripped = url.strip()
    lower = url_stripped.lower()

    # Tenor page link: append .gif so Tenor redirects to the media CDN
    if "tenor.com/view" in lower:
        if not lower.endswith(".gif"):
            return url_stripped + ".gif"
        return url_stripped

    # Tenor static thumbnails on media.tenor.com → .gif
    if "media.tenor.com" in lower:
        if lower.endswith(".png"):
            return url_stripped[:-4] + ".gif"
        if lower.endswith(".webp"):
            return url_stripped[:-5] + ".gif"

    return url_stripped


async def fetch_random_discord_meme(action_key: str, project: Optional[str]) -> Optional[str]:
    """
    Choose a random meme image/gif URL for the given action and project from the
    cached Discord messages.

    Requirements for a message to qualify:
      - It must be associated with the target project/game (via GAME_EMOJI_MAP).
      - It must have a reaction that matches the *action emoji* for this action
        under that project (using config.games[project].actions[action_key]).
    """
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        logging.debug("[discord] Missing bot token or channel id; skipping meme fetch.")
        return None

    # Determine action emoji for this project; if none, no memes
    target_emoji = get_action_emoji(action_key, project)
    if not target_emoji:
        logging.debug(
            f"[discord] No emoji mapping for action={action_key} under project={project}; "
            f"skipping meme fetch."
        )
        return None

    normalized_target = normalize_emoji(target_emoji)

    # Lazy-load cache on first use if needed
    if not discord_messages_cache:
        logging.info("[discord] Message cache empty; doing one-time refresh before meme selection.")
        await refresh_discord_messages_cache()

    messages = _select_messages_for_project(project)
    if not messages:
        logging.info(
            f"[discord] No messages available for project={project}; "
            f"cannot select a meme for action={action_key}."
        )
        return None

    logging.info(
        f"[discord] Selecting meme from {len(messages)} cached messages for "
        f"project={project}, action={action_key}, emoji={target_emoji!r}"
    )

    # url -> cumulative weight
    weighted_candidates: Dict[str, float] = {}

    def _add_candidate(url: str, weight: float):
        if not url or weight <= 0:
            return
        url = _normalize_meme_url(url)
        prev = weighted_candidates.get(url, 0.0)
        weighted_candidates[url] = prev + weight

    for msg in messages:
        msg_id = msg.get("id")
        reactions = msg.get("reactions") or []

        match_weight = 0

        for r in reactions:
            emoji_obj = r.get("emoji") or {}
            name = emoji_obj.get("name") or ""
            emoji_id = emoji_obj.get("id")  # None for unicode, string for custom
            count = r.get("count") or 0

            logging.debug(
                f"[discord] Reaction on {msg_id}: name={name!r}, id={emoji_id}, count={count}"
            )

            if count <= 0:
                continue

            matched = False

            if emoji_id is None:
                # Unicode emoji: name is the actual emoji character
                norm_name = normalize_emoji(name)
                if norm_name == normalized_target:
                    matched = True
            else:
                # Custom emoji: allow naming it exactly like the action
                if name.lower() == action_key.lower():
                    matched = True

            if matched:
                match_weight += count  # Sum all matching emoji reactions

        if match_weight <= 0:
            continue  # no matching reaction for this action on this message

        logging.info(
            f"[discord] Cached message {msg_id} has matching reaction for action={action_key} "
            f"with weight={match_weight}"
        )

        # --- Attachments ---
        for att in msg.get("attachments", []):
            url = (att.get("url") or "").strip()
            fname = (att.get("filename") or "").lower()
            ctype = (att.get("content_type") or "").lower()

            logging.info(
                f"[discord] Attachment on {msg_id}: filename={fname}, "
                f"content_type={ctype}, url={url}"
            )

            if not url:
                continue

            if (
                ctype.startswith("image/")
                or fname.endswith((".gif", ".webp", ".png", ".jpg", ".jpeg"))
                or any(ext in url.lower() for ext in [".gif", ".webp", ".png", ".jpg", ".jpeg"])
            ):
                _add_candidate(url, match_weight)

        # --- Embeds ---
        for emb in msg.get("embeds", []):
            emb_type = emb.get("type")
            emb_url = (emb.get("url") or "").strip()
            logging.info(f"[discord] Embed on {msg_id}: type={emb_type}, url={emb_url}")

            img = emb.get("image") or {}
            thumb = emb.get("thumbnail") or {}

            for label, img_obj in (("image", img), ("thumb", thumb)):
                u = (img_obj.get("url") or img_obj.get("proxy_url") or "").strip()
                if u:
                    logging.info(f"[discord] Embed {label} on {msg_id}: url={u}")
                    if any(ext in u.lower() for ext in [".gif", ".webp", ".png", ".jpg", ".jpeg"]):
                        _add_candidate(u, match_weight)

            if emb_url and (
                "tenor.com/view" in emb_url.lower()
                or any(ext in emb_url.lower() for ext in [".gif", ".webp"])
            ):
                _add_candidate(emb_url, match_weight)

        # --- Fallback: content link ---
        content = (msg.get("content") or "").strip()
        if "http" in content:
            parts = content.split()
            for p in parts:
                if not p.startswith("http"):
                    continue

                lower_p = p.lower()
                if (
                    "tenor.com/view" in lower_p
                    or any(ext in lower_p for ext in [".gif", ".webp", ".png", ".jpg", ".jpeg"])
                ):
                    logging.info(f"[discord] Content image candidate on {msg_id}: {p}")
                    _add_candidate(p, match_weight)
                    break

    if not weighted_candidates:
        logging.info(
            f"[discord] No image/GIF candidates found in cache for project={project} "
            f"action={action_key} emoji={target_emoji!r}."
        )
        return None

    # Apply anti-repetition weighting to avoid playing same memes repeatedly
    weighted_candidates = apply_anti_repetition_weighting(weighted_candidates, action_key)

    # Weighted random choice from cached candidates
    items = list(weighted_candidates.items())
    total_weight = sum(w for _, w in items)
    r = random.uniform(0, total_weight)
    upto = 0.0
    for url, w in items:
        upto += w
        if r <= upto:
            logging.info(
                f"🖼️ [discord] Selected cached meme URL for project={project} "
                f"action={action_key}: {url} (weight={w}, total={total_weight})"
            )
            # Track this selection to avoid repetition
            track_played_media(url, action_key)
            return url

    chosen = random.choice(list(weighted_candidates.keys()))
    logging.info(
        f"🖼️ [discord] Fallback selected cached meme URL for project={project} "
        f"action={action_key}: {chosen}"
    )
    # Track this selection to avoid repetition
    track_played_media(chosen, action_key)
    return chosen


# -----------------------------
# DISCORD VIDEO SELECTION
# -----------------------------
async def fetch_random_discord_video(action_key: str, project: Optional[str]) -> tuple[Optional[str], Optional[float]]:
    """
    Choose a random *video* URL (YouTube or direct video file) for the given
    action and project from the cached Discord messages, download/cache it locally,
    and return (local_url, duration_seconds).

    Requirements for a message to qualify:
      - It must be associated with the target project/game (via GAME_EMOJI_MAP).
      - It must have a reaction that matches the *action emoji* for this action
        under the given project (using config.games[project].actions[action_key]).
      - It must contain at least one video-ish attachment / embed / link.
      - A candidate is considered "video" if:
          * attachment/content_type starts with video/
          * filename or URL ends with a known video extension
          * OR the URL looks like a YouTube link (youtube.com / youtu.be)
    """
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        logging.debug("[discord] Missing bot token or channel id; skipping video fetch.")
        return None, None

    target_emoji = get_action_emoji(action_key, project)
    if not target_emoji:
        logging.debug(
            f"[discord] No emoji mapping for action={action_key} under project={project}; "
            f"skipping video fetch."
        )
        return None, None

    normalized_target = normalize_emoji(target_emoji)

    # Lazy-load cache on first use if needed
    if not discord_messages_cache:
        logging.info("[discord] Message cache empty; doing one-time refresh before video selection.")
        await refresh_discord_messages_cache()

    messages = _select_messages_for_project(project)
    if not messages:
        logging.info(
            f"[discord] No messages available for project={project}; "
            f"cannot select a video for action={action_key}."
        )
        return None, None

    logging.info(
        f"[discord] Selecting VIDEO from {len(messages)} cached messages for "
        f"project={project}, action={action_key}, emoji={target_emoji!r}"
    )

    VIDEO_EXTS = (".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv")
    weighted_candidates: Dict[str, float] = {}

    def _looks_like_youtube(u: str) -> bool:
        return bool(YOUTUBE_RE.search(u or ""))

    def _add_candidate(url: str, weight: float):
        if not url or weight <= 0:
            return
        url = url.strip()
        prev = weighted_candidates.get(url, 0.0)
        weighted_candidates[url] = prev + weight

    for msg in messages:
        msg_id = msg.get("id")
        reactions = msg.get("reactions") or []

        match_weight = 0

        for r in reactions:
            emoji_obj = r.get("emoji") or {}
            name = emoji_obj.get("name") or ""
            emoji_id = emoji_obj.get("id")
            count = r.get("count") or 0

            logging.debug(
                f"[discord] (video) Reaction on {msg_id}: name={name!r}, id={emoji_id}, count={count}"
            )

            if count <= 0:
                continue

            matched = False
            if emoji_id is None:
                norm_name = normalize_emoji(name)
                if norm_name == normalized_target:
                    matched = True
            else:
                if name.lower() == action_key.lower():
                    matched = True

            if matched:
                match_weight += count  # Sum all matching emoji reactions for voting weight

        if match_weight <= 0:
            continue

        logging.info(
            f"[discord] Cached message {msg_id} has matching reaction for VIDEO action={action_key} "
            f"with weight={match_weight}"
        )

        # --- Attachments ---
        for att in msg.get("attachments", []):
            url = (att.get("url") or "").strip()
            fname = (att.get("filename") or "").lower()
            ctype = (att.get("content_type") or "").lower()

            logging.info(
                f"[discord] (video) Attachment on {msg_id}: filename={fname}, "
                f"content_type={ctype}, url={url}"
            )

            if not url:
                continue

            lower_url = url.lower()
            if (
                ctype.startswith("video/")
                or fname.endswith(VIDEO_EXTS)
                or any(ext in lower_url for ext in VIDEO_EXTS)
            ):
                _add_candidate(url, match_weight)

        # --- Embeds ---
        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()
            if emb_url:
                lower_emb = emb_url.lower()
                if (
                    any(ext in lower_emb for ext in VIDEO_EXTS)
                    or _looks_like_youtube(emb_url)
                ):
                    logging.info(f"[discord] (video) Embed url on {msg_id}: {emb_url}")
                    _add_candidate(emb_url, match_weight)

            video_obj = emb.get("video") or {}
            v_url = (video_obj.get("url") or "").strip()
            if v_url:
                lower_v = v_url.lower()
                if (
                    any(ext in lower_v for ext in VIDEO_EXTS)
                    or _looks_like_youtube(v_url)
                ):
                    logging.info(f"[discord] (video) Embed video on {msg_id}: {v_url}")
                    _add_candidate(v_url, match_weight)

        # --- Fallback: links in content ---
        content = (msg.get("content") or "").strip()
        if "http" in content:
            parts = content.split()
            for p in parts:
                if not p.startswith("http"):
                    continue
                lower_p = p.lower()
                if (
                    any(ext in lower_p for ext in VIDEO_EXTS)
                    or _looks_like_youtube(p)
                ):
                    logging.info(f"[discord] (video) Content video candidate on {msg_id}: {p}")
                    _add_candidate(p, match_weight)
                    break

    if not weighted_candidates:
        logging.info(
            f"[discord] No VIDEO candidates found in cache for project={project} "
            f"action={action_key} emoji={target_emoji!r}."
        )
        return None, None

    items = list(weighted_candidates.items())
    total_weight = sum(w for _, w in items)
    r = random.uniform(0, total_weight)
    upto = 0.0
    for url, w in items:
        upto += w
        if r <= upto:
            logging.info(
                f"📺 [discord] Selected cached VIDEO URL candidate for project={project} "
                f"action={action_key}: {url} (weight={w}, total={total_weight})"
            )
            # Cache the video before returning
            local_url, duration = await cache_discord_video(url)
            if local_url:
                logging.info(
                    f"📺 [discord] Using local cached video URL: {local_url} "
                    f"for remote {url} (duration={duration}s)"
                )
                return local_url, duration
            else:
                logging.warning(
                    f"❗ [discord] Failed to cache video {url}; trying another candidate."
                )

    chosen = random.choice(list(weighted_candidates.keys()))
    logging.info(
        f"📺 [discord] Fallback selected VIDEO URL candidate for project={project} "
        f"action={action_key}: {chosen}"
    )
    # Cache the fallback video
    local_url, duration = await cache_discord_video(chosen)
    if local_url:
        logging.info(
            f"📺 [discord] Using fallback local cached video URL: {local_url} "
            f"for remote {chosen} (duration={duration}s)"
        )
        return local_url, duration

    logging.error(
        f"❗ [discord] Failed to cache any video for action={action_key} "
        f"(project={project}); returning None."
    )
    return None, None


# -----------------------------
# VIDEO DURATION HELPERS
# -----------------------------
async def get_video_duration_seconds(url: str) -> Optional[float]:
    """
    Best-effort attempt to get video duration in seconds.

    - For YouTube links, uses yt_dlp (if installed) to fetch metadata.
    - For other URLs we currently return None.

    You can pip install yt_dlp in the container to make this work:
        pip install yt_dlp
    """
    if not url:
        return None

    if not YOUTUBE_RE.search(url):
        # For now we don't inspect arbitrary video URLs.
        return None

    try:
        import yt_dlp  # type: ignore
    except ImportError:
        logging.warning(
            "yt_dlp not installed; cannot fetch YouTube duration for %s. "
            "Install it with 'pip install yt_dlp' to enable accurate durations.",
            url,
        )
        return None

    async def _run_yt_dlp(u: str) -> Optional[float]:
        def _inner() -> Optional[float]:
            ydl_opts = {
                "quiet": True,
                "skip_download": True,
                "no_warnings": True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(u, download=False)
                dur = info.get("duration")
                if dur is None:
                    return None
                try:
                    return float(dur)
                except Exception:
                    return None

        return await asyncio.to_thread(_inner)

    try:
        duration = await _run_yt_dlp(url)
        if duration is not None:
            logging.info("⌛ [video] Fetched YouTube duration=%.2fs for %s", duration, url)
        else:
            logging.info("⌛ [video] No duration metadata found for %s", url)
        return duration
    except Exception as e:
        logging.error(f"❗ [video] Error getting duration for {url}: {e}", exc_info=True)
        return None


# -----------------------------
# DISCORD SOUND CACHE HELPERS
# -----------------------------
async def cache_discord_audio(url: str) -> Optional[str]:
    """
    Download a Discord audio URL into an ephemeral cache directory and return
    a local HTTP path like /dsounds/<hashed>.ext that the overlay can play.

    - Files are stored under DISCORD_SOUND_CACHE_DIR
    - Names are based on SHA256(url) + original extension
    """
    if not url:
        return None

    DISCORD_SOUND_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Strip query params, derive extension from URL if possible
    base_part = url.split("?", 1)[0]
    base_name = os.path.basename(base_part)
    _, ext = os.path.splitext(base_name)
    if not ext:
        ext = ".ogg"  # sane default

    # Stable name based on URL hash
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    fname = f"{h}{ext}"
    fs_path = DISCORD_SOUND_CACHE_DIR / fname

    # Check for existing valid cached file
    if fs_path.exists() and fs_path.stat().st_size > 0:
        logging.debug(f"🔊 [discord] Using cached audio for {url[:50]}... -> {fs_path}")
        return f"/dsounds/{fname}"

    # Download and cache with retry logic
    max_retries = 3
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                logging.info(f"🔄 [warm_cache] Retry {attempt}/{max_retries} for audio {url[:50]}...")
                await asyncio.sleep(1 * attempt)  # Exponential backoff
                
            logging.info(f"🔊 [warm_cache] Downloading audio {url[:50]}... -> {fs_path}")
            
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=45),
                connector=aiohttp.TCPConnector(limit=10)
            ) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logging.warning(
                            f"❗ [discord] Failed to download audio {url[:50]}...: "
                            f"status={resp.status}, body={text[:200]!r}"
                        )
                        if resp.status in (404, 403, 410):  # Don't retry for these
                            break
                        continue
                    
                    # Read data in chunks to handle large files
                    data = b""
                    async for chunk in resp.content.iter_chunked(8192):
                        data += chunk
                        
            # Only write if we have data
            if len(data) > 0:
                fs_path.write_bytes(data)
                logging.info(f"💾 [warm_cache] Cached audio {url[:50]}... -> {fs_path} ({len(data)} bytes)")
                return f"/dsounds/{fname}"
            else:
                logging.warning(f"❗ [discord] Empty audio data for {url[:50]}...")
                continue
                
        except asyncio.TimeoutError:
            logging.warning(f"⏱️ [discord] Timeout downloading audio {url[:50]}... (attempt {attempt + 1})")
            continue
        except Exception as e:
            logging.error(f"❗ [discord] Error caching audio {url[:50]}... (attempt {attempt + 1}): {e}")
            if attempt == max_retries - 1:  # Last attempt
                logging.error(f"❗ [discord] Final failure caching audio {url[:50]}...", exc_info=True)
            continue
            
    # Clean up partial file on failure
    if fs_path.exists():
        try:
            fs_path.unlink()
        except Exception:
            pass
    return None


async def cache_discord_video(url: str) -> tuple[Optional[str], Optional[float]]:
    """
    Download a video URL (YouTube or direct) into an ephemeral cache directory and return
    a local HTTP path like /dvideos/<hashed>.mp4 that the overlay can play, plus duration.

    - Files are stored under DISCORD_VIDEO_CACHE_DIR
    - Names are based on SHA256(url) + .mp4 extension
    - Uses yt-dlp for YouTube videos
    - Filters out videos shorter than 0.5 seconds (static images)
    - Returns (local_path, duration_seconds)
    """
    if not url:
        return None, None

    DISCORD_VIDEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Stable name based on URL hash
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    fname = f"{h}.mp4"
    fs_path = DISCORD_VIDEO_CACHE_DIR / fname
    
    logging.info(f"[cache] Caching video with URL: {url}")
    logging.info(f"[cache] Calculated hash: {h}")
    logging.info(f"[cache] Target file path: {fs_path}")

    # Check for existing valid cached file
    if fs_path.exists() and fs_path.stat().st_size > 0:
        logging.debug(f"📺 [discord] Using cached video for {url[:50]}... -> {fs_path}")
        # Try to get duration from existing file
        duration = await get_video_duration_from_file(str(fs_path))
        if duration is None:
            # File is invalid (too short or corrupted), remove it
            try:
                fs_path.unlink()
                logging.info(f"🗑️ [video] Removed invalid cached video: {fs_path}")
            except Exception:
                pass
        else:
            return f"/dvideos/{fname}", duration

    # Check if it's a YouTube video
    is_youtube = bool(YOUTUBE_RE.search(url))
    duration: Optional[float] = None

    # Retry logic for downloads
    max_retries = 2 if is_youtube else 3
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                logging.info(f"🔄 [warm_cache] Retry {attempt}/{max_retries} for video {url[:50]}...")
                await asyncio.sleep(2 * attempt)  # Exponential backoff
                
            logging.info(f"📺 [warm_cache] Downloading video {url[:50]}... -> {fs_path}")
            
            if is_youtube:
                # Use yt-dlp to download YouTube video
                try:
                    import yt_dlp  # type: ignore
                except ImportError:
                    logging.warning(
                        f"yt_dlp not installed; cannot download YouTube video {url[:50]}... "
                        f"Install it with 'pip install yt_dlp' to enable video caching."
                    )
                    return None, None

                async def _download_youtube(u: str) -> Optional[float]:
                    def _inner() -> Optional[float]:
                        ydl_opts = {
                            "format": "best[ext=mp4][height<=720]/best[height<=720]/best",
                            "outtmpl": str(fs_path),
                            "quiet": False,  # Enable logging to see what's happening
                            "no_warnings": False,  # Enable warnings
                            "writesubtitles": False,
                            "writeautomaticsub": False,
                            "writeinfojson": False,
                            "writethumbnail": False,
                            "socket_timeout": 30,
                            "retries": 3,
                            "extract_flat": False,
                            "ignoreerrors": False,
                        }
                        try:
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                logging.info(f"📹 [yt-dlp] Extracting info for {u[:50]}...")
                                info = ydl.extract_info(u, download=True)
                                if not info:
                                    logging.warning(f"❗ [yt-dlp] No info extracted for {u[:50]}...")
                                    return None
                                    
                                dur = info.get("duration")
                                if dur is None:
                                    logging.warning(f"❗ [yt-dlp] No duration in info for {u[:50]}...")
                                    return None
                                try:
                                    duration = float(dur)
                                    if duration > 0:
                                        logging.info(f"✅ [yt-dlp] Downloaded video: {u[:50]}... ({duration}s)")
                                        return duration
                                    else:
                                        logging.warning(f"❗ [yt-dlp] Zero duration video: {u[:50]}...")
                                        return None
                                except Exception as e:
                                    logging.error(f"❗ [yt-dlp] Duration parse error for {u[:50]}...: {e}")
                                    return None
                        except Exception as e:
                            logging.error(f"❗ [yt-dlp] Download failed for {u[:50]}...: {e}")
                            return None

                    return await asyncio.to_thread(_inner)

                duration = await _download_youtube(url)
                if duration is not None and fs_path.exists() and fs_path.stat().st_size > 0:
                    logging.info(f"📹 [warm_cache] Downloaded YouTube video {url[:50]}... -> {fs_path} (duration={duration}s, size={fs_path.stat().st_size} bytes)")
                    return f"/dvideos/{fname}", duration
                else:
                    if attempt < max_retries - 1:
                        continue
                    logging.warning(f"❗ [discord] yt-dlp failed to download or video too short: {url[:50]}...")
                    # Clean up failed download
                    if fs_path.exists():
                        try:
                            fs_path.unlink()
                        except Exception:
                            pass
                    return None, None

            else:
                # Direct video file - download it
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=90),
                    connector=aiohttp.TCPConnector(limit=5)
                ) as session:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            logging.warning(
                                f"❗ [discord] Failed to download video {url[:50]}...: "
                                f"status={resp.status}, body={text[:200]!r}"
                            )
                            if resp.status in (404, 403, 410):  # Don't retry for these
                                break
                            continue
                        
                        # Read data in chunks to handle large files
                        data = b""
                        async for chunk in resp.content.iter_chunked(8192):
                            data += chunk
                            
                # Only write if we have data
                if len(data) > 0:
                    fs_path.write_bytes(data)
                    logging.info(f"💾 [warm_cache] Cached video {url[:50]}... -> {fs_path} ({len(data)} bytes)")
                    
                    # Try to get duration from downloaded file
                    duration = await get_video_duration_from_file(str(fs_path))
                    if duration is None:
                        # File is invalid (too short or corrupted), remove it
                        try:
                            fs_path.unlink()
                            logging.info(f"🗑️ [video] Removed invalid downloaded video: {fs_path}")
                        except Exception:
                            pass
                        if attempt < max_retries - 1:
                            continue
                        return None, None
                    return f"/dvideos/{fname}", duration
                else:
                    logging.warning(f"❗ [discord] Empty video data for {url[:50]}...")
                    continue

        except asyncio.TimeoutError:
            logging.warning(f"⏱️ [discord] Timeout downloading video {url[:50]}... (attempt {attempt + 1})")
            continue
        except Exception as e:
            logging.error(f"❗ [discord] Error caching video {url[:50]}... (attempt {attempt + 1}): {e}")
            if attempt == max_retries - 1:  # Last attempt
                logging.error(f"❗ [discord] Final failure caching video {url[:50]}...", exc_info=True)
            continue

    # Clean up partial download on final failure
    if fs_path.exists():
        try:
            fs_path.unlink()
            logging.debug(f"🧹 [discord] Cleaned up partial video file {fs_path}")
        except Exception:
            pass
    return None, None


async def get_video_duration_from_file(file_path: str) -> Optional[float]:
    """
    Get duration from a local video file using ffprobe or similar.
    Returns None if the file is corrupted or unreadable, but accepts short durations for GIFs.
    """
    try:
        # Try ffprobe first (more reliable for local files)
        import subprocess
        result = subprocess.run([
             'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', file_path
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            duration_str = result.stdout.strip()
            if duration_str:
                duration = float(duration_str)
                # Accept any positive duration - GIFs can be very short (0.1s+)
                if duration > 0:
                    logging.debug(f"[video] Valid video duration: {file_path} ({duration}s)")
                    return duration
                else:
                    logging.warning(f"[video] Zero duration video: {file_path}")
                    return None
    except Exception:
        pass

    # Fallback: try yt-dlp on local file
    try:
        import yt_dlp  # type: ignore
        
        async def _get_duration_yt_dlp(path: str) -> Optional[float]:
            def _inner() -> Optional[float]:
                ydl_opts = {
                    "quiet": True,
                    "skip_download": True,
                    "no_warnings": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f"file://{path}", download=False)
                    dur = info.get("duration")
                    if dur is None:
                        return None
                    try:
                        duration = float(dur)
                        # Accept any positive duration - GIFs can be very short
                        if duration > 0:
                            logging.debug(f"[video] Valid video duration (yt-dlp): {path} ({duration}s)")
                            return duration
                        else:
                            logging.warning(f"[video] Zero duration video (yt-dlp): {path}")
                            return None
                    except Exception:
                        return None
            return await asyncio.to_thread(_inner)
        
        return await _get_duration_yt_dlp(file_path)
    except Exception:
        pass

    # If we can't determine duration, assume it's corrupted
    logging.warning(f"❗ [video] Could not determine duration for {file_path} - may be corrupted")
    return None


async def get_audio_duration_from_file(file_path: str) -> Optional[float]:
    """
    Get duration from a local audio file using ffprobe.
    Returns None if the file is corrupted or unreadable.
    """
    try:
        # Use ffprobe to get audio duration
        result = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-show_entries", "format=duration", 
            "-of", "csv=p=0", file_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await result.communicate()
        
        if result.returncode == 0 and stdout:
            duration_str = stdout.decode().strip()
            if duration_str:
                duration = float(duration_str)
                if duration > 0:
                    logging.debug(f"[audio] Valid audio duration: {file_path} ({duration}s)")
                    return duration
                else:
                    logging.warning(f"[audio] Zero duration audio: {file_path}")
                    return None
    except Exception:
        pass
    
    logging.warning(f"❗ [audio] Could not determine duration for {file_path} - may be corrupted")
    return None


# -----------------------------
# DISCORD SOUND SELECTION (Discord-only SFX)
# -----------------------------
async def fetch_random_discord_sound(action_key: str, project: Optional[str]) -> Optional[str]:
    """
    Choose a random sound (audio URL) for the given action from the cached
    Discord messages, then download & cache it locally and return a /dsounds/ URL.

    Requirements for a message to qualify:
      - It must be associated with the target project/game (via GAME_EMOJI_MAP).
      - It must have a reaction that matches the *action emoji* for this action
        under the given project (using config.games[project].actions[action_key]).
      - It must contain at least one audio-ish attachment / embed / link.

    NOTE: Now uses the same project filtering as memes (requires both game emoji and action emoji).
    """
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        logging.debug("[discord] Missing bot token or channel id; skipping sound fetch.")
        return None

    # Determine action emoji for this project; if none, no sounds
    target_emoji = get_action_emoji(action_key, project)
    if not target_emoji:
        logging.debug(
            f"[discord] No emoji mapping for action={action_key} under project={project}; "
            f"skipping sound fetch."
        )
        return None

    normalized_target = normalize_emoji(target_emoji)

    # Lazy-load cache on first use if needed
    if not discord_messages_cache:
        logging.info("[discord] Message cache empty; doing one-time refresh before sound selection.")
        await refresh_discord_messages_cache()

    messages = _select_messages_for_project(project)
    if not messages:
        logging.info(
            f"[discord] No messages available for project={project}; "
            f"cannot select a sound for action={action_key}."
        )
        return None

    logging.info(
        f"[discord] Selecting sound from {len(messages)} cached messages for "
        f"project={project}, action={action_key}, emoji={target_emoji!r}"
    )

    # url -> cumulative weight
    weighted_candidates: Dict[str, float] = {}

    AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".webm")

    def _add_candidate(url: str, weight: float):
        if not url or weight <= 0:
            return
        url = url.strip()
        prev = weighted_candidates.get(url, 0.0)
        weighted_candidates[url] = prev + weight

    # We scan messages filtered by project/game (via GAME_EMOJI_MAP) and look for the action emoji.
    for msg in messages:
        msg_id = msg.get("id")
        reactions = msg.get("reactions") or []

        match_weight = 0

        for r in reactions:
            emoji_obj = r.get("emoji") or {}
            name = emoji_obj.get("name") or ""
            emoji_id = emoji_obj.get("id")  # None for unicode, string for custom
            count = r.get("count") or 0

            logging.debug(
                f"[discord] (sound) Reaction on {msg_id}: name={name!r}, id={emoji_id}, count={count}"
            )

            if count <= 0:
                continue

            matched = False

            if emoji_id is None:
                # Unicode emoji
                norm_name = normalize_emoji(name)
                if norm_name == normalized_target:
                    matched = True
            else:
                # Custom emoji: allow naming it exactly like the action
                if name.lower() == action_key.lower():
                    matched = True

            if matched:
                match_weight += count  # Sum all matching emoji reactions for voting weight

        if match_weight <= 0:
            continue  # no matching reaction for this action on this message

        logging.info(
            f"[discord] Cached message {msg_id} has matching reaction for sound action={action_key} "
            f"with weight={match_weight}"
        )

        # --- Attachments (primary source for audio) ---
        for att in msg.get("attachments", []):
            url = (att.get("url") or "").strip()
            fname = (att.get("filename") or "").lower()
            ctype = (att.get("content_type") or "").lower()

            logging.info(
                f"[discord] (sound) Attachment on {msg_id}: filename={fname}, "
                f"content_type={ctype}, url={url}"
            )

            if not url:
                continue

            if (
                ctype.startswith("audio/")
                or fname.endswith(AUDIO_EXTS)
                or any(ext in url.lower() for ext in AUDIO_EXTS)
            ):
                _add_candidate(url, match_weight)

        # --- Embeds (audio URLs sometimes appear here) ---
        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()
            if emb_url and any(ext in emb_url.lower() for ext in AUDIO_EXTS):
                logging.info(f"[discord] (sound) Embed url on {msg_id}: {emb_url}")
                _add_candidate(emb_url, match_weight)

            audio_obj = emb.get("audio") or {}
            audio_url = (audio_obj.get("url") or "").strip()
            if audio_url and any(ext in audio_url.lower() for ext in AUDIO_EXTS):
                logging.info(f"[discord] (sound) Embed audio on {msg_id}: {audio_url}")
                _add_candidate(audio_url, match_weight)

        # --- Fallback: plain-text links in content ---
        content = (msg.get("content") or "").strip()
        if "http" in content:
            parts = content.split()
            for p in parts:
                if not p.startswith("http"):
                    continue
                lower_p = p.lower()
                if any(ext in lower_p for ext in AUDIO_EXTS):
                    logging.info(f"[discord] (sound) Content audio candidate on {msg_id}: {p}")
                    _add_candidate(p, match_weight)
                    break

    if not weighted_candidates:
        logging.info(
            f"[discord] No audio candidates found in cache for action={action_key} "
            f"emoji={target_emoji!r} (project={project})."
        )
        return None

    # Weighted random choice from cached candidates, then cache locally
    items = list(weighted_candidates.items())
    total_weight = sum(w for _, w in items)
    r = random.uniform(0, total_weight)
    upto = 0.0

    for url, w in items:
        upto += w
        if r <= upto:
            logging.info(
                f"🔊 [discord] Selected cached sound URL candidate for action={action_key} "
                f"(project={project}): {url} (weight={w}, total={total_weight})"
            )
            local_url = await cache_discord_audio(url)
            if local_url:
                logging.info(
                    f"🔊 [discord] Using local cached sound URL: {local_url} "
                    f"for remote {url}"
                )
                return local_url
            else:
                logging.warning(
                    f"❗ [discord] Failed to cache audio for {url}; trying another candidate."
                )

    # Fallback (should almost never happen)
    chosen = random.choice(list(weighted_candidates.keys()))
    logging.info(
        f"🔊 [discord] Fallback selected sound candidate for action={action_key} "
        f"(project={project}): {chosen}"
    )
    local_url = await cache_discord_audio(chosen)
    if local_url:
        logging.info(
            f"🔊 [discord] Using fallback local cached sound URL: {local_url} "
            f"for remote {chosen}"
        )
        return local_url

    logging.error(
        f"❗ [discord] Failed to cache any audio for action={action_key} "
        f"(project={project}); returning None."
    )
    return None


# -----------------------------
# MEDIA COMBO PICKER
# -----------------------------
async def pick_media_for_action(
    action_key: str,
    project_key: str,
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[float]]:
    """
    Decide which media to use for a given action based on EMOJI VOTE WEIGHTS ONLY.
    
    Core principle: Only media with valid emoji votes can be selected.
    Selection is weighted by reaction counts (democratic voting system).
    
    Returns: (sound_url, meme_url, video_url, video_duration_seconds)
    """
    game_conf = GAMES_CONFIG.get(project_key, {})
    actions_map = (game_conf.get("actions") or {})
    
    if action_key not in actions_map or action_key == "clear":
        logging.info(f"[media] No action mapping for {action_key} in project {project_key}")
        return None, None, None, None
    
    # Get all media options with their emoji weights
    weighted_media_options = []  # List of (media_type, url, weight, duration, original_url)
    
    try:
        # Get cached media with weights
        sound_result = await get_cached_discord_sound_with_weight(action_key, project=project_key)
        meme_result = await get_cached_discord_meme_with_weight(action_key, project=project_key)  
        video_result = await get_cached_discord_video_with_weight(action_key, project=project_key)
        
        # Add sound options (these can pair with memes)
        if sound_result and sound_result[0]:  # (url, weight)
            sound_url, sound_weight = sound_result
            weighted_media_options.append(("sound", sound_url, sound_weight, None, None))
        
        # Add meme options (these can pair with sounds)
        if meme_result and meme_result[0]:  # (url, weight) 
            meme_url, meme_weight = meme_result
            weighted_media_options.append(("meme", meme_url, meme_weight, None, None))
            
        # Add video options (these play standalone)
        if video_result and video_result[0]:  # (url, weight, duration, original_url)
            video_url, video_weight, video_duration, original_video_url = video_result
            weighted_media_options.append(("video", video_url, video_weight, video_duration, original_video_url))
        
    except Exception as e:
        logging.error(f"[media] Error getting weighted media for {action_key}: {e}")
        return None, None, None, None
    
    if not weighted_media_options:
        logging.info(f"[media] No media with valid emoji votes found for action={action_key}")
        return None, None, None, None
    
    # Log available options
    for media_type, url, weight, duration, orig_url in weighted_media_options:
        if media_type == "video":
            logging.info(f"[media] {media_type}: {url} (weight={weight}, duration={duration}s, original={orig_url[:50] if orig_url else 'N/A'}...)")
        else:
            logging.info(f"[media] {media_type}: {url} (weight={weight})")
    
    # Determine media combinations based on available weighted options
    available_combinations = []
    
    # Check for video options (highest impact media)
    video_options = [opt for opt in weighted_media_options if opt[0] == "video"]
    if video_options:
        for video_type, video_url, video_weight, video_duration, original_video_url in video_options:
            # Determine video type for proper handling
            if original_video_url and YOUTUBE_RE.search(original_video_url):
                combo_type = "youtube_video"
            else:
                combo_type = "tenor_video" 
            
            available_combinations.append((
                combo_type, 
                video_weight,
                None,  # sound_url 
                None,  # meme_url
                video_url,  # video_url
                video_duration  # video_duration
            ))
    
    # Check for meme + sound combinations
    sound_options = [opt for opt in weighted_media_options if opt[0] == "sound"]
    meme_options = [opt for opt in weighted_media_options if opt[0] == "meme"]
    
    if sound_options and meme_options:
        # Create combinations of highest weighted sound + meme
        for _, sound_url, sound_weight, _, _ in sound_options:
            for _, meme_url, meme_weight, _, _ in meme_options:
                # Combined weight is average to not double-count
                combo_weight = (sound_weight + meme_weight) / 2
                available_combinations.append((
                    "gif_audio",
                    combo_weight, 
                    sound_url,
                    meme_url,
                    None,  # video_url
                    None   # video_duration
                ))
    
    # Check for standalone options
    if sound_options and not meme_options:
        for _, sound_url, sound_weight, _, _ in sound_options:
            available_combinations.append((
                "audio_only",
                sound_weight,
                sound_url,
                None,  # meme_url
                None,  # video_url  
                None   # video_duration
            ))
    
    if meme_options and not sound_options:
        for _, meme_url, meme_weight, _, _ in meme_options:
            available_combinations.append((
                "gif_only", 
                meme_weight,
                None,  # sound_url
                meme_url,
                None,  # video_url
                None   # video_duration
            ))
    
    if not available_combinations:
        logging.info(f"[media] No valid media combinations for action={action_key}")
        return None, None, None, None
    
    # Weighted selection based on emoji votes
    total_weight = sum(weight for _, weight, _, _, _, _ in available_combinations)
    if total_weight <= 0:
        logging.warning(f"[media] All media has zero weight for action={action_key}")
        return None, None, None, None
    
    # Log combinations
    for combo_type, weight, sound, meme, video, duration in available_combinations:
        logging.info(f"[media] Combination: {combo_type} (weight={weight:.1f})")
    
    # Weighted random selection
    import random
    r = random.uniform(0, total_weight)
    upto = 0.0
    for combo_type, weight, sound_url, meme_url, video_url, video_duration in available_combinations:
        upto += weight
        if r <= upto:
            logging.info(f"[media] SELECTED: {combo_type} (weight={weight:.1f}/{total_weight:.1f})")
            return sound_url, meme_url, video_url, video_duration
    
    # Fallback (shouldn't happen)
    combo_type, weight, sound_url, meme_url, video_url, video_duration = available_combinations[0]
    logging.info(f"[media] FALLBACK: {combo_type} (weight={weight:.1f})")
    return sound_url, meme_url, video_url, video_duration


# -----------------------------
# FILES & TIMESTAMPS
# -----------------------------
def ensure_paths() -> None:
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    CHAPTER_DIR.mkdir(parents=True, exist_ok=True)
    DISCORD_SOUND_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DISCORD_VIDEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    logging.info(f"📁 WATCH_DIR      = {WATCH_DIR.resolve()}")
    logging.info(f"📁 CHAPTER_DIR    = {CHAPTER_DIR.resolve()}")
    logging.info(f"📝 TEMPLATE_FILE  = {TEMPLATE_FILE.resolve()}")
    logging.info(f"🎮 DEFAULT_PROJECT_NAME = {DEFAULT_PROJECT_NAME}")
    logging.info(f"🎧 DISCORD_SOUND_CACHE_DIR = {DISCORD_SOUND_CACHE_DIR.resolve()}")
    logging.info(f"📹 DISCORD_VIDEO_CACHE_DIR = {DISCORD_VIDEO_CACHE_DIR.resolve()}")


def format_chapter_time(seconds: float) -> str:
    """
    Format a float number of seconds into HH:MM:SS.mmm
    """
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


async def start_new_chapter_session(project: Optional[str]) -> None:
    """
    Start a new chapter file when a recording/stream starts.
    Uses the provided project/game name (from OBS scene) when possible.
    """
    global current_chapter_file, session_start_wall, CURRENT_SESSION_PROJECT

    CHAPTER_DIR.mkdir(parents=True, exist_ok=True)

    # Determine effective project name for this session
    game_key = resolve_game_key(project)
    effective_project = game_key or project or DEFAULT_PROJECT_NAME or "unknown"

    CURRENT_SESSION_PROJECT = effective_project

    ts_stamp = time.strftime("%Y%m%d-%H%M%S")
    fname = f"{effective_project}-{ts_stamp}-chapters.txt"
    path = CHAPTER_DIR / fname

    session_start_wall = time.time()
    current_chapter_file = path

    try:
        with path.open("w", encoding="utf-8", newline="") as f:
            f.write(f"# Project: {effective_project}\n")
            f.write(f"# Created: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("# Format: HH:MM:SS.mmm <label>\n\n")
        logging.info(f"📄 [chapter] Started new chapter file: {path}")
    except Exception as e:
        logging.error(f"❗ [chapter] Failed to create chapter file {path}: {e}", exc_info=True)


async def append_chapter_line(action: str, project: Optional[str]) -> None:
    """
    Append a line to the current chapter log file when an action arrives.
    Uses CURRENT_SESSION_PROJECT if available; otherwise, project/action is enough.
    """
    global current_chapter_file, session_start_wall, CURRENT_SESSION_PROJECT

    if current_chapter_file is None:
        logging.info("⚠️ [chapter] No active chapter file; starting a session implicitly.")
        await start_new_chapter_session(project)

    if session_start_wall is None:
        session_start_wall = time.time()

    # If project is provided and differs, keep CURRENT_SESSION_PROJECT as the first project seen
    if project and not CURRENT_SESSION_PROJECT:
        CURRENT_SESSION_PROJECT = resolve_game_key(project) or project

    elapsed = max(0.0, time.time() - session_start_wall)
    tc = format_chapter_time(elapsed)
    line = f"{tc} {action}\n"

    logging.info(f"📝 [chapter] Writing line: {line.strip()} -> {current_chapter_file}")
    try:
        with current_chapter_file.open("a", encoding="utf-8", newline="") as f:
            f.write(line)
    except Exception as e:
        logging.error(
            f"❗ [chapter] Failed to write to {current_chapter_file}: {e}",
            exc_info=True,
        )


# -----------------------------
# RUN HELPERS
# -----------------------------
async def start_run_for_project(project_key: str) -> int:
    """
    Start a new run for the given project.
    Returns the run number.
    """
    global run_counters, current_run_by_project, run_stats_by_project

    run_num = run_counters.get(project_key, 0) + 1
    run_counters[project_key] = run_num
    current_run_by_project[project_key] = run_num

    run_stats_by_project[(project_key, run_num)] = {
        "kills": 0,
        "deaths": 0,
        "headshots": 0,
        "events": 0,
        "started_at": time.time(),
    }

    logging.info(f"🏁 [run] Started run #{run_num} for project={project_key}")
    return run_num


def register_run_event(project_key: str, action_key: str) -> None:
    """
    Update run stats for a normal gameplay action (kill, death, etc.)
    if a run is currently active.
    """
    run_num = current_run_by_project.get(project_key)
    if not run_num:
        return  # no active run

    key = (project_key, run_num)
    stats = run_stats_by_project.get(key)
    if not stats:
        # should not happen, but be safe
        stats = {
            "kills": 0,
            "deaths": 0,
            "headshots": 0,
            "events": 0,
            "started_at": time.time(),
        }
        run_stats_by_project[key] = stats

    stats["events"] = stats.get("events", 0) + 1

    ak = action_key.lower()
    if ak in RUN_KILL_ACTIONS:
        stats["kills"] = stats.get("kills", 0) + 1
    if ak in RUN_DEATH_ACTIONS:
        stats["deaths"] = stats.get("deaths", 0) + 1
    if ak == "headshot":
        stats["headshots"] = stats.get("headshots", 0) + 1


async def end_run_for_project(project_key: str) -> None:
    """
    End the current run for a project, push its summary into history,
    and mark the recap panel as visible for a while.
    """
    global run_panel_visible_until

    run_num = current_run_by_project.get(project_key)
    if not run_num:
        logging.info(f"⚠️ [run] end_run_for_project called but no active run for {project_key}")
        return

    key = (project_key, run_num)
    stats = run_stats_by_project.pop(key, None) or {
        "kills": 0,
        "deaths": 0,
        "headshots": 0,
        "events": 0,
        "started_at": time.time(),
    }

    started_at = stats.get("started_at", time.time())
    ended_at = time.time()
    duration = max(0.0, ended_at - started_at)

    kills = int(stats.get("kills", 0))
    deaths = int(stats.get("deaths", 0))
    headshots = int(stats.get("headshots", 0))

    if deaths > 0:
        kd = kills / deaths
    else:
        kd = float(kills) if kills > 0 else 0.0

    summary = {
        "run": run_num,
        "project": project_key,
        "kills": kills,
        "deaths": deaths,
        "headshots": headshots,
        "kd": kd,
        "duration": duration,
    }

    # 🔵 No backend cap: keep full history; frontend decides what to show.
    hist = run_history_by_project.setdefault(project_key, [])
    hist.append(summary)

    current_run_by_project[project_key] = None

    # Keep the panel visible for a few minutes after this run ends
    run_panel_visible_until = time.time() + RUN_PANEL_DURATION_SECONDS

    logging.info(
        f"🏁 [run] Ended run #{run_num} for project={project_key} "
        f"(kills={kills}, deaths={deaths}, headshots={headshots}, kd={kd:.2f}, "
        f"duration={duration:.1f}s)"
    )

    # Optional: also write a nice line to chapters
    try:
        await append_chapter_line(
            f"Run {run_num} end (K={kills}, D={deaths}, HS={headshots})", project_key
        )
    except Exception:
        # don't explode here if chapter write fails
        logging.exception("[run] Failed to append run summary to chapter file")


async def stop_all_runs() -> None:
    """
    End all active runs across all projects and post a generic summary overlay.
    Each run still gets its normal per-project summary/history.
    """
    active_projects = [proj for proj, num in current_run_by_project.items() if num]
    if not active_projects:
        logging.info("[run] stop_all_runs called but no active runs.")
        return

    logging.info(f"[run] stop_all_runs ending runs for projects={active_projects}")
    last_proj: Optional[str] = None

    for proj in active_projects:
        try:
            await end_run_for_project(proj)
            last_proj = proj
        except Exception:
            logging.exception(f"[run] Failed to end run for project={proj}")

    # Show a generic overlay message after stopping everything
    if last_proj:
        try:
            await update_live_overlay("Runs stopped", last_proj)
        except Exception:
            logging.exception("[run] Failed to update overlay after stop_all_runs")


# -----------------------------
# OVERLAY STATE
# -----------------------------
async def update_live_overlay(action: str, project_key: str) -> None:
    """
    Update the live overlay state (per project) exposed at /overlay.
    """
    global overlay_clear_task, last_overlay_output, last_action, last_sound, last_meme_url, last_video_url, last_video_duration, last_project, run_panel_visible_until

    async with state_lock:
        if action.lower() == "clear":
            logging.info("🧹 [overlay] CLEAR action received; resetting counts and run stats.")

            # Reset per-action overlay counts
            action_counts.clear()

            # Reset all run-related state
            run_counters.clear()
            current_run_by_project.clear()
            run_stats_by_project.clear()
            run_history_by_project.clear()
            run_panel_visible_until = None

            # Clear overlay content & media
            last_overlay_output = ""
            last_action = ""
            last_sound = None
            last_meme_url = None
            last_video_url = None
            last_video_duration = None
            last_audio_duration = None
            last_project = ""

            # Cancel any pending auto-clear timer
            if overlay_clear_task and not overlay_clear_task.done():
                overlay_clear_task.cancel()
                overlay_clear_task = None

            return

        key = action.lower()

        # per-project counts: (project, action)
        count_key = (project_key, key)
        count = action_counts.get(count_key, 0) + 1
        action_counts[count_key] = count

        # look up emoji for this game
        game_conf = GAMES_CONFIG.get(project_key, {})
        actions_map = (game_conf.get("actions") or {})
        emoji = actions_map.get(key, "")

        label = action
        output = f"{emoji} {label}".strip()
        if count > 1:
            output += f" x{count}"

        last_overlay_output = output
        last_action = key
        last_project = project_key

        # --- MEDIA PICKER: choose between (GIF+audio) and (video) ---
        sound_url, meme_url, video_url, video_duration = await pick_media_for_action(key, project_key)

        last_sound = sound_url or ""
        last_meme_url = meme_url or None
        last_video_url = video_url or None
        last_video_duration = video_duration
        
        # CRITICAL: Calculate audio duration BEFORE setting globals to avoid race conditions
        calculated_audio_duration = None
        if last_sound and last_sound.startswith("/dsounds/"):
            # Extract filename from /dsounds/filename.ext
            audio_filename = last_sound.split("/dsounds/")[-1]
            audio_file_path = DISCORD_SOUND_CACHE_DIR / audio_filename
            if audio_file_path.exists():
                try:
                    calculated_audio_duration = await get_audio_duration_from_file(str(audio_file_path))
                    if calculated_audio_duration:
                        logging.info(f"🎵 [overlay] Audio duration detected: {calculated_audio_duration}s for {audio_filename}")
                except Exception as e:
                    logging.warning(f"Failed to get audio duration for {audio_filename}: {e}")
        
        # Set the global AFTER calculation completes  
        last_audio_duration = calculated_audio_duration

        codepoints = " ".join(f"U+{ord(ch):04X}" for ch in output)
        logging.info(
            f"🖨️ [overlay] New overlay text: {output} [{codepoints}] "
            f"project={project_key} action={last_action} sound={last_sound} "
            f"meme={last_meme_url} video={last_video_url} duration={last_video_duration} audio_duration={last_audio_duration}"
        )

        # reset / restart auto-clear timer
        if overlay_clear_task and not overlay_clear_task.done():
            overlay_clear_task.cancel()

        overlay_clear_task = asyncio.create_task(_auto_clear_overlay())


async def _auto_clear_overlay() -> None:
    """
    Clears overlay after a delay - ALWAYS respects media duration.
    - For Tenor + Discord audio: use audio duration
    - For YouTube videos: use video duration  
    - For GIF + audio: use audio duration
    - NO fallback timing - only clear when media duration is known
    """
    global overlay_clear_task, last_overlay_output, last_action, last_sound, last_meme_url, last_video_url, last_video_duration, last_audio_duration, last_project

    try:
        clear_delay = None
        
        # Determine appropriate duration based on media combination
        if last_video_url and last_audio_duration:
            # Tenor video + Discord audio: use audio duration (audio controls the timing)
            clear_delay = last_audio_duration + 1.0
            logging.info(f"⏱️ [overlay] Tenor+Audio mode: Auto-clear scheduled after audio duration: {clear_delay}s")
        elif last_video_url and last_video_duration:
            # YouTube video: use video duration (video controls the timing)
            clear_delay = last_video_duration + 1.0  
            logging.info(f"⏱️ [overlay] YouTube mode: Auto-clear scheduled after video duration: {clear_delay}s")
        elif last_audio_duration and (last_sound or last_meme_url):
            # GIF + Discord audio: use audio duration
            clear_delay = last_audio_duration + 1.0
            logging.info(f"⏱️ [overlay] GIF+Audio mode: Auto-clear scheduled after audio duration: {clear_delay}s")
        else:
            # No timed media - don't auto-clear, let frontend handle it
            logging.info(f"⏱️ [overlay] No timed media detected - no auto-clear scheduled")
            return
            
        await asyncio.sleep(clear_delay)

        async with state_lock:
            last_overlay_output = ""
            last_action = ""
            last_sound = None
            last_meme_url = None
            last_video_url = None
            last_video_duration = None
            last_audio_duration = None
            last_project = ""
        logging.info(f"🧽 [overlay] Auto-cleared after {clear_delay}s")

    except asyncio.CancelledError:
        logging.debug("⏳ [overlay] Auto-clear cancelled (new action received)")
        return


# -----------------------------
# ACTION HANDLING / TCP PARSE
# -----------------------------
async def handle_action(action: str, project: Optional[str]) -> None:
    """
    Handle a single parsed 'action' from TCP, with an optional game/project.
    """
    action = action.strip()
    if not action:
        logging.info("⚠️ [handler] Ignoring empty action.")
        return

    # Resolve which project/game this should use
    project_key = resolve_game_key(project) if project else DEFAULT_PROJECT_NAME
    if not project_key:
        logging.info(
            f"⚠️ [handler] Unknown project {project!r}; using DEFAULT_PROJECT_NAME={DEFAULT_PROJECT_NAME}"
        )
        project_key = DEFAULT_PROJECT_NAME

    logging.info(f"🎯 [handler] Received action={action} for project={project_key}")
    lower = action.lower()

    # ---- Run control actions ----
    if lower == "run_start":
        # If a run is already active for this project, end it first (split)
        if current_run_by_project.get(project_key):
            logging.info(f"[run] run_start received while run active; splitting run for {project_key}")
            await end_run_for_project(project_key)

        # Start next run
        run_num = await start_run_for_project(project_key)
        try:
            await append_chapter_line(f"Run {run_num} start", project_key)
        except Exception:
            logging.exception("[run] Failed to append run-start to chapter file")

        # Show a run start event in the overlay
        await update_live_overlay(f"Run {run_num} start", project_key)
        return

    if lower == "run_end":
        # End the current run for this project ONCE and show a summary
        run_num = current_run_by_project.get(project_key)

        if not run_num:
            # No active run → do nothing (prevents double-trigger)
            logging.info(f"[run] run_end received for {project_key} but no active run; ignoring.")
            return

        # End the active run (this pushes it into history)
        await end_run_for_project(project_key)

        # Build a summary across *all* runs for this project
        hist = run_history_by_project.get(project_key, [])
        if hist:
            total_kills = sum(r.get("kills", 0) for r in hist)
            total_deaths = sum(r.get("deaths", 0) for r in hist)
            total_headshots = sum(r.get("headshots", 0) for r in hist)
            runs_count = len(hist)

            if total_deaths > 0:
                overall_kd = total_kills / total_deaths
            else:
                overall_kd = float(total_kills) if total_kills > 0 else 0.0

            overlay_text = (
                f"Runs {runs_count} | "
                f"💀{total_kills}  ☠️{total_deaths}  🎯{total_headshots}  "
                f"KD {overall_kd:.2f}"
            )
        else:
            overlay_text = "No runs recorded"

        await update_live_overlay(overlay_text, project_key)
        return

    if lower == "run_stop":
        # New: end ALL active runs across all projects and post a summary message
        await stop_all_runs()
        return

    # ---- Recording start -> new chapter session ----
    if lower == "start":
        await start_new_chapter_session(project_key)

    # ---- Normal actions (kills, deaths, etc.) ----
    if lower != "clear":
        await append_chapter_line(action, project_key)
        # Update run stats if a run is in progress
        register_run_event(project_key, lower)

    await update_live_overlay(action, project_key)


def extract_from_payload(text: str) -> tuple[Optional[str], list[str]]:
    """
    Extract project/game + one or more actions from the raw payload.

    Supports lines like:
      game=hunt_showdown
      action=kill
      action=death

    And also bare actions like 'kill' if they exist in ANY game's actions.
    """
    project: Optional[str] = None
    actions: list[str] = []

    # Precompute lowercase set for faster membership tests
    all_actions_lower = {a.lower() for a in ALL_ACTION_KEYS}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        logging.info(f"🔍 [parser] Checking line: {repr(line)}")
        lower = line.lower()

        if lower.startswith("game=") or lower.startswith("project="):
            val = line.split("=", 1)[1].strip()
            if val:
                project = val
                logging.info(f"✅ [parser] Parsed project/game: {project}")
            continue

        if lower.startswith("action="):
            val = line.split("=", 1)[1].strip()
            if val:
                logging.info(f"✅ [parser] Parsed action from 'action=' line: {val}")
                actions.append(val)
            continue

        # bare token like 'kill'
        token = line
        if token.lower() in all_actions_lower:
            logging.info(f"✅ [parser] Parsed bare action: {token}")
            actions.append(token)
        else:
            logging.info(f"⚠️ [parser] Line did not match project/action format: {repr(line)}")

    return project, actions


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    addr = writer.get_extra_info("peername")
    logging.info(f"🔌 [tcp] Connection from {addr}")

    try:
        data = await reader.read(1024)
        if not data:
            logging.info(f"⚠️ [tcp] Empty payload from {addr}, closing.")
            writer.close()
            await writer.wait_closed()
            return

        text = data.decode("utf-8", errors="ignore")
        logging.info(f"📥 [tcp] Raw payload bytes: {data!r}")
        logging.info(f"📥 [tcp] Raw payload text: {repr(text)}")

        project, actions = extract_from_payload(text)
        if not actions:
            logging.info("⚠️ [tcp] No actions parsed from payload.")
        else:
            for a in actions:
                await handle_action(a, project)

    except Exception as e:
        logging.error(f"❗ [tcp] Error handling client {addr}: {e}", exc_info=True)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logging.info(f"🔌 [tcp] Connection from {addr} closed.")


# -----------------------------
# HTTP SERVER
# -----------------------------
async def handle_http(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """
    Simple HTTP server:
      - GET /             => serves the HTML template
      - GET /overlay      => JSON with latest overlay text + action + sound + meme + project + runs
      - GET /config       => serves raw YAML config
      - GET /dsounds/<...> => serves cached Discord audio files
      - GET /dvideos/<...> => serves cached Discord video files
    """
    addr = writer.get_extra_info("peername")
    logging.debug(f"🌐 [http] Request from {addr}")
    try:
        request = await reader.read(1024)
        if not request:
            writer.close()
            await writer.wait_closed()
            return

        try:
            req_text = request.decode("utf-8", errors="ignore")
            first_line = req_text.splitlines()[0]
            parts = first_line.split()
            method = parts[0] if len(parts) > 0 else "GET"
            raw_path = parts[1] if len(parts) > 1 else "/"
        except Exception:
            method = "GET"
            raw_path = "/"

        path = raw_path.split("?", 1)[0]  # strip query params
        logging.debug(f"🌐 [http] {method} {path}")

        if path.startswith("/overlay"):
            async with state_lock:
                text = last_overlay_output or ""
                action = last_action or ""
                sound = last_sound or ""
                meme = last_meme_url or ""
                video = last_video_url or ""
                video_duration = last_video_duration if last_video_duration is not None else 0.0
                audio_duration = last_audio_duration if last_audio_duration is not None else 0.0
                project = last_project or ""
                
                # DEBUG: Log audio duration value when API is called
                #logging.info(f"🔍 [overlay] API call - last_audio_duration={last_audio_duration}, final_audio_duration={audio_duration}")

                # ---- Build run summaries for the panel ----
                runs_for_overlay: List[Dict[str, Any]] = []
                now = time.time()

                # Decide which project the panel is for
                proj_key = project or DEFAULT_PROJECT_NAME

                if proj_key:
                    active_run_num = current_run_by_project.get(proj_key)
                    full_hist = run_history_by_project.get(proj_key, [])

                    # Panel is visible while a run is active OR
                    # for some time after the last run ended.
                    visible = bool(active_run_num) or (
                        run_panel_visible_until is not None
                        and now < run_panel_visible_until
                    )

                    if visible and full_hist:
                        # Only send the last MAX_VISIBLE_RUNS runs to the frontend
                        if MAX_VISIBLE_RUNS > 0:
                            hist = full_hist[-MAX_VISIBLE_RUNS:]
                        else:
                            hist = full_hist

                        n = len(hist)

                        # Old runs (history)
                        for idx, summary in enumerate(hist):
                            if n > 1:
                                # 0.25 (oldest) → 1.0 (newest), based on *visible* slice
                                opacity = 0.25 + 0.75 * (idx / (n - 1))
                            else:
                                opacity = 1.0

                            runs_for_overlay.append(
                                {
                                    "run": summary.get("run"),
                                    "kills": summary.get("kills", 0),
                                    "deaths": summary.get("deaths", 0),
                                    "headshots": summary.get("headshots", 0),
                                    "kd": summary.get("kd", 0.0),
                                    "opacity": round(float(opacity), 2),
                                    "active": False,
                                }
                            )

                        # Current run (active, glowing)
                        if active_run_num:
                            key = (proj_key, active_run_num)
                            stats = run_stats_by_project.get(key, {}) or {}
                            kills = int(stats.get("kills", 0))
                            deaths = int(stats.get("deaths", 0))
                            headshots = int(stats.get("headshots", 0))

                            if deaths > 0:
                                kd = kills / deaths
                            else:
                                kd = float(kills) if kills > 0 else 0.0

                            runs_for_overlay.append(
                                {
                                    "run": active_run_num,
                                    "kills": kills,
                                    "deaths": deaths,
                                    "headshots": headshots,
                                    "kd": kd,
                                    "opacity": 1.0,
                                    "active": True,  # <-- drives the glow CSS
                                }
                            )

            body_obj = {
                "text": text,
                "action": action,
                "sound": sound,
                "meme": meme,
                "video": video,
                "video_duration": video_duration,
                "audio_duration": audio_duration,
                "project": project,
                "runs": runs_for_overlay,
            }
            body_bytes = json.dumps(body_obj).encode("utf-8")
            headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json; charset=utf-8\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            writer.write(headers.encode("ascii") + body_bytes)
            await writer.drain()

        elif path == "/config":
            # Serve the raw YAML config
            try:
                body_str = CONFIG_PATH.read_text(encoding="utf-8")
            except Exception as e:
                logging.error(f"❗ [http] Failed to read CONFIG YAML: {e}", exc_info=True)
                body_str = "error: cannot read config"

            body_bytes = body_str.encode("utf-8")
            headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/yaml; charset=utf-8\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            writer.write(headers.encode("ascii") + body_bytes)
            await writer.drain()

        elif path.startswith("/debug_video"):
            # DEBUG ENDPOINT: Force select a cached video for testing
            try:
                import os
                from pathlib import Path
                video_dir = Path("/discord/discord_videos")
                video_files = list(video_dir.glob("*.mp4"))
                
                if video_files:
                    # Select first video file
                    video_file = video_files[0]
                    video_filename = video_file.name
                    
                    # Get duration
                    duration = None
                    try:
                        result = subprocess.run([
                            'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                            '-of', 'default=noprint_wrappers=1:nokey=1', str(video_file)
                        ], capture_output=True, text=True, timeout=10)
                        
                        if result.returncode == 0:
                            duration_str = result.stdout.strip()
                            if duration_str:
                                duration = float(duration_str)
                    except Exception:
                        duration = 10.0  # fallback
                    
                    # Create debug response
                    debug_response = {
                        "text": "🎬 DEBUG VIDEO",
                        "action": "debug",
                        "sound": "",
                        "meme": "",
                        "video": f"/dvideos/{video_filename}",
                        "video_duration": duration or 10.0,
                        "audio_duration": 0.0,
                        "project": "debug",
                        "runs": []
                    }
                    
                    body_bytes = json.dumps(debug_response).encode("utf-8")
                else:
                    body_bytes = json.dumps({"error": "No cached videos found"}).encode("utf-8")
                    
            except Exception as e:
                body_bytes = json.dumps({"error": str(e)}).encode("utf-8")
            
            headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json; charset=utf-8\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            writer.write(headers.encode("ascii") + body_bytes)
            await writer.drain()

        elif path.startswith("/dsounds/"):
            # Static served cached Discord audio
            rel = path[len("/dsounds/"):].lstrip("/")
            fs_path = (DISCORD_SOUND_CACHE_DIR / rel).resolve()

            # Security: ensure it's inside DISCORD_SOUND_CACHE_DIR
            try:
                fs_path.relative_to(DISCORD_SOUND_CACHE_DIR.resolve())
            except ValueError:
                logging.warning(f"🚫 [http] Attempted path escape for dsounds: {fs_path}")
                resp = b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

            if not fs_path.exists() or not fs_path.is_file():
                logging.warning(f"❓ [http] Cached sound not found: {fs_path}")
                resp = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

            try:
                body_bytes = fs_path.read_bytes()
                mime, _ = mimetypes.guess_type(fs_path.name)
                mime = mime or "audio/ogg"
            except Exception as e:
                logging.error(f"❗ [http] Failed to read cached sound file {fs_path}: {e}", exc_info=True)
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

            headers = (
                "HTTP/1.1 200 OK\r\n"
                f"Content-Type: {mime}\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            writer.write(headers.encode("ascii") + body_bytes)
            await writer.drain()

        elif path.startswith("/dvideos/"):
            # Static served cached Discord videos
            rel = path[len("/dvideos/"):].lstrip("/")
            fs_path = (DISCORD_VIDEO_CACHE_DIR / rel).resolve()

            # Security: ensure it's inside DISCORD_VIDEO_CACHE_DIR
            try:
                fs_path.relative_to(DISCORD_VIDEO_CACHE_DIR.resolve())
            except ValueError:
                logging.warning(f"🚫 [http] Attempted path escape for dvideos: {fs_path}")
                resp = b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

            if not fs_path.exists() or not fs_path.is_file():
                logging.warning(f"❓ [http] Cached video not found: {fs_path}")
                resp = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

            try:
                body_bytes = fs_path.read_bytes()
                mime, _ = mimetypes.guess_type(fs_path.name)
                mime = mime or "video/mp4"
            except Exception as e:
                logging.error(f"❗ [http] Failed to read cached video file {fs_path}: {e}", exc_info=True)
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

            headers = (
                "HTTP/1.1 200 OK\r\n"
                f"Content-Type: {mime}\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            writer.write(headers.encode("ascii") + body_bytes)
            await writer.drain()

        else:
            # Serve HTML
            try:
                if TEMPLATE_FILE.exists():
                    body_str = TEMPLATE_FILE.read_text(encoding="utf-8")
                else:
                    logging.warning("⚠️ TEMPLATE_FILE missing; using bare fallback HTML.")
                    body_str = "<html><body>Socket Sentinel Overlay</body></html>"
            except Exception as e:
                logging.error(f"❗ [http] Failed to read TEMPLATE_FILE: {e}", exc_info=True)
                body_str = "<html><body>Socket Sentinel Overlay Error</body></html>"

            body_bytes = body_str.encode("utf-8")
            headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            writer.write(headers.encode("ascii") + body_bytes)
            await writer.drain()

    except Exception as e:
        logging.error(f"❗ [http] Error serving HTTP request: {e}", exc_info=True)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logging.debug(f"🌐 [http] Connection from {addr} closed.")


# -----------------------------
# MAIN ENTRY
# -----------------------------
async def main() -> None:
    # Load YAML config (required) before anything else
    load_overlay_config()

    ensure_paths()
    logging.info("🚀 obs-socket-sentinel starting up...")

    # ---- Discord cache bootstrap ----
    if DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID:
        logging.info("[discord] Bot token + channel id present; building initial meme/sound cache...")
        await refresh_discord_messages_cache()
        # Warm cache ALL media files on startup for instant playback
        logging.info("[warm_cache] Starting initial warm cache of all media...")
        await warm_cache_all_media()
        # Start periodic background refresh (every 10 minutes) which includes warm caching
        asyncio.create_task(discord_cache_refresher_task(interval_seconds=600))
        # Start cache cleanup task
        asyncio.create_task(cache_cleanup_task())
    else:
        logging.info("[discord] Bot token or channel id missing; meme/sound cache disabled.")

    logging.info(f"📡 TCP listening on {HOST}:{PORT}")
    tcp_server = await asyncio.start_server(handle_client, HOST, PORT)

    logging.info(f"🌐 HTTP overlay at http://{HTTP_HOST}:{HTTP_PORT}/")
    http_server = await asyncio.start_server(handle_http, HTTP_HOST, HTTP_PORT)

    tcp_addrs = ", ".join(str(sock.getsockname()) for sock in tcp_server.sockets)
    http_addrs = ", ".join(str(sock.getsockname()) for sock in http_server.sockets)
    logging.info(f"✅ TCP server listening on: {tcp_addrs}")
    logging.info(f"✅ HTTP server listening on: {http_addrs}")

    async with tcp_server, http_server:
        await asyncio.gather(
            tcp_server.serve_forever(),
            http_server.serve_forever(),
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("👋 Shutting down obs-socket-sentinel.")

