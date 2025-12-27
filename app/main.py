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
import datetime
from typing import Dict, List, Any, Optional, Set

import aiohttp  # make sure this is installed in the container
import yaml  # pip install pyyaml
import hashlib  # for stable cache filenames
import re  # for YouTube detection

# -----------------------------
# CONFIG / GLOBALS
# -----------------------------
# Task reference so we can cancel/replace timers
overlay_clear_task: Optional[asyncio.Task] = None

# Global references for overlay media
last_sound: Optional[str] = None  # URL string for sound (Discord cached)
last_meme_url: Optional[str] = None  # URL string for meme image/gif (Discord)
last_video_url: Optional[str] = None  # URL string for video (YouTube/direct)
last_video_duration: Optional[float] = None  # Seconds, if known
last_audio_duration: Optional[float] = None  # Audio duration for proper timing
last_synonyms: Optional[List[str]] = None  # Synonyms for burst words

# Recently played media tracking to avoid repetition
recent_media_history: Dict[str, List[str]] = {}  # action_key -> list of recent URLs
RECENT_MEDIA_HISTORY_SIZE = 10  # Remember last 10 items per action

# Video cycle tracking for smart rotation
# Structure: action_key -> {
#   "pool": [(url, weight, duration, original_url), ...],  # All videos with repetition for weighted ones
#   "remaining": [(url, weight, duration, original_url), ...],  # Slots remaining in current cycle
#   "cycle_number": int  # Which cycle we're on
# }
video_cycle_state: Dict[str, Dict] = {}

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

# Security token for API access
SS_TOKEN = os.getenv("SS_TOKEN", "").strip()

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

# Alternative cache directories for fallback (in case of path issues)
ALTERNATIVE_VIDEO_CACHE_DIRS = [
    Path("./_data/discord/discord_videos"),  # Local development path
    Path("_data/discord/discord_videos"),  # Alternative local path
]

# Discord meme/image file cache (persistent)
DISCORD_MEME_CACHE_DIR = Path(
    os.getenv("DISCORD_MEME_CACHE_DIR", "/discord/discord_memes")
)

# Failed video tracking for faster startup
FAILED_VIDEOS_LOG = DISCORD_VIDEO_CACHE_DIR / "failed_videos.json"
failed_video_urls: Set[str] = set()
failed_video_details: Dict[str, Dict[str, Any]] = {}


async def load_failed_videos() -> None:
    """Load the list of previously failed video URLs to skip on startup."""
    global failed_video_urls, failed_video_details

    try:
        if FAILED_VIDEOS_LOG.exists():
            with open(FAILED_VIDEOS_LOG, "r") as f:
                data = json.load(f)

                # Backward compatibility - handle old format
                if "failed_urls" in data and isinstance(data["failed_urls"], list):
                    failed_video_urls = set(data["failed_urls"])
                    failed_video_details = {}
                    for url in failed_video_urls:
                        failed_video_details[url] = {
                            "first_failed": "2025-11-25T00:00:00",  # Default for old entries
                            "last_failed": data.get(
                                "last_updated", "2025-11-25T00:00:00"
                            ),
                            "failure_count": 1,
                            "error_type": "legacy_unknown",
                            "error_message": "Migrated from old format",
                        }
                else:
                    # New detailed format
                    failed_video_details = data.get("failed_videos", {})
                    failed_video_urls = set(failed_video_details.keys())

                logging.info(
                    f"📋 [startup] Loaded {len(failed_video_urls)} failed video URLs to skip"
                )
        else:
            failed_video_urls = set()
            failed_video_details = {}
            logging.info("📋 [startup] No failed video log found, starting fresh")
    except Exception as e:
        logging.error(f"❗ [startup] Error loading failed videos log: {e}")
        failed_video_urls = set()
        failed_video_details = {}


async def save_failed_videos() -> None:
    """Save the detailed list of failed video URLs to disk."""
    global failed_video_urls, failed_video_details

    try:
        DISCORD_VIDEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Generate statistics
        total_failures = sum(
            details.get("failure_count", 1) for details in failed_video_details.values()
        )
        error_types = {}
        for details in failed_video_details.values():
            error_type = details.get("error_type", "unknown")
            error_types[error_type] = error_types.get(error_type, 0) + 1

        # Most recent failures for display
        recent_failures = []
        for url, details in failed_video_details.items():
            recent_failures.append(
                {
                    "url": url,
                    "last_failed": details.get("last_failed", ""),
                    "error_type": details.get("error_type", "unknown"),
                    "failure_count": details.get("failure_count", 1),
                }
            )
        recent_failures.sort(key=lambda x: x["last_failed"], reverse=True)
        recent_failures = recent_failures[:10]  # Keep top 10 most recent

        data = {
            "failed_videos": failed_video_details,
            "statistics": {
                "total_failed_urls": len(failed_video_urls),
                "total_failure_attempts": total_failures,
                "error_type_breakdown": error_types,
                "startup_skip_rate": f"{len(failed_video_urls)}/{len(failed_video_urls) + 100}",  # Estimated
                "recent_failures": recent_failures,
            },
            "metadata": {
                "last_updated": datetime.datetime.now().isoformat(),
                "format_version": "2.0",
                "generator": "obs-socket-sentinel",
            },
        }

        with open(FAILED_VIDEOS_LOG, "w") as f:
            json.dump(data, f, indent=2)
        logging.info(
            f"💾 [startup] Saved {len(failed_video_urls)} failed video URLs with detailed stats to {FAILED_VIDEOS_LOG}"
        )
    except Exception as e:
        logging.error(f"❗ [startup] Error saving failed videos log: {e}")


async def add_failed_video(
    url: str, error_type: str = "unknown", error_message: str = "No details"
) -> None:
    """Add a URL to the failed videos list with detailed error information."""
    global failed_video_urls, failed_video_details

    now = datetime.datetime.now().isoformat()

    if url not in failed_video_urls:
        failed_video_urls.add(url)
        failed_video_details[url] = {
            "first_failed": now,
            "last_failed": now,
            "failure_count": 1,
            "error_type": error_type,
            "error_message": error_message,
            "video_id": extract_youtube_video_id(url)
            if "youtube.com" in url or "youtu.be" in url
            else "direct_video",
        }
        logging.warning(
            f"📝 [startup] Added failed video to skip list: {url[:50]}... (Type: {error_type})"
        )
    else:
        # Update existing entry
        details = failed_video_details[url]
        details["last_failed"] = now
        details["failure_count"] = details.get("failure_count", 1) + 1
        details["error_type"] = error_type  # Update to most recent error
        details["error_message"] = error_message
        logging.warning(
            f"📝 [startup] Updated failed video ({details['failure_count']} failures): {url[:50]}... (Type: {error_type})"
        )

    await save_failed_videos()


async def remove_failed_video(url: str) -> None:
    """Remove a URL from the failed videos list (if it works again)."""
    global failed_video_urls, failed_video_details

    if url in failed_video_urls:
        failed_video_urls.remove(url)
        details = failed_video_details.pop(url, {})
        failure_count = details.get("failure_count", 1)
        logging.info(
            f"✅ [startup] Removed recovered video from skip list: {url[:50]}... (was {failure_count} failures)"
        )
        await save_failed_videos()


# Loaded from YAML
GAMES_CONFIG: Dict[str, Dict[str, Any]] = {}
GAME_EMOJI_MAP: Dict[str, set] = {}
ALL_ACTION_KEYS: set[str] = set()  # union of all games' actions
GLOBAL_SYSTEM_ACTIONS: Dict[str, str] = {}  # global actions available across all games
DEFAULT_PROJECT_NAME: Optional[str] = None  # used as fallback for chapters / overlay

# -----------------------------
# RUNTIME STATE
# -----------------------------
action_counts: Dict[tuple[str, str], int] = {}  # (project_key, action) -> count
state_lock = asyncio.Lock()
last_overlay_output: str = ""  # current overlay text
last_action: str = ""  # last action key
last_project: str = ""  # last project/game key used for overlay

# Video/audio duration cache to avoid repeated ffprobe calls
video_duration_cache: Dict[str, float] = {}  # file_path -> duration in seconds
audio_duration_cache: Dict[str, float] = {}  # file_path -> duration in seconds

# Action history for undo functionality
action_history: List[Dict[str, Any]] = []  # List of action records for undo
MAX_UNDO_HISTORY = 50  # Maximum number of actions to keep in undo history

# Achievement notification state
current_achievement: Optional[Dict[str, Any]] = None
achievement_display_until: Optional[float] = None
ACHIEVEMENT_DISPLAY_DURATION = 30.0  # Show achievement for 10 seconds

# Playtime display state
current_playtime: Optional[Dict[str, Any]] = None
playtime_display_until: Optional[float] = None
PLAYTIME_DISPLAY_DURATION = 30  # Show playtime for 5 minutes (300 seconds)

# Achievement percentages display state
current_achievement_percentages: Optional[Dict[str, Any]] = None
achievement_percentages_display_until: Optional[float] = None
ACHIEVEMENT_PERCENTAGES_DISPLAY_DURATION = (
    30.0  # Show achievement percentages for 5 minutes (300 seconds)
)

# News notification state
current_news: Optional[Dict[str, Any]] = None
news_display_until: Optional[float] = None

# CTA (Call-To-Action) notification state
current_subscribe_cta: Optional[Dict[str, Any]] = None
subscribe_cta_display_until: Optional[float] = None
last_subscribe_cta_time: float = 0.0  # When we last triggered subscribe CTA
SUBSCRIBE_CTA_INTERVAL = 15 * 60  # 15 minutes in seconds
SUBSCRIBE_CTA_DURATION = 10.0  # Show for 10 seconds

current_merch_cta: Optional[Dict[str, Any]] = None
merch_cta_display_until: Optional[float] = None
last_merch_cta_time: float = 0.0  # When we last triggered merch CTA
MERCH_CTA_INTERVAL = 22 * 60  # 22 minutes in seconds
MERCH_CTA_DURATION = 12.0  # Show for 12 seconds

# Three.js intro state
current_intro: Optional[Dict[str, Any]] = None
intro_display_until: Optional[float] = None
INTRO_DISPLAY_DURATION = 8.0  # Show intro for 8 seconds

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
run_counters: Dict[str, int] = {}  # project -> last run number
current_run_by_project: Dict[
    str, Optional[int]
] = {}  # project -> current run number or None

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
RUN_PANEL_DURATION_SECONDS = 30  # 3 minutes
run_panel_visible_until: Optional[float] = None

# Max number of runs to *display* in the panel (backend-side visual cap)
MAX_VISIBLE_RUNS = 10

# Discord meme/sound cache
discord_messages_cache: List[dict] = []  # all messages from channel
discord_game_caches: Dict[str, List[dict]] = {}  # per-game filtered messages
discord_cache_lock = asyncio.Lock()  # to avoid concurrent rebuilds

YOUTUBE_RE = re.compile(r"(youtube\.com|youtu\.be)", re.IGNORECASE)


# Synonym fallback dictionaries for common game actions
ACTION_SYNONYMS = {
    "kill": [
        "ELIMINATED",
        "CLAPPED",
        "DELETED",
        "SENT TO LOBBY",
        "UNINSTALLED",
        "DIFFED",
        "SMOKED",
        "FOLDED",
        "DESTROYED",
        "SHUT DOWN",
        "WIPED",
        "GRIEFED",
        "TERMINATED",
    ],
    "death": [
        "SKILL ISSUE",
        "F IN CHAT",
        "FLATLINED",
        "BLUE SCREENED",
        "WASTED",
        "DISCONNECTED",
        "OFFLINED",
        "RAGE QUIT",
        "EXPIRED",
        "GREY SCREEN",
        "FATAL ERROR",
        "DECEASED",
    ],
    "headshot": [
        "ONE TAPPED",
        "CLICKED",
        "AIMBOTTED",
        "DOMED",
        "BRAIN BLAST",
        "VIBE CHECKED",
        "MOGGED",
        "CRITICAL ERROR",
        "HEAD POP",
        "SURGERY",
        "DISMANTLED",
        "NEURAL SHOCK",
    ],
    "downed": [
        "KNOCKED",
        "SLUMPED",
        "PLANKED",
        "BUFFERING",
        "SYSTEM HANG",
        "LAGGING",
        "SLEEP MODE",
        "TOUCHING GRASS",
        "FLOORED",
        "CRITICAL HP",
        "DROPPED",
        "INCAPACITATED",
    ],
    "revive": [
        "REBOOTED",
        "CLUTCHED",
        "RESPAWNED",
        "SYSTEM RESTORE",
        "POWER CYCLED",
        "STIMMED",
        "POCKETED",
        "PHOENIX",
        "RESURRECTED",
        "BACK ONLINE",
        "REFRESHED",
        "SAVED",
    ],
    "funny": [
        "OMEGALUL",
        "POGGERS",
        "COPIUM",
        "EMOTIONAL DAMAGE",
        "SKULL EMOJI",
        "BASED",
        "SUS",
        "CRINGE",
        "GOOFY AHH",
        "TROLLING",
        "MEME",
        "KEKW",
    ],
    "banish": [
        "YEETED",
        "SHADOW REALM",
        "BANHAMMERED",
        "SHIFT+DEL",
        "DESPAWNED",
        "EXORCISED",
        "VOIDED",
        "EVICTED",
        "/KICK",
        "EXPELLED",
        "PURGED",
        "DEPORTED",
    ],
    "extraction": [
        "EXFIL",
        "RTB",
        "GHOSTED",
        "ALT+F4",
        "SECURED",
        "DIPPED",
        "MISSION PASSED",
        "ESCAPED",
        "LOGGED OFF",
        "HOUDINI",
        "EXTRACTED",
        "EVAC",
    ],
    "undo": [
        "CTRL+Z",
        "ROLLBACK",
        "GIT REVERT",
        "RETCON",
        "MISCLICK",
        "FAT FINGER",
        "MULLIGAN",
        "TIME TRAVEL",
        "PATCHING",
        "REVERSED",
        "CANCELLED",
        "UNDONE",
    ],
    "clear": [
        "FORMAT C:",
        "FACTORY RESET",
        "TABULA RASA",
        "HARD RESET",
        "SCRUBBED",
        "FULL SEND",
        "NUKE",
        "CLEAN SLATE",
        "PURGED",
        "WIPED",
        "ZEROED",
        "BLANK",
    ],
    "explosion": [
        "KABOOM",
        "BOOM",
        "DETONATED",
        "NUKED",
        "VAPORIZED",
        "ATOMIZED",
        "OBLITERATED",
        "BLOWN UP",
        "DEMOLISHED",
        "ANNIHILATED",
        "DISINTEGRATED",
        "FRAGMENTED",
        "COMBUSTED",
        "BIG BADA BOOM",
    ],
}


def get_synonyms_for_action(action_key: str, count: int = 10) -> List[str]:
    """
    Get synonyms for a given action word.
    Uses NLTK WordNet if available, otherwise falls back to predefined lists.

    Returns a list of synonyms (uppercase) for use in burst words.
    """
    action_lower = action_key.lower()
    synonyms = []

    # Try NLTK WordNet first (if installed)
    try:
        from nltk.corpus import wordnet

        # Try verb synsets first
        synsets = wordnet.synsets(action_lower, pos=wordnet.VERB)
        
        # If no verb synsets, try noun synsets
        if not synsets:
            synsets = wordnet.synsets(action_lower, pos=wordnet.NOUN)
            logging.info(f"[synonyms] Trying noun synsets for '{action_key}' (no verb synsets found)")

        logging.info(f"[synonyms] Found {len(synsets)} WordNet synsets for '{action_key}'")

        for synset in synsets[:3]:  # Get synonyms from first 3 synsets
            for lemma in synset.lemmas():
                word = lemma.name().replace("_", " ").upper()
                if word != action_key.upper() and word not in synonyms:
                    synonyms.append(word)
                    if len(synonyms) >= count // 2:  # Get half from WordNet, half from curated
                        break
            if len(synonyms) >= count // 2:
                break

        if synonyms:
            logging.info(
                f"[synonyms] Got {len(synonyms)} WordNet synonyms for '{action_key}': {synonyms}"
            )
    except ImportError:
        logging.info(f"[synonyms] NLTK not available, using fallback dictionary")
    except Exception as e:
        logging.warning(f"[synonyms] WordNet error for '{action_key}': {e}, using fallback")

    # Fallback or supplement with predefined synonyms
    if not synonyms or len(synonyms) < count:
        fallback = ACTION_SYNONYMS.get(action_lower, [])

        # Add fallback words that aren't already in the list
        for word in fallback:
            if word not in synonyms:
                synonyms.append(word)
                if len(synonyms) >= count:
                    break

    # If still no synonyms, add the original word variations
    if not synonyms:
        base = action_key.upper()
        synonyms = [base, f"{base}!", f"{base}!!", f"💥{base}💥"]

    # Shuffle for variety
    random.shuffle(synonyms)

    # Return requested count (or all if less available)
    result = synonyms[:count]
    logging.info(
        f"[synonyms] Generated {len(result)} synonyms for '{action_key}': {result[:5]}..."
    )
    return result


def build_video_cycle_pool(
    weighted_candidates: Dict[str, tuple[float, float, str]], action_key: str
) -> List[tuple[str, float, float, str]]:
    """
    Build a cycle pool where videos with higher weights appear multiple times.
    The goal is to cycle through all videos before repeating, with weighted videos
    getting proportionally more plays per cycle.

    Returns a list of (url, weight, duration, original_url) tuples.
    """
    if not weighted_candidates:
        return []

    # Get all videos with their weights
    videos = list(
        weighted_candidates.items()
    )  # [(url, (weight, duration, original_url)), ...]

    if len(videos) == 1:
        # Only one video, just include it once
        url, (weight, duration, original_url) = videos[0]
        return [(url, weight, duration, original_url)]

    # Calculate relative weights
    min_weight = min(w for _, (w, _, _) in videos)

    # Build pool with repetitions based on weight
    pool = []
    for url, (weight, duration, original_url) in videos:
        # Calculate how many times this video should appear in the cycle
        # Videos with min_weight appear once, videos with 2x min_weight appear twice, etc.
        repetitions = max(1, round(weight / min_weight))

        # Cap repetitions at 3x to prevent single video domination
        repetitions = min(repetitions, 3)

        for _ in range(repetitions):
            pool.append((url, weight, duration, original_url))

    logging.info(
        f"[video_cycle] Built pool for {action_key}: {len(pool)} slots from {len(videos)} unique videos"
    )
    for url, (weight, duration, original_url) in videos:
        count = sum(1 for u, _, _, _ in pool if u == url)
        logging.info(
            f"[video_cycle]   {url}: weight={weight:.1f}, appears {count}x in cycle"
        )

    return pool


def apply_anti_repetition_weighting(
    weighted_candidates: Dict[str, float], action_key: str
) -> Dict[str, float]:
    """
    Apply anti-repetition weighting to reduce chances of recently played media.
    Items played more recently get higher penalty, but still remain selectable.

    NOTE: This is now primarily used for non-video media (sounds, memes).
    Videos use the cycle-based system instead.
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
            # Apply penalty based on recency - more gradual than before
            # Most recent gets 10% weight, second gets 25%, third gets 40%, etc.
            recency_index = recent_list.index(url)  # 0 = most recent
            penalty_multiplier = 0.10 + (
                recency_index * 0.15
            )  # 0.10, 0.25, 0.40, 0.55, 0.70, 0.85, 1.0+
            penalty_multiplier = min(
                penalty_multiplier, 0.85
            )  # Cap at 85% for older items
            adjusted_weight = weight * penalty_multiplier

        adjusted_candidates[url] = adjusted_weight

    return adjusted_candidates


def apply_diversity_weighting(
    weighted_candidates: Dict[str, float],
) -> Dict[str, float]:
    """
    Apply diversity weighting to give lower-weighted items a small boost.
    This ensures that content with fewer reactions can still occasionally be selected.
    """
    if not weighted_candidates or len(weighted_candidates) <= 1:
        return weighted_candidates

    # Calculate base stats
    weights = list(weighted_candidates.values())
    min_weight = min(weights)
    max_weight = max(weights)

    # If all weights are the same, no diversity needed
    if max_weight == min_weight:
        return weighted_candidates

    # Add a small diversity bonus that's inversely proportional to weight
    # This gives lower-weighted items a small chance bump
    adjusted_candidates = {}
    for url, weight in weighted_candidates.items():
        # Calculate how "underrepresented" this item is (0.0 to 1.0)
        underrepresented_ratio = 1.0 - (
            (weight - min_weight) / (max_weight - min_weight)
        )
        # Apply a small diversity bonus (up to 15% of the original weight)
        diversity_bonus = weight * (underrepresented_ratio * 0.15)
        adjusted_weight = weight + diversity_bonus
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
    level=logging.INFO,  # Use INFO for production, DEBUG for troubleshooting
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)

# Silence the http logger specifically to prevent excessive request logging
logging.getLogger("http").setLevel(logging.WARNING)

# Silence aiohttp's internal client logger
logging.getLogger("aiohttp.client").setLevel(logging.WARNING)


# -----------------------------
# EMOJI / CONFIG HELPERS
# -----------------------------
def find_cached_video_file(filename: str) -> Optional[Path]:
    """
    Find a cached video file by checking multiple possible cache directories.
    Returns the first existing path found, or None if not found anywhere.
    """
    # Check primary cache directory first
    primary_path = DISCORD_VIDEO_CACHE_DIR / filename
    if primary_path.exists() and primary_path.stat().st_size > 0:
        return primary_path

    # Check alternative cache directories
    for alt_dir in ALTERNATIVE_VIDEO_CACHE_DIRS:
        alt_path = alt_dir / filename
        if alt_path.exists() and alt_path.stat().st_size > 0:
            logging.debug(f"📁 [cache] Found video in alternative cache: {alt_path}")
            return alt_path

    return None


def extract_youtube_video_id(url: str) -> str:
    """Extract YouTube video ID from various YouTube URL formats"""
    try:
        from urllib.parse import urlparse, parse_qs

        parsed = urlparse(url)

        if parsed.hostname in ("www.youtube.com", "youtube.com", "m.youtube.com"):
            if parsed.path == "/watch":
                return parse_qs(parsed.query).get("v", ["unknown"])[0]
            elif parsed.path.startswith("/embed/"):
                return parsed.path.split("/embed/")[-1].split("/")[0]
            elif parsed.path.startswith("/shorts/"):
                return parsed.path.split("/shorts/")[-1].split("/")[0]
        elif parsed.hostname in ("youtu.be",):
            return parsed.path.lstrip("/").split("/")[0]

        # Fallback for unrecognized format
        return url.split("/")[-1].split("?")[0]
    except:
        return "unknown"


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


# Global variables for hotkey mappings
current_hotkey_mappings = {}
last_hotkey_update = 0


# -----------------------------
# SECURITY HELPERS
# -----------------------------
def check_auth_header(request_headers: str) -> bool:
    """
    Check if the Authorization header contains a valid SS_TOKEN.
    Returns True if authorized, False otherwise.
    """
    if not SS_TOKEN:
        # If no token is configured, allow access (backward compatibility)
        return True

    # Parse headers to find Authorization
    lines = request_headers.split("\r\n")
    for line in lines:
        if line.lower().startswith("authorization:"):
            auth_value = line[len("authorization:") :].strip()
            # Support both "Bearer TOKEN" and just "TOKEN" formats
            if auth_value.lower().startswith("bearer "):
                token = auth_value[7:].strip()
            else:
                token = auth_value

            return token == SS_TOKEN

    # No Authorization header found and token is required
    return False


def requires_auth(path: str, method: str = "GET") -> bool:
    """
    Determine if a request path and method requires authentication.

    Public endpoints (no auth required):
    - GET / (main HTML page for browser overlay)
    - GET /ui (action control UI driver)
    - GET /overlay (JSON data for browser overlay)
    - GET /config (configuration for hotkey scripts)
    - GET /dsounds/* (cached audio files for overlay)
    - GET /dvideos/* (cached video files for overlay)
    - GET /dmemes/* (cached meme files for overlay)
    - GET /fonts/* (font files for overlay)

    Protected endpoints (auth required):
    - POST requests (if any)
    - Other endpoints not explicitly listed as public
    """
    # All POST requests require auth EXCEPT the /auth and /hotkeys endpoints
    if method.upper() not in ("GET", "HEAD"):
        # Exceptions: endpoints that don't require auth
        if path == "/auth" or path == "/hotkeys":
            return False
        return True

    # Public GET endpoints for browser overlay and scripts
    if (
        path == "/"
        or path == "/ui"
        or path.startswith("/overlay")
        or path.startswith("/config")
        or path.startswith("/hotkeys")
        or path.startswith("/dsounds/")
        or path.startswith("/dvideos/")
        or path.startswith("/dmemes/")
        or path.startswith("/sounds/")
        or path.startswith("/fonts/")
    ):
        return False

    # Default: require auth for unknown endpoints
    return True


def send_unauthorized(writer: asyncio.StreamWriter) -> None:
    """
    Send a 401 Unauthorized response.
    """
    json_response = '{"error":"Unauthorized: Missing or invalid token"}'
    resp = (
        "HTTP/1.1 401 Unauthorized\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(json_response)}\r\n"
        "Connection: close\r\n"
        "\r\n"
        f"{json_response}"
    )
    writer.write(resp.encode("utf-8"))


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
    global GAMES_CONFIG, GAME_EMOJI_MAP, ALL_ACTION_KEYS, GLOBAL_SYSTEM_ACTIONS, DEFAULT_PROJECT_NAME

    if not CONFIG_PATH.exists():
        logging.error(
            f"❌ Config file {CONFIG_PATH} not found. This app requires a YAML config."
        )
        raise SystemExit(1)

    try:
        cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        logging.info(f"🧾 Loaded config from {CONFIG_PATH}")
    except Exception as e:
        logging.error(
            f"❌ Failed to read/parse config YAML {CONFIG_PATH}: {e}", exc_info=True
        )
        raise SystemExit(1)

    GAMES_CONFIG = cfg.get("games", {}) or {}
    if not GAMES_CONFIG:
        logging.error("❌ Config must define 'games' with at least one game.")
        raise SystemExit(1)

    # Load global system actions (available across all games)
    GLOBAL_SYSTEM_ACTIONS = cfg.get("global_system_actions", {}) or {}
    if GLOBAL_SYSTEM_ACTIONS:
        logging.info(f"🌐 Loaded {len(GLOBAL_SYSTEM_ACTIONS)} global system actions: {list(GLOBAL_SYSTEM_ACTIONS.keys())}")

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

    # Add global system actions
    ALL_ACTION_KEYS.update(GLOBAL_SYSTEM_ACTIONS.keys())

    # Add special system actions that are always available
    ALL_ACTION_KEYS.add("undo")
    ALL_ACTION_KEYS.add("clear")

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

        for cache_dir in [
            DISCORD_SOUND_CACHE_DIR,
            DISCORD_VIDEO_CACHE_DIR,
            DISCORD_MEME_CACHE_DIR,
        ]:
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
                    if (
                        cache_dir == DISCORD_VIDEO_CACHE_DIR
                        and file_path.suffix == ".mp4"
                    ):
                        duration = await get_video_duration_from_file(str(file_path))
                        if (
                            duration is None
                        ):  # Only remove if we can't read duration (corrupted)
                            file_path.unlink()
                            invalid_count += 1
                            logging.info(
                                f"🗑️ [cache] Removed corrupted video file: {file_path}"
                            )
                        # Accept all videos with readable duration, even very short ones

                except Exception as e:
                    logging.warning(f"Failed to clean cache file {file_path}: {e}")

            if cleaned_count > 0:
                logging.info(
                    f"🧹 [cache] Cleaned {cleaned_count} old files from {cache_dir}"
                )
            if invalid_count > 0:
                logging.info(
                    f"🗑️ [cache] Removed {invalid_count} invalid video files from {cache_dir}"
                )

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
        logging.info(
            "[discord] No GAME_EMOJI_MAP defined; skipping per-game cache build."
        )
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
    Now with pagination support to fetch ALL messages from the channel.
    Also builds per-game caches using GAME_EMOJI_MAP.
    """
    global discord_messages_cache, discord_game_caches

    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        logging.debug(
            "[discord] Missing bot token or channel id; skipping cache refresh."
        )
        return

    async with discord_cache_lock:
        headers = {
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            "User-Agent": "obs-socket-sentinel (emoji-meme/sound fetcher, cached)",
        }

        # Reset caches
        discord_messages_cache = []
        discord_game_caches.clear()

        total_messages = 0
        before_id = None  # For pagination
        page = 1
        max_pages = 200  # Safety limit - should handle ~20,000 messages

        logging.info(
            f"[discord] Starting paginated message fetch from channel {DISCORD_CHANNEL_ID}"
        )

        try:
            async with aiohttp.ClientSession() as session:
                while page <= max_pages:
                    # Build URL with pagination
                    api_url = f"https://discord.com/api/v10/channels/{DISCORD_CHANNEL_ID}/messages?limit=100"
                    if before_id:
                        api_url += f"&before={before_id}"

                    logging.info(
                        f"[discord] Fetching page {page}"
                        + (f" (before={before_id})" if before_id else " (latest)")
                    )

                    async with session.get(
                        api_url, headers=headers, timeout=15
                    ) as resp:
                        if resp.status == 429:  # Rate limited
                            retry_after = int(resp.headers.get("retry-after", 5))
                            logging.warning(
                                f"[discord] Rate limited, waiting {retry_after} seconds..."
                            )
                            await asyncio.sleep(retry_after)
                            continue

                        if resp.status != 200:
                            text = await resp.text()
                            logging.warning(
                                f"[discord] Page {page} got non-200 response {resp.status}: {text[:200]}"
                            )
                            break

                        messages = await resp.json()

                        if not messages:  # No more messages
                            logging.info(
                                f"[discord] No more messages found on page {page}, stopping"
                            )
                            break

                        page_count = len(messages)
                        total_messages += page_count

                        logging.info(
                            f"[discord] Page {page}: got {page_count} messages (total so far: {total_messages})"
                        )

                        # Add messages from this page
                        discord_messages_cache.extend(messages)
                        before_id = messages[-1]["id"]  # Last message ID for next page

                        # If we got less than 100, we've reached the end
                        if page_count < 100:
                            logging.info(
                                f"[discord] Reached end of messages (got {page_count} < 100 on page {page})"
                            )
                            break

                        page += 1

                        # Small delay to be nice to Discord API
                        await asyncio.sleep(0.5)

        except Exception as e:
            logging.error(
                f"❗ [discord] Error during paginated fetch: {e}", exc_info=True
            )
            return

        if total_messages == 0:
            logging.warning("[discord] No messages fetched!")
            return

        logging.info(
            f"[discord] Paginated fetch complete: {total_messages} total messages from {page - 1} pages"
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

    logging.info(
        f"[warm_cache] Starting warm cache of all media from {len(discord_messages_cache)} messages"
    )

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
                if "v" in query_params:
                    video_id = query_params["v"][0]
            elif "/embed/" in parsed.path:
                # https://www.youtube.com/embed/VIDEO_ID
                video_id = parsed.path.split("/embed/")[-1].split("/")[0]
            elif "/shorts/" in parsed.path:
                # https://www.youtube.com/shorts/VIDEO_ID
                video_id = parsed.path.split("/shorts/")[-1].split("/")[0]
            elif "youtu.be" in parsed.netloc:
                # https://youtu.be/VIDEO_ID
                video_id = parsed.path.lstrip("/").split("/")[0]

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

            # Check if it's audio - DISABLED for YouTube-only mode
            # if (ctype.startswith("audio/") or
            #     fname.endswith(AUDIO_EXTS) or
            #     any(ext in url.lower() for ext in AUDIO_EXTS)):
            #     audio_urls.add(url)  # Keep Discord URLs as-is for auth

            # Check if it's video
            if (
                ctype.startswith("video/")
                or fname.endswith(VIDEO_EXTS)
                or any(ext in url.lower() for ext in VIDEO_EXTS)
            ):
                video_urls.add(url)  # Keep Discord URLs as-is for auth

        # Process embeds
        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()

            # Check for YouTube URLs
            if emb_url and YOUTUBE_RE.search(emb_url):
                video_urls.add(normalize_url(emb_url))  # Normalize YouTube URLs
            elif emb_url and any(ext in emb_url.lower() for ext in VIDEO_EXTS):
                video_urls.add(normalize_url(emb_url))  # Normalize other video URLs
            # DISABLED: elif emb_url and any(ext in emb_url.lower() for ext in AUDIO_EXTS):
            #     audio_urls.add(normalize_url(emb_url))  # Normalize other audio URLs

            # Check embed video/audio objects
            video_obj = emb.get("video") or {}
            v_url = (video_obj.get("url") or "").strip()
            if v_url:
                if any(ext in v_url.lower() for ext in VIDEO_EXTS) or YOUTUBE_RE.search(
                    v_url
                ):
                    video_urls.add(normalize_url(v_url))

            # DISABLED: audio_obj = emb.get("audio") or {}
            # a_url = (audio_obj.get("url") or "").strip()
            # if a_url and any(ext in a_url.lower() for ext in AUDIO_EXTS):
            #     audio_urls.add(normalize_url(a_url))

        # Check content for direct links
        content = (msg.get("content") or "").strip()
        if "http" in content:
            parts = content.split()
            for part in parts:
                if not part.startswith("http"):
                    continue

                lower_part = part.lower()
                # DISABLED: if any(ext in lower_part for ext in AUDIO_EXTS):
                #     audio_urls.add(normalize_url(part))
                if any(ext in lower_part for ext in VIDEO_EXTS) or YOUTUBE_RE.search(
                    part
                ):
                    video_urls.add(normalize_url(part))

    logging.info(
        f"[warm_cache] Found 0 audio URLs (disabled) and {len(video_urls)} unique video URLs"
    )

    # DISABLED: Skip all audio files - YouTube videos only
    audio_cached = 0
    audio_skipped = len(audio_urls) if audio_urls else 0  # Count as skipped
    audio_failed = 0

    # Skip audio processing entirely
    logging.info(f"[warm_cache] Skipped {audio_skipped} audio URLs (YouTube-only mode)")

    # Pre-cache all video files with better error handling
    video_cached = 0
    video_skipped = 0
    video_failed = 0

    for url in video_urls:
        try:
            # Skip URLs that previously failed to download
            if url in failed_video_urls:
                video_skipped += 1
                logging.debug(
                    f"⏭️ [warm_cache] Skipping previously failed video: {url[:50]}..."
                )
                continue

            h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
            filename = f"{h}.mp4"
            fs_path = find_cached_video_file(filename)

            if fs_path:
                # Validate existing cached video
                duration = await get_video_duration_from_file(str(fs_path))
                if (
                    duration is not None and duration > 0
                ):  # Accept any positive duration
                    video_skipped += 1
                    # Remove from failed list if it exists and works now
                    if url in failed_video_urls:
                        await remove_failed_video(url)
                    continue
                else:
                    # Remove invalid cached video (corrupted, not short)
                    try:
                        fs_path.unlink()
                        logging.info(
                            f"🗑️ [warm_cache] Removed corrupted cached video: {fs_path}"
                        )
                    except Exception:
                        pass

            result, duration, error_type, error_message = await cache_discord_video(url)
            if result and duration is not None:
                video_cached += 1
                # Remove from failed list if it was there (video recovered)
                if url in failed_video_urls:
                    await remove_failed_video(url)
            else:
                video_failed += 1
                logging.warning(f"[warm_cache] Failed to cache video: {url}")
                # Add to failed list for next startup with detailed error info
                await add_failed_video(
                    url, error_type or "unknown", error_message or "No details"
                )
        except Exception as e:
            video_failed += 1
            logging.error(f"[warm_cache] Error caching video {url}: {e}")
            # Add to failed list for next startup
            await add_failed_video(url, "exception", str(e))

    logging.info(
        f"[warm_cache] Complete! Audio: {audio_cached} cached, {audio_skipped} skipped, {audio_failed} failed. Video: {video_cached} cached, {video_skipped} skipped, {video_failed} failed"
    )


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
            logging.error(
                f"[discord] Error in periodic cache refresh: {e}", exc_info=True
            )
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
        logging.info(
            "[discord] No per-game caches available; using full message cache."
        )
        return discord_messages_cache

    if not project:
        # with per-game caches, but no explicit project, we can't disambiguate → []
        logging.info(
            "[discord] No project provided; with per-game caches this returns []."
        )
        return []

    key = resolve_game_key(project)
    if not key:
        logging.info(
            f"[discord] Unknown project '{project}'; falling back to full cache for better video selection."
        )
        return discord_messages_cache

    msgs = discord_game_caches.get(key)
    if msgs is None or len(msgs) == 0:
        logging.info(
            f"[discord] No per-game cache for '{key}'; falling back to full cache for better video selection."
        )
        return discord_messages_cache

    logging.info(f"[discord] Using {len(msgs)} messages from {key} game cache.")
    return msgs


# -----------------------------
# CACHED MEDIA LOOKUP (NO DOWNLOADS)
# -----------------------------
async def get_cached_discord_sound(
    action_key: str, project: Optional[str]
) -> Optional[str]:
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

            if (
                ctype.startswith("audio/")
                or fname.endswith(AUDIO_EXTS)
                or any(ext in url.lower() for ext in AUDIO_EXTS)
            ):
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
    weighted_candidates = apply_anti_repetition_weighting(
        weighted_candidates, action_key
    )

    # Apply diversity weighting to give lower-reaction content a chance
    weighted_candidates = apply_diversity_weighting(weighted_candidates)

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


async def get_cached_discord_meme(
    action_key: str, project: Optional[str]
) -> Optional[str]:
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

            if (
                ctype.startswith("image/")
                or fname.endswith((".gif", ".webp", ".png", ".jpg", ".jpeg"))
                or any(
                    ext in url.lower()
                    for ext in [".gif", ".webp", ".png", ".jpg", ".jpeg"]
                )
            ):
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
                if u and any(
                    ext in u.lower()
                    for ext in [".gif", ".webp", ".png", ".jpg", ".jpeg"]
                ):
                    u = _normalize_meme_url(u)
                    prev = weighted_candidates.get(u, 0.0)
                    weighted_candidates[u] = prev + match_weight

            if emb_url and (
                "tenor.com/view" in emb_url.lower()
                or any(ext in emb_url.lower() for ext in [".gif", ".webp"])
            ):
                emb_url = _normalize_meme_url(emb_url)
                prev = weighted_candidates.get(emb_url, 0.0)
                weighted_candidates[emb_url] = prev + match_weight

    if not weighted_candidates:
        return None

    # Apply anti-repetition weighting to avoid playing same memes repeatedly
    weighted_candidates = apply_anti_repetition_weighting(
        weighted_candidates, action_key
    )

    # Apply diversity weighting to give lower-reaction content a chance
    weighted_candidates = apply_diversity_weighting(weighted_candidates)

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


async def get_cached_discord_video(
    action_key: str, project: Optional[str]
) -> tuple[Optional[str], Optional[float], Optional[str]]:
    """
    Look up a random cached video for the action/project, but don't download anything.
    Only returns videos that are already cached locally AND have valid duration.
    Returns: (cached_url, duration, original_source_url)
    """
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        return None, None, None

    target_emoji = get_action_emoji(action_key, project)
    if not target_emoji:
        logging.info(
            f"[video] No target emoji found for action={action_key} project={project}"
        )
        return None, None, None

    normalized_target = normalize_emoji(target_emoji)
    logging.info(
        f"[video] Looking for videos with emoji '{target_emoji}' (normalized: '{normalized_target}') for action={action_key}"
    )

    messages = _select_messages_for_project(project)
    if not messages:
        logging.info(f"[video] No messages found for project={project}")
        return None, None, None

    logging.info(f"[video] Checking {len(messages)} messages for project={project}")

    # Build list of candidate video URLs (same logic as fetch_random_discord_video)
    weighted_candidates: Dict[
        str, tuple[float, float, str]
    ] = {}  # cache_url -> (weight, duration, original_url)
    VIDEO_EXTS = (".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv")

    messages_with_videos = 0
    messages_with_target_emoji = 0
    messages_with_both = 0

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
            if (
                ctype.startswith("video/")
                or fname.endswith(VIDEO_EXTS)
                or any(ext in url.lower() for ext in VIDEO_EXTS)
            ):
                has_video_content = True
                break

        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()
            if emb_url and (
                any(ext in emb_url.lower() for ext in VIDEO_EXTS)
                or YOUTUBE_RE.search(emb_url)
            ):
                has_video_content = True
                break

        if has_video_content:
            messages_with_videos += 1

        # Check if this message has the target emoji
        has_target_emoji = False
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
                    has_target_emoji = True
            else:
                if name.lower() == action_key.lower():
                    matched = True
                    has_target_emoji = True

            if matched:
                match_weight += count  # Sum all matching emoji reactions

        if has_target_emoji:
            messages_with_target_emoji += 1

        if has_video_content and has_target_emoji:
            messages_with_both += 1

        if match_weight <= 0:
            continue

        # This message has both video content AND matching reactions

        # Check attachments for videos
        for att in msg.get("attachments", []):
            url = (att.get("url") or "").strip()
            fname = (att.get("filename") or "").lower()
            ctype = (att.get("content_type") or "").lower()

            if not url:
                continue

            if (
                ctype.startswith("video/")
                or fname.endswith(VIDEO_EXTS)
                or any(ext in url.lower() for ext in VIDEO_EXTS)
            ):
                # Check if this video is already cached AND valid
                h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
                filename = f"{h}.mp4"
                fs_path = find_cached_video_file(filename)

                logging.info(
                    f"[video] Message {msg_id}: checking attachment video {url[:50]}... -> {filename}"
                )
                logging.info(
                    f"[video] Message {msg_id}: full attachment URL for hash: {url}"
                )
                logging.info(f"[video] Message {msg_id}: calculated hash: {h}")

                if fs_path:
                    duration = await get_video_duration_from_file(str(fs_path))
                    logging.info(
                        f"[video] Message {msg_id}: cached file found at {fs_path}, duration={duration}"
                    )
                    if (
                        duration is not None and duration > 0
                    ):  # Accept any positive duration
                        cache_url = f"/dvideos/{filename}"
                        prev_weight, _, _ = weighted_candidates.get(
                            cache_url, (0.0, 0.0, url)
                        )
                        weighted_candidates[cache_url] = (
                            prev_weight + match_weight,
                            duration,
                            url,
                        )
                        logging.info(
                            f"[video] Message {msg_id}: ADDED video candidate {cache_url} (weight={prev_weight + match_weight}, duration={duration})"
                        )
                    else:
                        logging.warning(
                            f"[video] Message {msg_id}: cached file has invalid duration ({duration})"
                        )
                else:
                    logging.info(
                        f"[video] Message {msg_id}: cached file NOT found: {filename}"
                    )

        # Check embeds for videos (including YouTube)
        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()
            if emb_url and (
                any(ext in emb_url.lower() for ext in VIDEO_EXTS)
                or YOUTUBE_RE.search(emb_url)
            ):
                h = hashlib.sha256(emb_url.encode("utf-8")).hexdigest()[:32]
                filename = f"{h}.mp4"
                fs_path = find_cached_video_file(filename)

                logging.info(
                    f"[video] Message {msg_id}: checking embed video {emb_url[:50]}... -> {filename}"
                )
                logging.info(
                    f"[video] Message {msg_id}: full embed URL for hash: {emb_url}"
                )
                logging.info(f"[video] Message {msg_id}: calculated hash: {h}")

                if fs_path:
                    duration = await get_video_duration_from_file(str(fs_path))
                    logging.info(
                        f"[video] Message {msg_id}: cached file found at {fs_path}, duration={duration}"
                    )
                    if (
                        duration is not None and duration > 0
                    ):  # Accept any positive duration
                        cache_url = f"/dvideos/{filename}"
                        prev_weight, _, _ = weighted_candidates.get(
                            cache_url, (0.0, 0.0, emb_url)
                        )
                        weighted_candidates[cache_url] = (
                            prev_weight + match_weight,
                            duration,
                            emb_url,
                        )
                        logging.info(
                            f"[video] Message {msg_id}: ADDED video candidate {cache_url} (weight={prev_weight + match_weight}, duration={duration})"
                        )
                    else:
                        logging.warning(
                            f"[video] Message {msg_id}: cached file has invalid duration ({duration})"
                        )
                else:
                    logging.info(
                        f"[video] Message {msg_id}: cached file NOT found: {filename}"
                    )
                    # Let's also check what files ARE in the cache directory
                    try:
                        for cache_dir in [
                            DISCORD_VIDEO_CACHE_DIR
                        ] + ALTERNATIVE_VIDEO_CACHE_DIRS:
                            if cache_dir.exists():
                                cache_files = list(cache_dir.glob("*.mp4"))
                                logging.info(
                                    f"[video] Cache directory {cache_dir} has {len(cache_files)} files: {[f.name for f in cache_files[:3]]}"
                                )
                    except Exception:
                        pass

    logging.info(
        f"[video] SUMMARY for {action_key}/{project}: {len(messages)} messages, {messages_with_videos} with videos, {messages_with_target_emoji} with emoji '{target_emoji}', {messages_with_both} with both"
    )

    if not weighted_candidates:
        logging.info(
            f"[video] No valid cached videos found for action={action_key} project={project}"
        )
        return None, None, None

    # Apply anti-repetition weighting to avoid playing same videos repeatedly
    # Convert tuple format to simple format for anti-repetition processing
    simple_candidates = {
        url: weight for url, (weight, _, _) in weighted_candidates.items()
    }
    simple_candidates = apply_anti_repetition_weighting(simple_candidates, action_key)
    simple_candidates = apply_diversity_weighting(simple_candidates)
    # Convert back to tuple format
    adjusted_candidates = {
        url: (
            simple_candidates[url],
            weighted_candidates[url][1],
            weighted_candidates[url][2],
        )
        for url in simple_candidates
    }

    # Weighted random choice from cached candidates
    items = list(adjusted_candidates.items())
    total_weight = sum(weight for _, (weight, _, _) in items)
    r = random.uniform(0, total_weight)
    upto = 0.0
    for url, (weight, duration, original_url) in items:
        upto += weight
        if r <= upto:
            logging.info(
                f"📺 [cache] Selected cached video for action={action_key}: {url} (duration={duration}s)"
            )
            # Track this selection to avoid repetition
            track_played_media(url, action_key)
            return url, duration, original_url

    # Fallback
    chosen_url, (_, chosen_duration, chosen_original) = random.choice(items)
    logging.info(
        f"📺 [cache] Fallback selected cached video for action={action_key}: {chosen_url} (duration={chosen_duration}s)"
    )
    track_played_media(chosen_url, action_key)
    return chosen_url, chosen_duration, chosen_original


# -----------------------------
# WEIGHT-AWARE CACHED MEDIA FUNCTIONS
# -----------------------------


async def get_cached_discord_sound_with_weight(
    action_key: str, project: Optional[str]
) -> tuple[Optional[str], float]:
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

            if (
                ctype.startswith("audio/")
                or fname.endswith(AUDIO_EXTS)
                or any(ext in url.lower() for ext in AUDIO_EXTS)
            ):
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
                    weighted_candidates[cache_url] = (
                        weighted_candidates.get(cache_url, 0.0) + match_weight
                    )

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
                    weighted_candidates[cache_url] = (
                        weighted_candidates.get(cache_url, 0.0) + match_weight
                    )

    if not weighted_candidates:
        return None, 0.0

    # Apply anti-repetition and weighted selection
    weighted_candidates = apply_anti_repetition_weighting(
        weighted_candidates, action_key
    )
    weighted_candidates = apply_diversity_weighting(weighted_candidates)

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


async def get_cached_discord_meme_with_weight(
    action_key: str, project: Optional[str]
) -> tuple[Optional[str], float]:
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
                weighted_candidates[url] = (
                    weighted_candidates.get(url, 0.0) + match_weight
                )

        # Check embeds for images/GIFs
        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()

            # Check various embed URL types
            for label, u in [
                ("url", emb.get("url")),
                ("image.url", emb.get("image", {}).get("url")),
                ("thumbnail.url", emb.get("thumbnail", {}).get("url")),
                ("video.thumbnail_url", emb.get("video", {}).get("thumbnail_url")),
            ]:
                if u and any(
                    ext in u.lower()
                    for ext in [".gif", ".webp", ".png", ".jpg", ".jpeg"]
                ):
                    # CRITICAL: Exclude YouTube thumbnails - these should be handled by video logic, not meme logic
                    if "ytimg.com" in u.lower() or "youtube.com" in u.lower():
                        continue  # Skip YouTube thumbnails
                    weighted_candidates[u] = (
                        weighted_candidates.get(u, 0.0) + match_weight
                    )

            if emb_url and (
                (
                    "tenor.com/view" in emb_url.lower()
                    and not emb_url.lower().endswith(".mp4")
                )  # Tenor images only, not videos
                or any(ext in emb_url.lower() for ext in [".gif", ".webp"])
            ):
                weighted_candidates[emb_url] = (
                    weighted_candidates.get(emb_url, 0.0) + match_weight
                )

    if not weighted_candidates:
        return None, 0.0

    # Apply anti-repetition and weighted selection
    weighted_candidates = apply_anti_repetition_weighting(
        weighted_candidates, action_key
    )
    weighted_candidates = apply_diversity_weighting(weighted_candidates)

    # Weighted random choice
    items = list(weighted_candidates.items())
    total_weight = sum(w for _, w in items)
    r = random.uniform(0, total_weight)
    upto = 0.0
    for url, w in items:
        upto += w
        if r <= upto:
            # Convert remote URL to local cached URL
            cached_url = await cache_discord_meme(url)
            if cached_url:
                track_played_media(cached_url, action_key)
                return cached_url, w
            else:
                # Failed to cache, skip this one
                logging.warning(
                    f"❗ [meme] Failed to cache selected meme: {url[:50]}..."
                )
                continue

    # Fallback
    chosen_url, chosen_weight = random.choice(items)
    cached_url = await cache_discord_meme(chosen_url)
    if cached_url:
        track_played_media(cached_url, action_key)
        return cached_url, chosen_weight
    else:
        logging.warning(
            f"❗ [meme] Failed to cache fallback meme: {chosen_url[:50]}..."
        )
        return None, 0.0


async def get_cached_discord_video_with_weight(
    action_key: str, project: Optional[str]
) -> tuple[Optional[str], float, Optional[float], Optional[str]]:
    """
    Look up a random cached video for the action/project with emoji weight.
    Returns: (cached_url, total_weight, duration, original_source_url)
    """
    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        return None, 0.0, None, None

    target_emoji = get_action_emoji(action_key, project)
    if not target_emoji:
        logging.info(
            f"[video_weight] No target emoji found for action={action_key} project={project}"
        )
        return None, 0.0, None, None

    normalized_target = normalize_emoji(target_emoji)
    logging.info(
        f"[video_weight] Looking for videos with emoji '{target_emoji}' (normalized: '{normalized_target}') for action={action_key}"
    )

    messages = _select_messages_for_project(project)
    if not messages:
        logging.info(f"[video_weight] No messages found for project={project}")
        return None, 0.0, None, None

    logging.info(
        f"[video_weight] Checking {len(messages)} messages for project={project}"
    )

    # cache_url -> (weight, duration, original_url)
    weighted_candidates: Dict[str, tuple[float, float, str]] = {}
    VIDEO_EXTS = (".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv")

    messages_with_videos = 0
    messages_with_target_emoji = 0
    messages_with_both = 0

    for msg in messages:
        msg_id = msg.get("id", "unknown")  # Add message ID for debug
        reactions = msg.get("reactions") or []
        match_weight = 0

        # Check if this message has video content
        has_video_content = False
        for att in msg.get("attachments", []):
            url = (att.get("url") or "").strip()
            fname = (att.get("filename") or "").lower()
            ctype = (att.get("content_type") or "").lower()
            if (
                ctype.startswith("video/")
                or fname.endswith(VIDEO_EXTS)
                or any(ext in url.lower() for ext in VIDEO_EXTS)
            ):
                has_video_content = True
                break

        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()
            if emb_url and (
                any(ext in emb_url.lower() for ext in VIDEO_EXTS)
                or YOUTUBE_RE.search(emb_url)
            ):
                has_video_content = True
                break

        if has_video_content:
            messages_with_videos += 1

        # Calculate emoji weight for this message
        has_target_emoji = False
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
                    has_target_emoji = True
            else:
                if name.lower() == action_key.lower():
                    matched = True
                    has_target_emoji = True

            if matched:
                match_weight += count

        if has_target_emoji:
            messages_with_target_emoji += 1

        if has_video_content and has_target_emoji:
            messages_with_both += 1

        if match_weight <= 0:
            continue

        # Check attachments for videos
        for att in msg.get("attachments", []):
            url = (att.get("url") or "").strip()
            fname = (att.get("filename") or "").lower()
            ctype = (att.get("content_type") or "").lower()

            if not url:
                continue

            if (
                ctype.startswith("video/")
                or fname.endswith(VIDEO_EXTS)
                or any(ext in url.lower() for ext in VIDEO_EXTS)
            ):
                h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
                filename = f"{h}.mp4"
                fs_path = find_cached_video_file(filename)

                if fs_path:
                    duration = await get_video_duration_from_file(str(fs_path))
                    if (
                        duration is not None and duration > 0
                    ):  # Accept any positive duration
                        cache_url = f"/dvideos/{filename}"
                        prev_weight, _, _ = weighted_candidates.get(
                            cache_url, (0.0, duration, url)
                        )
                        weighted_candidates[cache_url] = (
                            prev_weight + match_weight,
                            duration,
                            url,
                        )
                    else:
                        logging.info(
                            f"[video_weight] Message {msg_id}: cached file has INVALID duration ({duration}) at {fs_path}"
                        )
                else:
                    logging.info(
                        f"[video_weight] Message {msg_id}: video NOT CACHED: {filename} from {url[:50]}..."
                    )

        # Check embeds for videos (including YouTube and Tenor)
        for emb in msg.get("embeds", []):
            emb_url = (emb.get("url") or "").strip()
            if emb_url and (
                any(ext in emb_url.lower() for ext in VIDEO_EXTS)
                or YOUTUBE_RE.search(emb_url)
            ):
                # DISABLED: "tenor.com" in emb_url.lower()  # YouTube-only mode
                h = hashlib.sha256(emb_url.encode("utf-8")).hexdigest()[:32]
                filename = f"{h}.mp4"
                fs_path = find_cached_video_file(filename)

                if fs_path:
                    duration = await get_video_duration_from_file(str(fs_path))
                    if duration is not None and duration > 0:
                        cache_url = f"/dvideos/{filename}"
                        prev_weight, _, _ = weighted_candidates.get(
                            cache_url, (0.0, duration, emb_url)
                        )
                        weighted_candidates[cache_url] = (
                            prev_weight + match_weight,
                            duration,
                            emb_url,
                        )
                    else:
                        logging.info(
                            f"[video_weight] Message {msg_id}: embed cached file has INVALID duration ({duration}) at {fs_path}"
                        )
                else:
                    logging.info(
                        f"[video_weight] Message {msg_id}: embed video NOT CACHED: {filename} from {emb_url[:50]}..."
                    )

    logging.info(
        f"[video_weight] SUMMARY for {action_key}/{project}: {len(messages)} messages, found {len(weighted_candidates)} cached videos"
    )
    logging.info(
        f"[video_weight] Stats: {messages_with_videos} msgs with videos, {messages_with_target_emoji} msgs with emoji '{target_emoji}', {messages_with_both} msgs with both"
    )

    if not weighted_candidates:
        return None, 0.0, None, None

    # Use cycle-based selection for videos
    global video_cycle_state

    # Check if we need to initialize or rebuild the cycle
    cycle_state = video_cycle_state.get(action_key)

    # Rebuild cycle if:
    # 1. No cycle exists yet
    # 2. Available videos changed (different candidates than cycle pool)
    current_video_urls = set(weighted_candidates.keys())
    needs_rebuild = False

    if not cycle_state:
        needs_rebuild = True
        logging.info(
            f"[video_cycle] No cycle state for {action_key}, building new cycle"
        )
    else:
        # Check if the set of available videos changed
        pool_urls = set(url for url, _, _, _ in cycle_state["pool"])
        if current_video_urls != pool_urls:
            needs_rebuild = True
            logging.info(
                f"[video_cycle] Available videos changed for {action_key}, rebuilding cycle"
            )

    if needs_rebuild:
        pool = build_video_cycle_pool(weighted_candidates, action_key)
        video_cycle_state[action_key] = {
            "pool": pool,
            "remaining": pool.copy(),  # Track which specific pool slots remain
            "cycle_number": 1,
        }
        cycle_state = video_cycle_state[action_key]
        logging.info(
            f"[video_cycle] Created new cycle #{cycle_state['cycle_number']} for {action_key} with {len(pool)} slots"
        )

    # If all slots have been used, start a new cycle
    if not cycle_state["remaining"]:
        cycle_state["remaining"] = cycle_state["pool"].copy()
        cycle_state["cycle_number"] += 1
        logging.info(
            f"[video_cycle] Cycle complete! Starting cycle #{cycle_state['cycle_number']} for {action_key}"
        )

    # Randomly select from remaining slots (equal probability)
    idx = random.randint(0, len(cycle_state["remaining"]) - 1)
    chosen_url, chosen_weight, chosen_duration, chosen_original = cycle_state[
        "remaining"
    ].pop(idx)

    # Track in legacy history for backward compatibility
    track_played_media(chosen_url, action_key)

    played_count = len(cycle_state["pool"]) - len(cycle_state["remaining"])
    total_count = len(cycle_state["pool"])
    logging.info(
        f"[video_cycle] Selected '{chosen_url}' (weight={chosen_weight:.1f}) - progress: {played_count}/{total_count} in cycle #{cycle_state['cycle_number']}"
    )

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


async def fetch_random_discord_meme(
    action_key: str, project: Optional[str]
) -> Optional[str]:
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
        logging.info(
            "[discord] Message cache empty; doing one-time refresh before meme selection."
        )
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
                or any(
                    ext in url.lower()
                    for ext in [".gif", ".webp", ".png", ".jpg", ".jpeg"]
                )
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
                    if any(
                        ext in u.lower()
                        for ext in [".gif", ".webp", ".png", ".jpg", ".jpeg"]
                    ):
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
                if "tenor.com/view" in lower_p or any(
                    ext in lower_p for ext in [".gif", ".webp", ".png", ".jpg", ".jpeg"]
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
    weighted_candidates = apply_anti_repetition_weighting(
        weighted_candidates, action_key
    )
    weighted_candidates = apply_diversity_weighting(weighted_candidates)

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
async def fetch_random_discord_video(
    action_key: str, project: Optional[str]
) -> tuple[Optional[str], Optional[float]]:
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
        logging.debug(
            "[discord] Missing bot token or channel id; skipping video fetch."
        )
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
        logging.info(
            "[discord] Message cache empty; doing one-time refresh before video selection."
        )
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
                match_weight += (
                    count  # Sum all matching emoji reactions for voting weight
                )

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
                if any(ext in lower_emb for ext in VIDEO_EXTS) or _looks_like_youtube(
                    emb_url
                ):
                    logging.info(f"[discord] (video) Embed url on {msg_id}: {emb_url}")
                    _add_candidate(emb_url, match_weight)

            video_obj = emb.get("video") or {}
            v_url = (video_obj.get("url") or "").strip()
            if v_url:
                lower_v = v_url.lower()
                if any(ext in lower_v for ext in VIDEO_EXTS) or _looks_like_youtube(
                    v_url
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
                if any(ext in lower_p for ext in VIDEO_EXTS) or _looks_like_youtube(p):
                    logging.info(
                        f"[discord] (video) Content video candidate on {msg_id}: {p}"
                    )
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
            local_url, duration, _, _ = await cache_discord_video(url)
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
    local_url, duration, _, _ = await cache_discord_video(chosen)
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
            logging.info(
                "⌛ [video] Fetched YouTube duration=%.2fs for %s", duration, url
            )
        else:
            logging.info("⌛ [video] No duration metadata found for %s", url)
        return duration
    except Exception as e:
        logging.error(
            f"❗ [video] Error getting duration for {url}: {e}", exc_info=True
        )
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
                logging.info(
                    f"🔄 [warm_cache] Retry {attempt}/{max_retries} for audio {url[:50]}..."
                )
                await asyncio.sleep(1 * attempt)  # Exponential backoff

            logging.info(
                f"🔊 [warm_cache] Downloading audio {url[:50]}... -> {fs_path}"
            )

            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=45),
                connector=aiohttp.TCPConnector(limit=10),
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
                logging.info(
                    f"💾 [warm_cache] Cached audio {url[:50]}... -> {fs_path} ({len(data)} bytes)"
                )
                return f"/dsounds/{fname}"
            else:
                logging.warning(f"❗ [discord] Empty audio data for {url[:50]}...")
                continue

        except asyncio.TimeoutError:
            logging.warning(
                f"⏱️ [discord] Timeout downloading audio {url[:50]}... (attempt {attempt + 1})"
            )
            continue
        except Exception as e:
            logging.error(
                f"❗ [discord] Error caching audio {url[:50]}... (attempt {attempt + 1}): {e}"
            )
            if attempt == max_retries - 1:  # Last attempt
                logging.error(
                    f"❗ [discord] Final failure caching audio {url[:50]}...",
                    exc_info=True,
                )
            continue

    # Clean up partial file on failure
    if fs_path.exists():
        try:
            fs_path.unlink()
        except Exception:
            pass
    return None


async def cache_discord_video(
    url: str,
) -> tuple[Optional[str], Optional[float], Optional[str], Optional[str]]:
    """
    Download a video URL (YouTube or direct) into an ephemeral cache directory and return
    a local HTTP path like /dvideos/<hashed>.mp4 that the overlay can play, plus duration.

    - Files are stored under DISCORD_VIDEO_CACHE_DIR
    - Names are based on SHA256(url) + .mp4 extension
    - Uses yt-dlp for YouTube videos
    - Filters out videos shorter than 0.5 seconds (static images)
    - Returns (local_path, duration_seconds, error_type, error_message)
    """
    if not url:
        return None, None, "empty_url", "URL is empty"

    DISCORD_VIDEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Stable name based on URL hash
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    fname = f"{h}.mp4"
    fs_path = DISCORD_VIDEO_CACHE_DIR / fname

    logging.info(f"[cache] Caching video with URL: {url}")
    logging.info(f"[cache] Calculated hash: {h}")
    logging.info(f"[cache] Target file path: {fs_path}")

    # Check for existing valid cached file
    logging.debug(
        f"🔍 [video_cache] Checking cache for {fs_path.name}. Exists: {fs_path.exists()}, Size: {fs_path.stat().st_size if fs_path.exists() else 0}"
    )
    if fs_path.exists() and fs_path.stat().st_size > 0:
        logging.debug(f"📺 [discord] Using cached video for {url[:50]}... -> {fs_path}")
        # Try to get duration from existing file
        duration = await get_video_duration_from_file(str(fs_path))
        logging.debug(
            f"🔍 [video_cache] get_video_duration_from_file returned: {duration} for {fs_path.name}"
        )
        if duration is None:
            logging.warning(
                f"🗑️ [video] Cached video {fs_path.name} is invalid (no duration or zero duration). Removing and re-downloading."
            )
            # File is invalid (too short or corrupted), remove it
            try:
                fs_path.unlink()
                logging.info(f"🗑️ [video] Removed invalid cached video: {fs_path}")
            except Exception as e:
                logging.error(
                    f"❗ [video] Error removing invalid cached video {fs_path}: {e}"
                )
        else:
            logging.info(
                f"✅ [video] Using valid cached video {fs_path.name} (duration: {duration}s)."
            )
            return f"/dvideos/{fname}", duration, None, None
    else:
        logging.info(
            f"⬇️ [video] Cached file {fs_path.name} not found or empty. Downloading..."
        )

    # Check if it's a YouTube video
    is_youtube = bool(YOUTUBE_RE.search(url))
    duration: Optional[float] = None

    # Retry logic for downloads
    max_retries = 2 if is_youtube else 3
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                logging.info(
                    f"🔄 [warm_cache] Retry {attempt}/{max_retries} for video {url[:50]}..."
                )
                await asyncio.sleep(2 * attempt)  # Exponential backoff

            logging.info(
                f"📺 [warm_cache] Downloading video {url[:50]}... -> {fs_path}"
            )

            if is_youtube:
                # Use yt-dlp to download YouTube video
                try:
                    import yt_dlp  # type: ignore
                except ImportError:
                    logging.warning(
                        f"yt_dlp not installed; cannot download YouTube video {url[:50]}... "
                        f"Install it with 'pip install yt_dlp' to enable video caching."
                    )
                    return None, None, "missing_ytdlp", "yt-dlp not installed"

                async def _download_youtube(
                    u: str,
                ) -> tuple[Optional[float], Optional[str], Optional[str]]:
                    def _inner() -> tuple[
                        Optional[float], Optional[str], Optional[str]
                    ]:
                        # Random delay between 1-10 seconds to appear more human-like
                        import random
                        import time

                        delay = random.uniform(1, 10)
                        logging.info(
                            f"⏸️ [yt-dlp] Random anti-bot delay: {delay:.1f}s for {u[:50]}..."
                        )
                        time.sleep(delay)

                        ydl_opts = {
                            # Force MP4 format for consistent web playback
                            "format": "best[ext=mp4]/best[height<=720]/best",
                            "outtmpl": str(fs_path),
                            "quiet": True,
                            "no_warnings": False,
                            "writeautomaticsub": False,
                            "writesubtitles": False,
                            "writethumbnail": False,
                            "embed_subs": False,
                            # Force MP4 container for web compatibility
                            "merge_output_format": "mp4",
                            # Built-in yt-dlp anti-blocking options
                            "socket_timeout": 60,  # Longer timeout
                            "retries": 5,  # More retries
                            "fragment_retries": 10,  # Retry fragments more
                            "extract_flat": False,
                            "ignoreerrors": False,
                            "no_check_certificate": True,
                            # Anti-blocking sleep settings
                            "sleep_requests": random.uniform(
                                3, 8
                            ),  # Longer sleep between requests
                            "sleep_subtitles": random.uniform(1, 3),
                            "sleep_formats": random.uniform(
                                1, 5
                            ),  # Sleep between format attempts
                            "sleep_fragments": random.uniform(
                                0.5, 2
                            ),  # Sleep between fragments
                            # Throttle download speed to appear less bot-like
                            "ratelimit": random.randint(
                                500000, 2000000
                            ),  # 500KB-2MB/s limit
                            # User-agent rotation with more realistic agents
                            "http_headers": {
                                "User-Agent": random.choice(
                                    [
                                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
                                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
                                    ]
                                )
                            },
                            # Additional anti-detection options
                            "skip_unavailable_fragments": True,
                            "keep_fragments": False,
                            "abort_on_unavailable_fragment": False,
                            # Force IPv4 to avoid IPv6 detection
                            "force_ipv4": True,
                            # Add some randomness to avoid pattern detection
                            "http_chunk_size": random.randint(
                                1024, 10240
                            ),  # Random chunk size
                        }

                        # Add cookies if available
                        cookies_file = "/app/youtube/cookies.txt"
                        if os.path.exists(cookies_file):
                            ydl_opts["cookiefile"] = cookies_file
                            logging.info(f"[yt-dlp] Using cookies from {cookies_file}")
                        else:
                            logging.debug(
                                f"[yt-dlp] No cookies file found at {cookies_file}"
                            )
                        try:
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                logging.info(
                                    f"📹 [yt-dlp] Extracting info for {u[:50]}..."
                                )
                                info = ydl.extract_info(u, download=True)
                                if not info:
                                    logging.warning(
                                        f"❗ [yt-dlp] No info extracted for {u[:50]}..."
                                    )
                                    return None, "no_info", "No info extracted"

                                dur = info.get("duration")
                                if dur is None:
                                    logging.warning(
                                        f"❗ [yt-dlp] No duration in info for {u[:50]}..."
                                    )
                                    return (
                                        None,
                                        "no_duration",
                                        "No duration in metadata",
                                    )
                                try:
                                    duration = float(dur)
                                    if duration > 0:
                                        logging.info(
                                            f"✅ [yt-dlp] Downloaded video: {u[:50]}... ({duration}s)"
                                        )
                                        return duration, None, None
                                    else:
                                        logging.warning(
                                            f"❗ [yt-dlp] Zero duration video: {u[:50]}..."
                                        )
                                        return (
                                            None,
                                            "zero_duration",
                                            f"Video has zero duration",
                                        )
                                except Exception as e:
                                    logging.error(
                                        f"❗ [yt-dlp] Duration parse error for {u[:50]}...: {e}"
                                    )
                                    return None, "duration_parse_error", str(e)
                        except Exception as e:
                            error_str = str(e)
                            logging.error(
                                f"❗ [yt-dlp] Download failed for {u[:50]}...: {e}"
                            )

                            # Categorize common yt-dlp errors
                            if "Video unavailable" in error_str:
                                if "private" in error_str.lower():
                                    return None, "video_private", error_str
                                elif "copyright" in error_str.lower():
                                    return None, "copyright_claim", error_str
                                elif (
                                    "Terms of Service" in error_str
                                    or "ToS" in error_str
                                ):
                                    return None, "tos_violation", error_str
                                else:
                                    return None, "video_unavailable", error_str
                            elif "Sign in to confirm your age" in error_str:
                                return None, "age_restricted", error_str
                            elif "This video is no longer available" in error_str:
                                return None, "video_removed", error_str
                            else:
                                return None, "ytdlp_error", error_str

                    return await asyncio.to_thread(_inner)

                duration, error_type, error_message = await _download_youtube(url)
                if (
                    duration is not None
                    and fs_path.exists()
                    and fs_path.stat().st_size > 0
                ):
                    logging.info(
                        f"📹 [warm_cache] Downloaded YouTube video {url[:50]}... -> {fs_path} (duration={duration}s, size={fs_path.stat().st_size} bytes)"
                    )
                    return f"/dvideos/{fname}", duration, None, None
                else:
                    if attempt < max_retries - 1:
                        continue
                    # Use captured error details or fallback
                    final_error_type = error_type or "ytdlp_failed"
                    final_error_message = (
                        error_message or "yt-dlp failed to download or video too short"
                    )
                    logging.warning(
                        f"❗ [discord] {final_error_message}: {url[:50]}..."
                    )
                    # Clean up failed download
                    if fs_path.exists():
                        try:
                            fs_path.unlink()
                        except Exception:
                            pass
                    return None, None, final_error_type, final_error_message

            else:
                # Direct video file - download it
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=90),
                    connector=aiohttp.TCPConnector(limit=5),
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
                    logging.info(
                        f"💾 [warm_cache] Cached video {url[:50]}... -> {fs_path} ({len(data)} bytes)"
                    )

                    # Try to get duration from downloaded file
                    duration = await get_video_duration_from_file(str(fs_path))
                    if duration is None:
                        # File is invalid (too short or corrupted), remove it
                        try:
                            fs_path.unlink()
                            logging.info(
                                f"🗑️ [video] Removed invalid downloaded video: {fs_path}"
                            )
                        except Exception:
                            pass
                        if attempt < max_retries - 1:
                            continue
                        return (
                            None,
                            None,
                            "video_too_short",
                            f"Video duration {duration}s is too short",
                        )
                    return f"/dvideos/{fname}", duration, None, None
                else:
                    logging.warning(f"❗ [discord] Empty video data for {url[:50]}...")
                    continue

        except asyncio.TimeoutError:
            logging.warning(
                f"⏱️ [discord] Timeout downloading video {url[:50]}... (attempt {attempt + 1})"
            )
            continue
        except Exception as e:
            logging.error(
                f"❗ [discord] Error caching video {url[:50]}... (attempt {attempt + 1}): {e}"
            )
            if attempt == max_retries - 1:  # Last attempt
                logging.error(
                    f"❗ [discord] Final failure caching video {url[:50]}...",
                    exc_info=True,
                )
            continue

    # Clean up partial download on final failure
    if fs_path.exists():
        try:
            fs_path.unlink()
            logging.debug(f"🧹 [discord] Cleaned up partial video file {fs_path}")
        except Exception:
            pass
    return None, None, "download_failed", "All download attempts failed"


async def cache_discord_meme(url: str) -> Optional[str]:
    """
    Download a meme/image URL into local cache and return a local HTTP path.

    - Files are stored under DISCORD_MEME_CACHE_DIR
    - Names are based on SHA256(url) + appropriate extension
    - Returns local path like /dmemes/<hashed>.<ext> that the overlay can use
    """
    if not url:
        return None

    DISCORD_MEME_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Stable name based on URL hash
    h = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]

    # Determine file extension from URL
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        path = parsed.path.lower()
        if path.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            ext = path[path.rfind(".") :]
        else:
            ext = ".png"  # Default fallback
    except:
        ext = ".png"

    fname = f"{h}{ext}"
    fs_path = DISCORD_MEME_CACHE_DIR / fname

    # Check for existing valid cached file
    if fs_path.exists() and fs_path.stat().st_size > 0:
        logging.debug(f"🎨 [meme] Using cached meme for {url[:50]}... -> {fs_path}")
        return f"/dmemes/{fname}"

    # Download the meme
    try:
        import aiohttp

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            connector=aiohttp.TCPConnector(limit=5),
        ) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    logging.warning(
                        f"❗ [meme] Failed to download {url[:50]}...: status={resp.status}"
                    )
                    return None

                content = await resp.read()
                if len(content) < 100:  # Too small to be a valid image
                    logging.warning(
                        f"❗ [meme] Downloaded content too small for {url[:50]}..."
                    )
                    return None

                fs_path.write_bytes(content)
                logging.info(
                    f"🎨 [meme] Downloaded {url[:50]}... -> {fs_path} (size={len(content)} bytes)"
                )
                return f"/dmemes/{fname}"

    except Exception as e:
        logging.warning(f"❗ [meme] Error downloading {url[:50]}...: {e}")
        # Clean up failed download
        if fs_path.exists():
            try:
                fs_path.unlink()
            except Exception:
                pass
        return None


async def video_has_audio(video_path: str) -> bool:
    """
    Check if a video file contains an audio track.
    Returns True if audio is present, False otherwise.
    """
    try:
        import subprocess

        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # If ffprobe finds audio streams, it will output "audio"
        return "audio" in result.stdout
    except Exception as e:
        logging.warning(f"❗ [audio_detect] Error checking audio in {video_path}: {e}")
        return False  # Assume no audio if detection fails


async def get_video_duration_from_file(file_path: str) -> Optional[float]:
    """
    Get duration from a local video file using ffprobe or similar.
    Returns None if the file is corrupted or unreadable, but accepts short durations for GIFs.
    Uses cache to avoid repeated ffprobe calls.
    """
    # Check cache first
    if file_path in video_duration_cache:
        logging.debug(
            f"✅ [video_duration] Using cached duration for {file_path}: {video_duration_cache[file_path]}s"
        )
        return video_duration_cache[file_path]

    logging.debug(f"🔍 [video_duration] Checking duration for file: {file_path}")
    try:
        # Try ffprobe first (more reliable for local files)
        import subprocess

        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        logging.debug(
            f"🔍 [video_duration] ffprobe result for {file_path}: ReturnCode={result.returncode}, Stdout='{result.stdout.strip()}', Stderr='{result.stderr.strip()}'"
        )

        if result.returncode == 0:
            duration_str = result.stdout.strip()
            if duration_str:
                duration = float(duration_str)
                if duration > 0:
                    logging.debug(
                        f"[video] Valid video duration: {file_path} ({duration}s)"
                    )
                    # Cache the result
                    video_duration_cache[file_path] = duration
                    return duration
                else:
                    logging.warning(
                        f"[video] Zero duration video detected by ffprobe: {file_path}"
                    )
                    return None
            else:
                logging.warning(
                    f"[video] ffprobe returned empty duration string for {file_path}"
                )
                return None
    except Exception as e:
        logging.warning(f"❗ [video_duration] ffprobe failed for {file_path}: {e}")
        pass  # Try yt-dlp fallback

    # Fallback: try yt-dlp on local file
    try:
        import yt_dlp  # type: ignore

        logging.debug(f"🔍 [video_duration] Falling back to yt-dlp for {file_path}")

        async def _get_duration_yt_dlp(path: str) -> Optional[float]:
            def _inner() -> Optional[float]:
                ydl_opts = {
                    "quiet": True,
                    "skip_download": True,
                    "no_warnings": True,
                    "extractor_args": {
                        "youtube": {
                            "player_client": ["web", "ios", "android_embedded"],
                            "skip": ["hls", "dash"],
                        }
                    },
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f"file://{path}", download=False)
                    dur = info.get("duration")
                    logging.debug(
                        f"🔍 [video_duration] yt-dlp info for {path}: Duration={dur}"
                    )
                    if dur is None:
                        logging.warning(
                            f"[video] yt-dlp found no duration metadata for {path}"
                        )
                        return None
                    try:
                        duration = float(dur)
                        if duration > 0:
                            logging.debug(
                                f"[video] Valid video duration (yt-dlp): {path} ({duration}s)"
                            )
                            return duration
                        else:
                            logging.warning(
                                f"[video] Zero duration video detected by yt-dlp: {path}"
                            )
                            return None
                    except Exception as e:
                        logging.warning(
                            f"❗ [video_duration] yt-dlp duration parse error for {path}: {e}"
                        )
                        return None

            return await asyncio.to_thread(_inner)

        duration = await _get_duration_yt_dlp(file_path)
        if duration is not None:
            # Cache the result
            video_duration_cache[file_path] = duration
        return duration
    except Exception as e:
        logging.warning(
            f"❗ [video_duration] yt-dlp fallback failed for {file_path}: {e}"
        )
        pass

    # If we can't determine duration, assume it's corrupted
    logging.warning(
        f"❗ [video] Could not determine duration for {file_path} - may be corrupted"
    )
    return None


async def get_audio_duration_from_file(file_path: str) -> Optional[float]:
    """
    Get duration from a local audio file using ffprobe.
    Returns None if the file is corrupted or unreadable.
    Uses cache to avoid repeated ffprobe calls.
    """
    # Check cache first
    if file_path in audio_duration_cache:
        logging.debug(
            f"✅ [audio_duration] Using cached duration for {file_path}: {audio_duration_cache[file_path]}s"
        )
        return audio_duration_cache[file_path]

    try:
        # Use ffprobe to get audio duration
        result = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "quiet",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await result.communicate()

        if result.returncode == 0 and stdout:
            duration_str = stdout.decode().strip()
            if duration_str:
                duration = float(duration_str)
                if duration > 0:
                    logging.debug(
                        f"[audio] Valid audio duration: {file_path} ({duration}s)"
                    )
                    # Cache the result
                    audio_duration_cache[file_path] = duration
                    return duration
                else:
                    logging.warning(f"[audio] Zero duration audio: {file_path}")
                    return None
    except Exception:
        pass

    logging.warning(
        f"❗ [audio] Could not determine duration for {file_path} - may be corrupted"
    )
    return None


# -----------------------------
# DISCORD SOUND SELECTION (Discord-only SFX)
# -----------------------------
async def fetch_random_discord_sound(
    action_key: str, project: Optional[str]
) -> Optional[str]:
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
        logging.debug(
            "[discord] Missing bot token or channel id; skipping sound fetch."
        )
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
        logging.info(
            "[discord] Message cache empty; doing one-time refresh before sound selection."
        )
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
                match_weight += (
                    count  # Sum all matching emoji reactions for voting weight
                )

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
                    logging.info(
                        f"[discord] (sound) Content audio candidate on {msg_id}: {p}"
                    )
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
) -> tuple[Optional[str], Optional[float]]:
    """
    Decide which media to use for a given action based on EMOJI VOTE WEIGHTS ONLY.

    Core principle: Only media with valid emoji votes can be selected.
    Selection is weighted by reaction counts (democratic voting system).

    Returns: (video_url, video_duration_seconds) - YouTube videos only
    """
    game_conf = GAMES_CONFIG.get(project_key, {})
    actions_map = game_conf.get("actions") or {}

    if action_key not in actions_map or action_key == "clear":
        logging.info(
            f"[media] No action mapping for {action_key} in project {project_key}"
        )
        return None, None

    # Get all media options with their emoji weights
    # SIMPLIFIED: Only process YouTube videos
    try:
        # Get only YouTube video results - skip all other media
        video_result = await get_cached_discord_video_with_weight(
            action_key, project=project_key
        )

        if not video_result or not video_result[0]:
            logging.info(f"[media] No YouTube videos found for action={action_key}")
            return None, None

        video_url, video_weight, video_duration, original_video_url = video_result

        # Only process if it's a YouTube video
        if not (original_video_url and YOUTUBE_RE.search(original_video_url)):
            logging.info(
                f"[media] No YouTube videos found for action={action_key} (skipping non-YouTube)"
            )
            return None, None

        logging.info(
            f"[media] youtube_video: {video_url} (weight={video_weight}, duration={video_duration}s)"
        )

    except Exception as e:
        logging.error(f"[media] Error getting YouTube videos for {action_key}: {e}")
        return None, None

    # Return YouTube video directly - no complex combinations needed
    logging.info(f"[media] SELECTED: youtube_video (weight={video_weight:.1f})")
    return video_url, video_duration


# -----------------------------
# FILES & TIMESTAMPS
# -----------------------------
def ensure_paths() -> None:
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    CHAPTER_DIR.mkdir(parents=True, exist_ok=True)
    DISCORD_SOUND_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DISCORD_VIDEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DISCORD_MEME_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    logging.info(f"📁 WATCH_DIR      = {WATCH_DIR.resolve()}")
    logging.info(f"📁 CHAPTER_DIR    = {CHAPTER_DIR.resolve()}")
    logging.info(f"📝 TEMPLATE_FILE  = {TEMPLATE_FILE.resolve()}")
    logging.info(f"🎮 DEFAULT_PROJECT_NAME = {DEFAULT_PROJECT_NAME}")
    logging.info(f"🎧 DISCORD_SOUND_CACHE_DIR = {DISCORD_SOUND_CACHE_DIR.resolve()}")
    logging.info(f"📹 DISCORD_VIDEO_CACHE_DIR = {DISCORD_VIDEO_CACHE_DIR.resolve()}")
    logging.info(f"🎨 DISCORD_MEME_CACHE_DIR = {DISCORD_MEME_CACHE_DIR.resolve()}")
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
        logging.error(
            f"❗ [chapter] Failed to create chapter file {path}: {e}", exc_info=True
        )


async def append_chapter_line(action: str, project: Optional[str]) -> None:
    """
    Append a line to the current chapter log file when an action arrives.
    Uses CURRENT_SESSION_PROJECT if available; otherwise, project/action is enough.
    """
    global current_chapter_file, session_start_wall, CURRENT_SESSION_PROJECT

    if current_chapter_file is None:
        logging.info(
            "⚠️ [chapter] No active chapter file; starting a session implicitly."
        )
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
        logging.info(
            f"⚠️ [run] end_run_for_project called but no active run for {project_key}"
        )
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
# UNDO HELPERS
# -----------------------------
def add_action_to_history(action: str, project_key: str) -> None:
    """
    Add an action to the undo history.
    """
    global action_history

    # Record the action for potential undo
    action_record = {
        "action": action,
        "project_key": project_key,
        "timestamp": time.time(),
        "original_count": action_counts.get((project_key, action.lower()), 0),
    }

    action_history.append(action_record)

    # Trim history to maximum size
    if len(action_history) > MAX_UNDO_HISTORY:
        action_history.pop(0)

    logging.info(
        f"📝 [undo] Added action to history: {action} for {project_key} (history size: {len(action_history)})"
    )


def reverse_run_event(project_key: str, action_key: str) -> None:
    """
    Reverse run stats for an undone action (opposite of register_run_event).
    """
    run_num = current_run_by_project.get(project_key)
    if not run_num:
        return  # no active run

    key = (project_key, run_num)
    stats = run_stats_by_project.get(key)
    if not stats:
        return

    # Decrement events count
    stats["events"] = max(0, stats.get("events", 0) - 1)

    ak = action_key.lower()

    # Reverse specific action stats
    if ak in RUN_KILL_ACTIONS:
        stats["kills"] = max(0, stats.get("kills", 0) - 1)
    if ak in RUN_DEATH_ACTIONS:
        stats["deaths"] = max(0, stats.get("deaths", 0) - 1)
    if ak == "headshot":
        stats["headshots"] = max(0, stats.get("headshots", 0) - 1)

    logging.info(
        f"↩️ [undo] Reversed run stats for action={action_key} in project={project_key}, run={run_num}"
    )


async def undo_last_action() -> bool:
    """
    Undo the last action in the history.
    Returns True if an action was undone, False if no actions to undo.
    """
    global action_history, action_counts, last_overlay_output, last_action, last_project

    if not action_history:
        logging.info("⚠️ [undo] No actions in history to undo")
        return False

    # Get the last action from history
    last_action_record = action_history.pop()
    action = last_action_record["action"]
    project_key = last_action_record["project_key"]
    original_count = last_action_record["original_count"]

    logging.info(f"↩️ [undo] Undoing last action: {action} for project {project_key}")

    # Reverse the action count
    count_key = (project_key, action.lower())
    current_count = action_counts.get(count_key, 0)

    if current_count > 0:
        new_count = current_count - 1
        if new_count == 0:
            # Remove the entry entirely if count reaches 0
            action_counts.pop(count_key, None)
        else:
            action_counts[count_key] = new_count

    # Reverse run stats if applicable
    if action.lower() not in ["clear", "start", "run_start", "run_end", "run_stop"]:
        reverse_run_event(project_key, action.lower())

    # Append undo entry to chapter file
    try:
        await append_chapter_line(f"UNDO: {action}", project_key)
    except Exception as e:
        logging.warning(f"Failed to append undo to chapter file: {e}")

    # Update overlay to show current state
    # Find the most recent action for this project to display
    most_recent_action = None
    most_recent_project = None

    # Look through action_counts to find what should be displayed
    for (proj, act), count in action_counts.items():
        if proj == project_key and count > 0:
            most_recent_action = act
            most_recent_project = proj
            break

    if most_recent_action and most_recent_project:
        # Update overlay with the current highest count action for this project
        await update_overlay_from_counts(most_recent_action, most_recent_project)
    else:
        # No actions left for this project, clear overlay
        async with state_lock:
            last_overlay_output = "Undone"
            last_action = "undo"
            last_project = project_key

        logging.info(
            f"🧽 [undo] No actions remaining for project {project_key}, showing 'Undone' message"
        )

    return True


async def update_overlay_from_counts(action_key: str, project_key: str) -> None:
    """
    Update overlay display based on current action counts (used by undo).
    """
    count_key = (project_key, action_key.lower())
    count = action_counts.get(count_key, 0)

    # Look up emoji for this game
    game_conf = GAMES_CONFIG.get(project_key, {})
    actions_map = game_conf.get("actions") or {}
    emoji = actions_map.get(action_key.lower(), "")

    output = f"{emoji} {action_key}".strip()
    if count > 1:
        output += f" x{count}"

    async with state_lock:
        global \
            last_overlay_output, \
            last_action, \
            last_project, \
            last_sound, \
            last_meme_url, \
            last_video_url, \
            last_video_duration, \
            last_audio_duration

        last_overlay_output = output
        last_action = action_key.lower()
        last_project = project_key

        # Clear media for undo - no need to replay media
        last_sound = None
        last_meme_url = None
        last_video_url = None
        last_video_duration = None
        last_audio_duration = None

    logging.info(
        f"🔄 [undo] Updated overlay from counts: {output} for project {project_key}"
    )


# -----------------------------
# ACHIEVEMENT NOTIFICATION HELPERS
# -----------------------------
async def display_achievement_notification(achievement_data: Dict[str, Any]) -> None:
    """
    Display a Steam achievement notification.
    """
    global current_achievement, achievement_display_until

    async with state_lock:
        current_achievement = achievement_data.copy()
        # Add sound URL for achievement notifications
        current_achievement["sound"] = "/sounds/achievement-unlocked-xbox.mp3"
        achievement_display_until = time.time() + ACHIEVEMENT_DISPLAY_DURATION

        logging.info(
            f"🏆 [achievement] Displaying notification: {achievement_data.get('achievement_title', 'Unknown')} from {achievement_data.get('game_name', 'Unknown Game')}"
        )

        # Auto-clear after duration
        asyncio.create_task(_auto_clear_achievement())


async def _auto_clear_achievement() -> None:
    """
    Clear achievement notification after display duration.
    """
    global current_achievement, achievement_display_until

    try:
        await asyncio.sleep(ACHIEVEMENT_DISPLAY_DURATION)

        async with state_lock:
            current_achievement = None
            achievement_display_until = None

        logging.info(
            f"🧽 [achievement] Auto-cleared notification after {ACHIEVEMENT_DISPLAY_DURATION}s"
        )

    except asyncio.CancelledError:
        logging.debug("⏳ [achievement] Auto-clear cancelled")
        return


# -----------------------------
# PLAYTIME NOTIFICATION HELPERS
# -----------------------------
async def display_playtime_notification(playtime_data: Dict[str, Any]) -> None:
    """
    Display a playtime notification for 5 minutes.
    """
    global current_playtime, playtime_display_until

    async with state_lock:
        current_playtime = playtime_data.copy()
        playtime_display_until = time.time() + PLAYTIME_DISPLAY_DURATION

        game_name = playtime_data.get("game_name", "Unknown Game")
        readable_time = playtime_data.get("total_playtime_readable", "Unknown")

        logging.info(
            f"⏰ [playtime] Displaying playtime: {readable_time} for {game_name}"
        )

        # Auto-clear after duration
        asyncio.create_task(_auto_clear_playtime())


async def _auto_clear_playtime() -> None:
    """
    Clear playtime notification after display duration.
    """
    global current_playtime, playtime_display_until

    try:
        await asyncio.sleep(PLAYTIME_DISPLAY_DURATION)

        async with state_lock:
            current_playtime = None
            playtime_display_until = None

        logging.info(
            f"🧽 [playtime] Auto-cleared notification after {PLAYTIME_DISPLAY_DURATION}s"
        )

    except asyncio.CancelledError:
        logging.debug("⏳ [playtime] Auto-clear cancelled")
        return


async def display_achievement_percentages(achievement_data: Dict[str, Any]) -> None:
    """
    Display achievement percentages notification for 30 seconds.
    """
    global current_achievement_percentages, achievement_percentages_display_until

    async with state_lock:
        current_achievement_percentages = achievement_data.copy()
        # Add sound to the notification
        current_achievement_percentages["sound"] = (
            "/sounds/achievement-unlocked-xbox.mp3"
        )
        achievement_percentages_display_until = (
            time.time() + ACHIEVEMENT_PERCENTAGES_DISPLAY_DURATION
        )

        # Log what we're displaying with full details
        game_name = achievement_data.get("game_name", "Unknown")
        achievements_list = achievement_data.get("achievements", [])
        
        logging.info(f"🏆 [achievement_percentages] Displaying {len(achievements_list)} achievements for {game_name}")
        for i, achievement in enumerate(achievements_list):
            name = achievement.get("display_name") or achievement.get("name") or "Unknown Achievement"
            percent = achievement.get("percent", 0)
            desc = achievement.get("description", "No description")
            logging.info(f"   {i+1}. {name} - {percent}% - {desc[:50]}{'...' if len(desc) > 50 else ''}")

        # Auto-clear after duration
        asyncio.create_task(_auto_clear_achievement_percentages())


async def _auto_clear_achievement_percentages() -> None:
    """
    Clear achievement percentages notification after display duration.
    """
    global current_achievement_percentages, achievement_percentages_display_until

    try:
        await asyncio.sleep(ACHIEVEMENT_PERCENTAGES_DISPLAY_DURATION)

        async with state_lock:
            current_achievement_percentages = None
            achievement_percentages_display_until = None

        logging.info(
            f"🧽 [achievement_percentages] Auto-cleared notification after {ACHIEVEMENT_PERCENTAGES_DISPLAY_DURATION}s"
        )

    except asyncio.CancelledError:
        logging.debug("⏳ [achievement_percentages] Auto-clear cancelled")
        return


def validate_achievement_data(data: Dict[str, Any]) -> bool:
    """
    Validate that achievement data contains required fields.
    """
    required_fields = [
        "achievement_title",
        "api_name",
        "description",
        "icon",
        "game_name",
        "app_id",
        "unlock_time",
        "steam_id",
    ]

    for field in required_fields:
        if field not in data:
            logging.warning(f"❌ [achievement] Missing required field: {field}")
            return False

    return True


# News notification globals
news_display_until = None
NEWS_DISPLAY_DURATION = 30  # 30 seconds like other notifications


async def display_news(news_data: Dict[str, Any]) -> None:
    """
    Display news notification at the bottom of the screen.
    """
    global current_news, news_display_until

    async with state_lock:
        current_news = news_data.copy()
        news_display_until = time.time() + NEWS_DISPLAY_DURATION

        game_name = news_data.get("game_name", "Unknown Game")
        item_count = len(news_data.get("news_items", []))

        logging.info(f"📰 [news] Displaying news: {item_count} items for {game_name}")

        # Auto-clear after duration
        asyncio.create_task(_auto_clear_news())


async def _auto_clear_news():
    """
    Clear news notification after display duration.
    """
    global current_news, news_display_until

    try:
        await asyncio.sleep(NEWS_DISPLAY_DURATION)

        async with state_lock:
            current_news = None
            news_display_until = None

        logging.info(
            f"🧽 [news] Auto-cleared notification after {NEWS_DISPLAY_DURATION}s"
        )

    except asyncio.CancelledError:
        logging.debug("⏳ [news] Auto-clear cancelled")
        return


# -----------------------------
# OVERLAY STATE
# -----------------------------
async def update_live_overlay(action: str, project_key: str) -> None:
    """
    Update the live overlay state (per project) exposed at /overlay.
    """
    global \
        overlay_clear_task, \
        last_overlay_output, \
        last_action, \
        last_sound, \
        last_meme_url, \
        last_video_url, \
        last_video_duration, \
        last_project, \
        run_panel_visible_until, \
        last_synonyms

    async with state_lock:
        if action.lower() == "clear":
            logging.info(
                "🧹 [overlay] CLEAR action received; resetting counts and run stats."
            )

            # Reset per-action overlay counts
            action_counts.clear()

            # Clear action history
            action_history.clear()

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
            last_synonyms = None
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

        # Add to undo history (only for actions that change counts, not special actions)
        if key not in ["clear", "undo"]:
            add_action_to_history(action, project_key)

        # look up emoji for this game
        game_conf = GAMES_CONFIG.get(project_key, {})
        actions_map = game_conf.get("actions") or {}
        emoji = actions_map.get(key, "")

        label = action
        output = f"{emoji} {label}".strip()
        if count > 1:
            output += f" x{count}"

        last_overlay_output = output
        last_action = key
        last_project = project_key

        # Generate synonyms for burst words
        last_synonyms = get_synonyms_for_action(key, count=15)

        # --- MEDIA PICKER: YouTube videos only ---
        video_url, video_duration = await pick_media_for_action(key, project_key)

        last_sound = ""  # No audio files
        last_meme_url = None  # No memes
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
                    calculated_audio_duration = await get_audio_duration_from_file(
                        str(audio_file_path)
                    )
                    if calculated_audio_duration:
                        logging.info(
                            f"🎵 [overlay] Audio duration detected: {calculated_audio_duration}s for {audio_filename}"
                        )
                except Exception as e:
                    logging.warning(
                        f"Failed to get audio duration for {audio_filename}: {e}"
                    )

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
    global \
        overlay_clear_task, \
        last_overlay_output, \
        last_action, \
        last_sound, \
        last_meme_url, \
        last_video_url, \
        last_video_duration, \
        last_audio_duration, \
        last_project

    try:
        clear_delay = None

        # Determine appropriate duration based on media combination
        if last_video_url and last_audio_duration:
            # Tenor video + Discord audio: use audio duration (audio controls the timing)
            clear_delay = last_audio_duration + 1.0
            logging.info(
                f"⏱️ [overlay] Tenor+Audio mode: Auto-clear scheduled after audio duration: {clear_delay}s"
            )
        elif last_video_url and last_video_duration:
            # YouTube video: use video duration (video controls the timing)
            clear_delay = last_video_duration + 1.0
            logging.info(
                f"⏱️ [overlay] YouTube mode: Auto-clear scheduled after video duration: {clear_delay}s"
            )
        elif last_audio_duration and (last_sound or last_meme_url):
            # GIF + Discord audio: use audio duration
            clear_delay = last_audio_duration + 1.0
            logging.info(
                f"⏱️ [overlay] GIF+Audio mode: Auto-clear scheduled after audio duration: {clear_delay}s"
            )
        else:
            # No timed media - don't auto-clear, let frontend handle it
            logging.info(
                f"⏱️ [overlay] No timed media detected - no auto-clear scheduled"
            )
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
            # DON'T reset last_project - it should persist to remember the active game
            # last_project = ""
        logging.info(f"🧽 [overlay] Auto-cleared after {clear_delay}s")

    except asyncio.CancelledError:
        logging.debug("⏳ [overlay] Auto-clear cancelled (new action received)")
        return


async def trigger_intro() -> None:
    """
    Trigger the Three.js intro animation.
    """
    global current_intro, intro_display_until
    
    async with state_lock:
        now = time.time()
        current_intro = {
            "trigger": True,
            "text": "The Cam Bros",
            "timestamp": now
        }
        intro_display_until = now + INTRO_DISPLAY_DURATION
    
    logging.info(f"🎬 [intro] Three.js intro triggered for {INTRO_DISPLAY_DURATION}s")


# -----------------------------
# ACTION HANDLING / TCP PARSE
# -----------------------------
async def handle_action(action: str, project: Optional[str]) -> None:
    """
    Handle a single parsed 'action' from TCP, with an optional game/project.
    """
    global last_overlay_output, last_action, last_project, last_sound, last_meme_url, last_video_url, last_video_duration, last_audio_duration
    
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

    # Update last_project with the current game
    async with state_lock:
        last_project = project_key

    logging.info(f"🎯 [handler] Received action={action} for project={project_key}")
    lower = action.lower()

    # ---- OBS Remote Control Actions ----
    if lower.startswith(("scene_", "transition_", "obs_")):
        try:
            from obs_controller import get_obs_controller, handle_obs_action
            
            obs_ctrl = await get_obs_controller()
            if obs_ctrl and obs_ctrl.connected:
                success = await handle_obs_action(lower, obs_ctrl)
                if success:
                    logging.info(f"✅ [obs] Action '{action}' executed")
                    # Update overlay without changing project
                    async with state_lock:
                        last_overlay_output = f"🎬 {action.replace('_', ' ').title()}"
                        last_action = action
                        # Don't change last_project - keep current game context
                else:
                    logging.warning(f"⚠️ [obs] Action '{action}' failed")
            else:
                logging.error("❌ [obs] OBS not connected")
        except Exception as e:
            logging.error(f"❌ [obs] Error: {e}", exc_info=True)
        return

    # ---- Global system action: Intro ----
    if lower == "intro":
        await trigger_intro()
        return

    # ---- Undo action ----
    if lower == "undo":
        success = await undo_last_action()
        if not success:
            # Show message that there's nothing to undo
            async with state_lock:
                last_overlay_output = "Nothing to undo"
                last_action = "undo"
                last_project = project_key
                last_sound = None
                last_meme_url = None
                last_video_url = None
                last_video_duration = None
                last_audio_duration = None
        return

    # ---- Run control actions ----
    if lower == "run_start":
        # If a run is already active for this project, end it first (split)
        if current_run_by_project.get(project_key):
            logging.info(
                f"[run] run_start received while run active; splitting run for {project_key}"
            )
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
            logging.info(
                f"[run] run_end received for {project_key} but no active run; ignoring."
            )
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


def extract_from_payload(text: str) -> tuple[Optional[str], list[str], bool]:
    """
    Extract project/game + one or more actions from the raw payload, and validate token.

    Supports lines like:
      token=secret_token
      game=hunt_showdown
      action=kill
      action=death

    And also bare actions like 'kill' if they exist in ANY game's actions.

    Returns: (project, actions, is_authorized)
    """
    project: Optional[str] = None
    actions: list[str] = []
    provided_token: Optional[str] = None

    # Precompute lowercase set for faster membership tests
    all_actions_lower = {a.lower() for a in ALL_ACTION_KEYS}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        logging.info(
            f"🔍 [parser] Checking line: {repr(line[:50])}{'...' if len(line) > 50 else ''}"
        )
        lower = line.lower()

        if lower.startswith("token="):
            provided_token = line.split("=", 1)[1].strip()
            logging.info("🔑 [parser] Token provided in TCP payload")
            continue

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
            logging.info(
                f"⚠️ [parser] Line did not match project/action/token format: {repr(line)}"
            )

    # Check authorization
    is_authorized = True
    if SS_TOKEN:  # If server requires token
        if not provided_token:
            logging.warning("🚫 [tcp] No token provided but SS_TOKEN is required")
            is_authorized = False
        elif provided_token != SS_TOKEN:
            logging.warning("🚫 [tcp] Invalid token provided")
            is_authorized = False
        else:
            logging.info("✅ [tcp] Token validated successfully")

    return project, actions, is_authorized


async def handle_client(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
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
        logging.info(f"📥 [tcp] Received {len(data)} bytes from {addr}")
        logging.debug(
            f"📥 [tcp] Raw payload text: {repr(text[:100])}{'...' if len(text) > 100 else ''}"
        )

        project, actions, is_authorized = extract_from_payload(text)

        if not is_authorized:
            logging.warning(f"🚫 [tcp] Unauthorized TCP request from {addr}")
            writer.close()
            await writer.wait_closed()
            return

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


# HTTP SERVER
# -----------------------------
async def handle_http(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    """
    Simple HTTP server:
      - GET /             => serves the HTML template
      - GET /overlay      => JSON with latest overlay text + action + sound + meme + project + runs + achievements + playtime + achievement_percentages
      - GET /config       => serves raw YAML config
      - POST /achievement => accepts Steam achievement notification data (requires auth)
      - POST /playtime    => accepts Steam playtime notification data (requires auth)
      - POST /global-achievement-percentages => accepts Steam achievement percentages data (requires auth)
      - POST /closest-achievements => alias for /global-achievement-percentages (requires auth)
      - POST /achievement-progress => alias for /global-achievement-percentages (requires auth)
      - POST /action      => accepts game action triggers (replaces TCP server, requires auth)
      - GET /sounds/<...> => serves local sound files from _data/sounds/
      - GET /dsounds/<...> => serves cached Discord audio files
      - GET /dvideos/<...> => serves cached Discord video files
      - GET /dmemes/<...>  => serves cached Discord meme/image files
    """
    addr = writer.get_extra_info("peername")
    # Declare global variables at function start to avoid scope issues
    global current_hotkey_mappings, last_hotkey_update, last_project

    try:
        # Read the request line and headers
        request_line = await reader.readline()
        if not request_line:
            writer.close()
            await writer.wait_closed()
            return

        req_text_parts = [request_line.decode("utf-8", errors="ignore").strip()]

        # Read headers until an empty line is found
        content_length = 0
        while True:
            header_line = await reader.readline()
            if not header_line or header_line.strip() == b"":
                break

            decoded_header = header_line.decode("utf-8", errors="ignore").strip()
            req_text_parts.append(decoded_header)

            if decoded_header.lower().startswith("content-length:"):
                try:
                    content_length = int(decoded_header.split(":", 1)[1].strip())
                except (ValueError, IndexError):
                    content_length = 0

        req_text = "\r\n".join(req_text_parts)  # Reconstruct full request header text

        first_line_parts = req_text_parts[0].split()
        method = first_line_parts[0] if len(first_line_parts) > 0 else "GET"
        raw_path = first_line_parts[1] if len(first_line_parts) > 1 else "/"

        path = raw_path.split("?", 1)[0]  # strip query params
        logging.debug(f"🌐 [http] {method} {path}")
        request_head = req_text  # The full headers are now the "request_head"
        # Verbose header logging removed - too noisy in production

        # Now read the body based on Content-Length
        body_data = b""
        if content_length > 0:
            logging.debug(
                f"🔍 [http_body] Reading {content_length} bytes for request body."
            )
            body_data = await reader.readexactly(content_length)
            logging.debug(
                f"🔍 [http_body] Read {len(body_data)} bytes for body (expected {content_length})."
            )

        # Now replace calls to _read_http_body with using body_data directly
        # The _read_http_body function itself will be removed later.
        # Selective authentication - only protect certain endpoints
        if requires_auth(path, method):
            if not check_auth_header(req_text):
                logging.warning(
                    f"🚫 [http] Unauthorized access attempt from {addr} to {method} {path}"
                )
                send_unauthorized(writer)
                await writer.drain()
                return
        else:
            logging.debug(f"🌍 [http] Public access: {method} {path}")

        # Handle POST /achievement endpoint
        if method == "POST" and path == "/achievement":
            try:
                # body_data is already available from the main http request parsing
                if not body_data:  # Already checks if body_data is empty
                    # Send error response
                    resp = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                    writer.write(resp)
                    await writer.drain()
                    return

                # Parse JSON
                achievement_data = json.loads(body_data.decode("utf-8"))

                # Validate data
                if not validate_achievement_data(achievement_data):
                    error_msg = '{"error":"Invalid data"}'
                    resp = f"HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: {len(error_msg)}\r\nConnection: close\r\n\r\n{error_msg}".encode()
                    writer.write(resp)
                    await writer.drain()
                    return

                # Display the achievement
                await display_achievement_notification(achievement_data)

                # Send success response
                response_body = json.dumps(
                    {"status": "success", "message": "Achievement displayed"}
                ).encode("utf-8")
                headers = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(response_body)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + response_body)
                await writer.drain()
                return

            except json.JSONDecodeError as e:
                logging.warning(f"❌ [achievement] Invalid JSON in POST body: {e}")
                error_msg = '{"error":"Invalid JSON"}'
                resp = f"HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: {len(error_msg)}\r\nConnection: close\r\n\r\n{error_msg}".encode()
                writer.write(resp)
                await writer.drain()
                return
            except Exception as e:
                logging.error(
                    f"❗ [achievement] Error processing achievement: {e}", exc_info=True
                )
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

        # Handle POST /playtime endpoint
        if method == "POST" and path == "/playtime":
            try:
                # body_data is already available from the main http request parsing
                if not body_data:
                    resp = b'HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: 29\r\nConnection: close\r\n\r\n{"error":"Request body is empty"}'
                    writer.write(resp)
                    await writer.drain()
                    return

                # Parse JSON
                playtime_data = json.loads(body_data.decode("utf-8"))

                # Validate required fields
                required_fields = [
                    "steam_id",
                    "app_id",
                    "game_name",
                    "total_playtime_minutes",
                    "total_playtime_hours",
                    "total_playtime_readable",
                    "timestamp",
                    "status",
                ]
                missing_fields = [
                    field for field in required_fields if field not in playtime_data
                ]

                if missing_fields:
                    logging.warning(
                        f"❌ [playtime] Missing required fields: {missing_fields}"
                    )
                    error_msg = f"Missing required fields: {', '.join(missing_fields)}"
                    response_body = json.dumps({"error": error_msg}).encode("utf-8")
                    resp_headers = (
                        "HTTP/1.1 400 Bad Request\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(response_body)}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    )
                    writer.write(resp_headers.encode("ascii") + response_body)
                    await writer.drain()
                    return

                # Display the playtime notification
                await display_playtime_notification(playtime_data)

                # Send success response
                response_body = json.dumps(
                    {"status": "success", "message": "Playtime displayed"}
                ).encode("utf-8")
                headers = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(response_body)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + response_body)
                await writer.drain()
                return

            except json.JSONDecodeError as e:
                logging.warning(f"❌ [playtime] Invalid JSON in POST body: {e}")
                resp = b'HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: 26\r\nConnection: close\r\n\r\n{"error":"Invalid JSON"}'
                writer.write(resp)
                await writer.drain()
                return
            except Exception as e:
                logging.error(
                    f"❗ [playtime] Error processing playtime: {e}", exc_info=True
                )
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

        # Handle POST /global-achievement-percentages endpoint
        if method == "POST" and path == "/global-achievement-percentages":
            try:
                # body_data is already available from the main http request parsing
                if not body_data:
                    resp = b'HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: 29\r\nConnection: close\r\n\r\n{"error":"Request body is empty"}'
                    writer.write(resp)
                    await writer.drain()
                    return

                # Parse JSON
                achievement_data = json.loads(body_data.decode("utf-8"))

                # Validate required top-level fields
                required_fields = ["game_name", "achievements"]
                missing_fields = [
                    field for field in required_fields if field not in achievement_data
                ]

                if missing_fields:
                    logging.warning(
                        f"❌ [achievement_percentages] Missing required fields: {missing_fields}"
                    )
                    error_msg = f"Missing required fields: {', '.join(missing_fields)}"
                    response_body = json.dumps({"error": error_msg}).encode("utf-8")
                    resp_headers = (
                        "HTTP/1.1 400 Bad Request\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(response_body)}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    )
                    writer.write(resp_headers.encode("ascii") + response_body)
                    await writer.drain()
                    return

                # Validate each achievement in the array - support multiple formats
                achievements_list = achievement_data["achievements"]
                normalized_achievements = []
                
                logging.info(f"[achievement_percentages] Normalizing {len(achievements_list)} achievements")
                
                for i, achievement in enumerate(achievements_list):
                    # Normalize the achievement data to standard format
                    normalized = {}
                    
                    # Handle different field names
                    # New format: achievement_title
                    # Old format: display_name or name
                    normalized["name"] = achievement.get("name") or achievement.get("achievement_title") or f"achievement_{i}"
                    normalized["display_name"] = achievement.get("display_name") or achievement.get("achievement_title") or achievement.get("name") or "Unknown Achievement"
                    normalized["description"] = achievement.get("description", "")
                    normalized["icon"] = achievement.get("icon", "")
                    
                    # Handle progress percentage
                    # New format: player_progress.progress_percent
                    # Old format: percent
                    if "player_progress" in achievement and achievement["player_progress"]:
                        progress = achievement["player_progress"]
                        normalized["percent"] = progress.get("progress_percent", 0)
                        logging.info(f"   [{i}] Using player_progress: {normalized['display_name']} = {normalized['percent']}%")
                    elif "percent" in achievement:
                        normalized["percent"] = achievement["percent"]
                        logging.info(f"   [{i}] Using percent field: {normalized['display_name']} = {normalized['percent']}%")
                    else:
                        # If no progress, treat as 0% or unlocked (100%)
                        normalized["percent"] = 100.0 if achievement.get("unlock_time") else 0.0
                        logging.info(f"   [{i}] No progress data, defaulting: {normalized['display_name']} = {normalized['percent']}%")
                    
                    normalized_achievements.append(normalized)
                
                # Replace original achievements with normalized ones
                achievement_data["achievements"] = normalized_achievements
                logging.info(f"[achievement_percentages] Normalization complete, displaying {len(normalized_achievements)} achievements")

                # Display the achievement percentages notification
                await display_achievement_percentages(achievement_data)

                # Send success response
                response_body = json.dumps(
                    {
                        "status": "success",
                        "message": "Achievement percentages displayed",
                    }
                ).encode("utf-8")
                headers = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(response_body)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + response_body)
                await writer.drain()
                return

            except json.JSONDecodeError as e:
                logging.warning(
                    f"❌ [achievement_percentages] Invalid JSON in POST body: {e}"
                )
                resp = b'HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: 26\r\nConnection: close\r\n\r\n{"error":"Invalid JSON"}'
                writer.write(resp)
                await writer.drain()
                return
            except Exception as e:
                logging.error(
                    f"❗ [achievement_percentages] Error processing achievement percentages: {e}",
                    exc_info=True,
                )
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

        # Handle POST /closest-achievements endpoint (alias for /global-achievement-percentages)
        if method == "POST" and path == "/closest-achievements":
            logging.info("[achievement_percentages] /closest-achievements endpoint hit (routing to global-achievement-percentages logic)")
            # Reuse the same logic as /global-achievement-percentages
            try:
                if not body_data:
                    resp = b'HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: 29\r\nConnection: close\r\n\r\n{"error":"Request body is empty"}'
                    writer.write(resp)
                    await writer.drain()
                    return

                achievement_data = json.loads(body_data.decode("utf-8"))
                await display_achievement_percentages(achievement_data)

                response_body = json.dumps({"status": "success", "message": "Closest achievements displayed"}).encode("utf-8")
                headers = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(response_body)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + response_body)
                await writer.drain()
                return

            except Exception as e:
                logging.error(f"❗ [achievement_percentages] Error processing closest achievements: {e}", exc_info=True)
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

        # Handle POST /achievement-progress endpoint (alias for /global-achievement-percentages)
        if method == "POST" and path == "/achievement-progress":
            logging.info("[achievement_percentages] /achievement-progress endpoint hit (routing to global-achievement-percentages logic)")
            # Reuse the same logic as /global-achievement-percentages
            try:
                if not body_data:
                    resp = b'HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: 29\r\nConnection: close\r\n\r\n{"error":"Request body is empty"}'
                    writer.write(resp)
                    await writer.drain()
                    return

                achievement_data = json.loads(body_data.decode("utf-8"))
                await display_achievement_percentages(achievement_data)

                response_body = json.dumps({"status": "success", "message": "Achievement progress displayed"}).encode("utf-8")
                headers = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(response_body)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + response_body)
                await writer.drain()
                return

            except Exception as e:
                logging.error(f"❗ [achievement_percentages] Error processing achievement progress: {e}", exc_info=True)
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

        # Handle POST /clear-achievements endpoint (manual clear for stuck achievements)
        if method == "POST" and path == "/clear-achievements":
            logging.info("[achievement_percentages] Manual clear endpoint hit")
            try:
                async with state_lock:
                    global current_achievement_percentages, achievement_percentages_display_until
                    current_achievement_percentages = None
                    achievement_percentages_display_until = None
                
                logging.info("🧽 [achievement_percentages] Manually cleared via /clear-achievements endpoint")
                
                response_body = json.dumps({"status": "success", "message": "Achievement percentages cleared"}).encode("utf-8")
                headers = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(response_body)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + response_body)
                await writer.drain()
                return

            except Exception as e:
                logging.error(f"❗ [achievement_percentages] Error clearing achievements: {e}", exc_info=True)
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

        # Handle POST /news endpoint
        if method == "POST" and path == "/news":
            try:
                # body_data is already available from the main http request parsing
                if not body_data:
                    resp = b'HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: 29\r\nConnection: close\r\n\r\n{"error":"Request body is empty"}'
                    writer.write(resp)
                    await writer.drain()
                    return

                # Parse JSON
                news_data = json.loads(body_data.decode("utf-8"))

                logging.info("📰 [news] News endpoint called")

                # Validate auth token
                if not check_auth_header(req_text):
                    logging.warning("❌ [news] Unauthorized request")
                    error_msg = "Unauthorized"
                    response_body = json.dumps({"error": error_msg}).encode("utf-8")
                    resp_headers = (
                        "HTTP/1.1 401 Unauthorized\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(response_body)}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    )
                    writer.write(resp_headers.encode("ascii") + response_body)
                    await writer.drain()
                    return

                # Log the received data
                logging.info(
                    f"📰 [news] Received news data: {json.dumps(news_data, indent=2)}"
                )

                # Validate required fields
                required_fields = [
                    "steam_id",
                    "app_id",
                    "game_name",
                    "news_items",
                    "timestamp",
                    "timestamp_iso",
                    "new_items_count",
                    "total_items_fetched",
                ]
                missing_fields = [
                    field for field in required_fields if field not in news_data
                ]

                if missing_fields:
                    logging.warning(
                        f"❌ [news] Missing required fields: {missing_fields}"
                    )
                    error_msg = f"Missing required fields: {', '.join(missing_fields)}"
                    response_body = json.dumps({"error": error_msg}).encode("utf-8")
                    resp_headers = (
                        "HTTP/1.1 400 Bad Request\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(response_body)}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    )
                    writer.write(resp_headers.encode("ascii") + response_body)
                    await writer.drain()
                    return

                # Validate each news item in the array
                news_list = news_data["news_items"]
                for i, news_item in enumerate(news_list):
                    required_news_fields = [
                        "gid",
                        "title",
                        "url",
                        "author",
                        "contents",
                        "feedlabel",
                        "date",
                        "feedname",
                        "feed_type",
                        "appid",
                    ]
                    missing_news_fields = [
                        field
                        for field in required_news_fields
                        if field not in news_item
                    ]

                    if missing_news_fields:
                        logging.warning(
                            f"❌ [news] News item {i}: Missing required fields: {missing_news_fields}"
                        )
                        error_msg = f"News item {i}: Missing required fields: {', '.join(missing_news_fields)}"
                        response_body = json.dumps({"error": error_msg}).encode("utf-8")
                        resp_headers = (
                            "HTTP/1.1 400 Bad Request\r\n"
                            "Content-Type: application/json\r\n"
                            f"Content-Length: {len(response_body)}\r\n"
                            "Connection: close\r\n"
                            "\r\n"
                        )
                        writer.write(resp_headers.encode("ascii") + response_body)
                        await writer.drain()
                        return

                # Display the news notification
                await display_news(news_data)

                # Send success response
                response_body = json.dumps(
                    {"status": "success", "message": "News displayed"}
                ).encode("utf-8")
                headers = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(response_body)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + response_body)
                await writer.drain()
                return

            except json.JSONDecodeError as e:
                logging.warning(f"❌ [news] Invalid JSON in POST body: {e}")
                resp = b'HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: 26\r\nConnection: close\r\n\r\n{"error":"Invalid JSON"}'
                writer.write(resp)
                await writer.drain()
                return
            except Exception as e:
                logging.error(f"❗ [news] Error processing news: {e}", exc_info=True)
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

        # Handle POST /subscribe-cta endpoint
        if method == "POST" and path == "/subscribe-cta":
            global current_subscribe_cta, subscribe_cta_display_until, last_subscribe_cta_time
            try:
                # Trigger subscribe CTA
                async with state_lock:
                    now = time.time()
                    current_subscribe_cta = {"trigger": True}
                    subscribe_cta_display_until = now + SUBSCRIBE_CTA_DURATION
                    last_subscribe_cta_time = now
                
                logging.info(f"[cta] 🔔 Subscribe CTA triggered via POST endpoint")
                
                # Send success response
                response_body = json.dumps(
                    {"status": "success", "message": "Subscribe CTA triggered"}
                ).encode("utf-8")
                headers = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(response_body)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + response_body)
                await writer.drain()
                return
            except Exception as e:
                logging.error(f"❗ [cta] Error triggering subscribe CTA: {e}", exc_info=True)
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

        # Handle POST /merch-cta endpoint
        if method == "POST" and path == "/merch-cta":
            global current_merch_cta, merch_cta_display_until, last_merch_cta_time
            try:
                # Trigger merch CTA
                async with state_lock:
                    now = time.time()
                    current_merch_cta = {"trigger": True}
                    merch_cta_display_until = now + MERCH_CTA_DURATION
                    last_merch_cta_time = now
                
                logging.info(f"[cta] 🛍️ Merch CTA triggered via POST endpoint")
                
                # Send success response
                response_body = json.dumps(
                    {"status": "success", "message": "Merch CTA triggered"}
                ).encode("utf-8")
                headers = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(response_body)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + response_body)
                await writer.drain()
                return
            except Exception as e:
                logging.error(f"❗ [cta] Error triggering merch CTA: {e}", exc_info=True)
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

        # Handle POST /hotkeys endpoint (hotkey mapping updates)
        if method == "POST" and path == "/hotkeys":
            global current_hotkey_mappings, last_hotkey_update
            logging.info("[hotkeys] POST /hotkeys endpoint hit")
            try:
                # body_data is already available from the main http request parsing
                if body_data:  # Already checks if body_data is not empty
                    body_str = body_data.decode("utf-8")

                    try:
                        hotkey_data = json.loads(body_str)

                        # Update global hotkey mappings
                        current_hotkey_mappings = hotkey_data.get("mappings", {})
                        last_hotkey_update = time.time()

                        logging.info(
                            f"[hotkeys] Updated hotkey mappings: {len(current_hotkey_mappings)} actions"
                        )

                        response_data = {
                            "status": "success",
                            "message": "Hotkey mappings updated",
                        }
                        body_bytes = json.dumps(response_data).encode("utf-8")
                        resp = (
                            "HTTP/1.1 200 OK\r\n"
                            "Content-Type: application/json\r\n"
                            "Content-Length: " + str(len(body_bytes)) + "\r\n"
                            "Access-Control-Allow-Origin: *\r\n"
                            "Access-Control-Allow-Methods: POST, OPTIONS\r\n"
                            "Access-Control-Allow-Headers: Content-Type, Authorization\r\n"
                            "Connection: close\r\n"
                            "\r\n"
                        ).encode("ascii") + body_bytes

                        writer.write(resp)
                        await writer.drain()
                        return

                    except json.JSONDecodeError:
                        resp = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                        writer.write(resp)
                        await writer.drain()
                        return
                else:
                    resp = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                    writer.write(resp)
                    await writer.drain()
                    return

            except Exception as e:
                logging.error(
                    f"❗ [http] Error in hotkeys endpoint: {e}", exc_info=True
                )
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

        # Handle GET /hotkeys endpoint (get current hotkey mappings)
        elif method == "GET" and path == "/hotkeys":
            try:
                response_data = {
                    "mappings": current_hotkey_mappings,
                    "last_updated": last_hotkey_update,
                    "status": "success",
                }

                body_bytes = json.dumps(response_data).encode("utf-8")
                resp = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    "Content-Length: " + str(len(body_bytes)) + "\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
                    "Access-Control-Allow-Headers: Content-Type, Authorization\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                ).encode("ascii") + body_bytes

                writer.write(resp)
                await writer.drain()
                return

            except Exception as e:
                logging.error(
                    f"❗ [http] Error in GET hotkeys endpoint: {e}", exc_info=True
                )
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

        # Handle OPTIONS for CORS preflight
        if method == "OPTIONS":
            if path == "/auth" or path == "/action" or path == "/hotkeys":
                resp = (
                    "HTTP/1.1 200 OK\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
                    "Access-Control-Allow-Headers: Content-Type, Authorization\r\n"
                    "Content-Length: 0\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                ).encode("ascii")
                writer.write(resp)
                await writer.drain()
                return

        # Handle POST /auth endpoint (token validation)
        if method == "POST" and path == "/auth":
            try:
                # body_data is already available from the main http request parsing
                if body_data:
                    body_str = body_data.decode("utf-8")
                    try:
                        data = json.loads(body_str)
                        provided_token = data.get("token", "").strip()

                        # Debug logging
                        logging.info(
                            f"[auth] Provided token: '{provided_token}' (len={len(provided_token)})"
                        )
                        logging.info(
                            f"[auth] Server SS_TOKEN: '{SS_TOKEN}' (len={len(SS_TOKEN) if SS_TOKEN else 0})"
                        )
                        logging.info(
                            f"[auth] Tokens match: {provided_token == SS_TOKEN}"
                        )

                        # Validate token
                        if not SS_TOKEN:
                            # If no token is configured, allow access
                            response_data = {
                                "valid": True,
                                "message": "No authentication required",
                            }
                        elif provided_token == SS_TOKEN:
                            response_data = {"valid": True, "message": "Token valid"}
                        else:
                            response_data = {"valid": False, "message": "Invalid token"}

                        body_bytes = json.dumps(response_data).encode("utf-8")
                        resp = (
                            "HTTP/1.1 200 OK\r\n"
                            "Content-Type: application/json\r\n"
                            "Content-Length: " + str(len(body_bytes)) + "\r\n"
                            "Access-Control-Allow-Origin: *\r\n"
                            "Access-Control-Allow-Methods: POST, OPTIONS\r\n"
                            "Access-Control-Allow-Headers: Content-Type\r\n"
                            "Connection: close\r\n"
                            "\r\n"
                        ).encode("ascii") + body_bytes

                        writer.write(resp)
                        await writer.drain()
                        return

                    except json.JSONDecodeError:
                        resp = b'HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: 26\r\nConnection: close\r\n\r\n{"error":"Invalid JSON"}'
                        writer.write(resp)
                        await writer.drain()
                        return
                else:
                    resp = b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                    writer.write(resp)
                    await writer.drain()
                    return

            except Exception as e:
                logging.error(f"❗ [http] Error in auth endpoint: {e}", exc_info=True)
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

        # Handle POST /action endpoint (replaces TCP server)
        if method == "POST" and path == "/action":
            try:
                # body_data is already available from the main http request parsing
                body_str = body_data.decode(
                    "utf-8", errors="ignore"
                )  # Decode body once

                if (
                    not body_str.strip()
                ):  # Check if the decoded string is empty or just whitespace
                    resp = b'HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: 38\r\nConnection: close\r\n\r\n{"error":"Request body is empty or malformed"}'
                    writer.write(resp)
                    await writer.drain()
                    return

                # Parse JSON
                logging.debug(
                    f"🔍 [action] Raw body_str for JSON parsing: '{body_str}'"
                )
                action_data = json.loads(body_str)

                # Extract required fields
                game = action_data.get("game", action_data.get("project"))
                action = action_data.get("action")

                if not action:
                    logging.warning(f"❌ [action] Missing required field: action")
                    error_msg = "Missing required field: action"
                    response_body = json.dumps({"error": error_msg}).encode("utf-8")
                    resp_headers = (
                        "HTTP/1.1 400 Bad Request\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(response_body)}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    )
                    writer.write(resp_headers.encode("ascii") + response_body)
                    await writer.drain()
                    return

                # Validate action exists in config (allow OBS actions dynamically)
                action_lower = action.lower()
                is_obs_action = action_lower.startswith(("scene_", "transition_", "obs_"))
                is_valid_action = action_lower in {a.lower() for a in ALL_ACTION_KEYS} or is_obs_action
                
                if not is_valid_action:
                    logging.warning(f"❌ [action] Unknown action: {action}")
                    error_msg = f"Unknown action: {action}. Valid actions: {', '.join(sorted(ALL_ACTION_KEYS))}"
                    response_body = json.dumps({"error": error_msg}).encode("utf-8")
                    resp_headers = (
                        "HTTP/1.1 400 Bad Request\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(response_body)}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    )
                    writer.write(resp_headers.encode("ascii") + response_body)
                    await writer.drain()
                    return

                # Process the action
                await handle_action(action, game)

                # Get updated action count for live UI updates
                try:
                    count_key = (game, action.lower())
                    current_count = action_counts.get(count_key, 0)
                except Exception as e:
                    logging.warning(f"Error getting action count: {e}")
                    current_count = 0

                # Check if this was a clear or undo action - need to send all counts
                action_lower = action.lower()
                all_counts = None
                if action_lower in ('clear', 'undo'):
                    # Return all current counts so UI can update everything
                    all_counts = {}
                    async with state_lock:
                        for (g, a), cnt in action_counts.items():
                            key = f"{g}::{a}"
                            all_counts[key] = cnt

                # Send success response
                response_data = {
                    "success": True,
                    "status": "success",
                    "message": f"Action '{action}' processed successfully",
                    "game": game,
                    "action": action,
                    "new_count": current_count,
                }
                
                # Include all counts if this was clear/undo
                if all_counts is not None:
                    response_data["all_counts"] = all_counts
                
                response_body = json.dumps(response_data).encode("utf-8")

                headers = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(response_body)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + response_body)
                await writer.drain()
                return

            except json.JSONDecodeError as e:
                logging.warning(f"❌ [action] Invalid JSON in POST body: {e}")
                resp = b'HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: 26\r\nConnection: close\r\n\r\n{"error":"Invalid JSON"}'
                writer.write(resp)
                await writer.drain()
                return
            except Exception as e:
                logging.error(
                    f"❗ [action] Error processing action: {e}", exc_info=True
                )
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

        if path.startswith("/overlay"):
            async with state_lock:
                text = last_overlay_output or ""
                action = last_action or ""
                sound = last_sound or ""
                meme = last_meme_url or ""
                video = last_video_url or ""
                video_duration = (
                    last_video_duration if last_video_duration is not None else 0.0
                )
                audio_duration = (
                    last_audio_duration if last_audio_duration is not None else 0.0
                )
                project = last_project or ""
                synonyms = last_synonyms or []

                # DEBUG: Log audio duration value when API is called
                # logging.info(f"🔍 [overlay] API call - last_audio_duration={last_audio_duration}, final_audio_duration={audio_duration}")

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

                # ---- Build achievement notification data ----
                achievement_notification = None
                if current_achievement and achievement_display_until:
                    if now < achievement_display_until:
                        achievement_notification = current_achievement.copy()
                        # Add remaining display time for frontend timing
                        achievement_notification["remaining_time"] = max(
                            0.0, achievement_display_until - now
                        )

                # ---- Build playtime notification data ----
                playtime_notification = None
                if current_playtime and playtime_display_until:
                    if now < playtime_display_until:
                        playtime_notification = current_playtime.copy()
                        # Add remaining display time for frontend timing
                        playtime_notification["remaining_time"] = max(
                            0.0, playtime_display_until - now
                        )
                        # Add sound for frontend
                        playtime_notification["sound"] = "/sounds/ticking-clock.mp3"

                # ---- Build achievement percentages notification data ----
                achievement_percentages_notification = None
                if (
                    current_achievement_percentages
                    and achievement_percentages_display_until
                ):
                    if now < achievement_percentages_display_until:
                        achievement_percentages_notification = (
                            current_achievement_percentages.copy()
                        )
                        # Add remaining display time for frontend timing
                        remaining_time = max(
                            0.0, achievement_percentages_display_until - now
                        )

                        if isinstance(achievement_percentages_notification, list):
                            # For list of achievements, add remaining_time to each item
                            for achievement in achievement_percentages_notification:
                                achievement["remaining_time"] = remaining_time
                        else:
                            # For single achievement, add directly
                            achievement_percentages_notification["remaining_time"] = (
                                remaining_time
                            )
                        # Add sound for frontend
                        achievement_percentages_notification["sound"] = (
                            "/sounds/achievements-progress.mp3"
                        )

                # ---- Build news notification data ----
                news_notification = None
                if current_news and news_display_until:
                    if now < news_display_until:
                        news_notification = current_news.copy()
                        # Add remaining display time for frontend timing
                        news_notification["remaining_time"] = (
                            max(0.0, news_display_until - now) * 1000
                        )  # Convert to milliseconds
                        # Add sound for frontend
                        news_notification["sound"] = "/sounds/news.mp3"

                # ---- Build subscribe CTA notification data ----
                subscribe_cta_notification = None
                if current_subscribe_cta and subscribe_cta_display_until:
                    if now < subscribe_cta_display_until:
                        subscribe_cta_notification = {"trigger": True}

                # ---- Build merch CTA notification data ----
                merch_cta_notification = None
                if current_merch_cta and merch_cta_display_until:
                    if now < merch_cta_display_until:
                        merch_cta_notification = {"trigger": True}

                # ---- Build intro notification data ----
                intro_notification = None
                if current_intro and intro_display_until:
                    if now < intro_display_until:
                        intro_notification = current_intro.copy()
                        intro_notification["remaining_time"] = max(
                            0.0, intro_display_until - now
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
                "synonyms": synonyms,
                "runs": runs_for_overlay,
                "achievement": achievement_notification,
                "playtime": playtime_notification,
                "achievement_percentages": achievement_percentages_notification,
                "news": news_notification,
                "subscribe_cta": subscribe_cta_notification,
                "merch_cta": merch_cta_notification,
                "intro": intro_notification,
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

        elif path == "/obs/actions":
            # Return dynamic OBS actions
            try:
                from obs_controller import get_obs_controller
                
                obs_ctrl = await get_obs_controller()
                if obs_ctrl and obs_ctrl.connected:
                    # Refresh OBS state
                    await obs_ctrl.refresh_state()
                    obs_actions = obs_ctrl.get_dynamic_actions()
                    
                    response_body = json.dumps(obs_actions, indent=2).encode("utf-8")
                    resp_headers = (
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(response_body)}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    )
                    writer.write(resp_headers.encode("ascii") + response_body)
                    await writer.drain()
                else:
                    response_body = b'{"error":"OBS not connected"}'
                    resp_headers = (
                        "HTTP/1.1 503 Service Unavailable\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(response_body)}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    )
                    writer.write(resp_headers.encode("ascii") + response_body)
                    await writer.drain()
            except Exception as e:
                logging.error(f"Error getting OBS actions: {e}")
                response_body = json.dumps({"error": str(e)}).encode("utf-8")
                resp_headers = (
                    "HTTP/1.1 500 Internal Server Error\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(response_body)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(resp_headers.encode("ascii") + response_body)
                await writer.drain()
            return

        elif path == "/config":
            # Serve the raw YAML config
            try:
                body_str = CONFIG_PATH.read_text(encoding="utf-8")
            except Exception as e:
                logging.error(
                    f"❗ [http] Failed to read CONFIG YAML: {e}", exc_info=True
                )
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

        elif path == "/ui":
            # Serve UI with all data embedded - single endpoint for everything
            try:
                # Get OBS actions if available
                obs_actions = {}
                try:
                    from obs_controller import get_obs_controller
                    obs_ctrl = await get_obs_controller()
                    if obs_ctrl and obs_ctrl.connected:
                        await obs_ctrl.refresh_state()
                        obs_actions = obs_ctrl.get_dynamic_actions()
                        total_actions = sum(len(group) for group in obs_actions.values() if isinstance(group, dict))
                        logging.info(f"[ui] Loaded {total_actions} OBS actions in {len(obs_actions)} groups: {list(obs_actions.keys())}")
                        logging.info(f"[ui] OBS scenes: {len(obs_ctrl.scenes)}, transitions: {len(obs_ctrl.transitions)}")
                    else:
                        logging.info("[ui] OBS not connected")
                except ImportError:
                    logging.debug("[ui] obs_controller module not available")
                except Exception as e:
                    logging.warning(f"[ui] OBS connection failed: {e}", exc_info=True)
                
                # Get current game - try to detect from OBS scene if not set
                current_game = last_project
                if not current_game and obs_actions:
                    # Try to detect game from current scene name
                    current_scene = obs_actions.get('current_scene', {}).get('display', '')
                    for game_key in GAMES_CONFIG.keys():
                        if game_key.lower() in current_scene.lower():
                            current_game = game_key
                            last_project = game_key  # Set it globally so it persists
                            logging.info(f"[ui] Auto-detected game '{current_game}' from scene '{current_scene}'")
                            break
                
                # Embed the full games config so UI can access all game actions
                games_config_for_ui = {}
                for game_key, game_data in GAMES_CONFIG.items():
                    games_config_for_ui[game_key] = {
                        "emoji": game_data.get("emoji", "🎮"),
                        "actions": game_data.get("actions", {})
                    }
                
                # Load UI template
                template_path = "/app/ui_driver_template.html"
                with open(template_path, "r", encoding="utf-8") as f:
                    body_str = f.read()
                
                # Get action counts for display
                action_counts_for_ui = {}
                async with state_lock:
                    for (game, action), count in action_counts.items():
                        key = f"{game}::{action}"
                        action_counts_for_ui[key] = count
                
                # Embed all data as JSON in the HTML
                obs_actions_json = json.dumps(obs_actions)
                games_config_json = json.dumps(games_config_for_ui)
                current_game_json = json.dumps(current_game or "")
                action_counts_json = json.dumps(action_counts_for_ui)
                
                # Replace placeholder data in the template
                body_str = body_str.replace(
                    'window.EMBEDDED_OBS_ACTIONS = {};',
                    f'window.EMBEDDED_OBS_ACTIONS = {obs_actions_json};'
                )
                body_str = body_str.replace(
                    'window.EMBEDDED_GAMES_CONFIG = {};',
                    f'window.EMBEDDED_GAMES_CONFIG = {games_config_json};'
                )
                body_str = body_str.replace(
                    'window.EMBEDDED_CURRENT_GAME = "";',
                    f'window.EMBEDDED_CURRENT_GAME = {current_game_json};'
                )
                body_str = body_str.replace(
                    'window.EMBEDDED_ACTION_COUNTS = {};',
                    f'window.EMBEDDED_ACTION_COUNTS = {action_counts_json};'
                )
                
                logging.info(f"[ui] Loaded UI template from {template_path} - game={current_game}, {len(obs_actions)} OBS actions")
            except Exception as e:
                logging.error(f"❗ [http] Failed to load UI: {e}", exc_info=True)
                body_str = f"<!DOCTYPE html><html><body><h1>Error loading UI</h1><p>{e}</p></body></html>"

            body_bytes = body_str.encode("utf-8")
            headers = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
                "Cache-Control: no-cache, no-store, must-revalidate\r\n"
                "Pragma: no-cache\r\n"
                "Expires: 0\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            writer.write(headers.encode("ascii") + body_bytes)
            await writer.drain()

        elif path == "/obs_state" and method == "GET":
            # Return current OBS state for UI updates
            try:
                # Check authentication
                is_authenticated = check_auth_header(req_text)
                if not is_authenticated:
                    body_bytes = json.dumps({"error": "Authentication required"}).encode("utf-8")
                    headers_str = (
                        "HTTP/1.1 401 Unauthorized\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(body_bytes)}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    )
                    writer.write(headers_str.encode("ascii") + body_bytes)
                    await writer.drain()
                    return
                
                # Get fresh OBS state
                obs_actions = {}
                current_scene = ""
                current_transition = ""
                is_recording = False
                is_streaming = False
                try:
                    from obs_controller import get_obs_controller
                    obs_ctrl = await get_obs_controller()
                    if obs_ctrl and obs_ctrl.connected:
                        await obs_ctrl.refresh_state()
                        obs_actions = obs_ctrl.get_dynamic_actions()
                        current_scene = obs_ctrl.current_scene
                        current_transition = obs_ctrl.current_transition
                        is_recording = obs_ctrl.is_recording
                        is_streaming = obs_ctrl.is_streaming
                except Exception as e:
                    logging.debug(f"[obs_state] Could not fetch OBS state: {e}")
                
                body_bytes = json.dumps({
                    "obs_actions": obs_actions,
                    "current_scene": current_scene,
                    "current_transition": current_transition,
                    "is_recording": is_recording,
                    "is_streaming": is_streaming
                }).encode("utf-8")
                headers_str = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(body_bytes)}\r\n"
                    "Cache-Control: no-cache\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers_str.encode("ascii") + body_bytes)
                await writer.drain()
                return
            except Exception as e:
                logging.error(f"[obs_state] Error: {e}", exc_info=True)
                body_bytes = json.dumps({"error": str(e)}).encode("utf-8")
                headers_str = (
                    "HTTP/1.1 500 Internal Server Error\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(body_bytes)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers_str.encode("ascii") + body_bytes)
                await writer.drain()
                return

        elif path == "/set_game" and method == "POST":
            # Set the current game manually via dropdown selection
            try:
                # Check authentication using existing auth function
                is_authenticated = check_auth_header(req_text)

                if not is_authenticated:
                    response_data = {
                        "success": False,
                        "error": "Authentication required",
                    }
                    body_bytes = json.dumps(response_data).encode("utf-8")
                    headers_str = (
                        "HTTP/1.1 401 Unauthorized\r\n"
                        "Content-Type: application/json\r\n"
                        f"Content-Length: {len(body_bytes)}\r\n"
                        "Connection: close\r\n"
                        "\r\n"
                    )
                    writer.write(headers_str.encode("ascii") + body_bytes)
                    await writer.drain()
                    return

                body = await reader.read(4096)
                data = json.loads(body.decode("utf-8"))
                selected_game = data.get("game", "")

                if selected_game in GAMES_CONFIG:
                    # Update the current project
                    async with state_lock:
                        last_project = selected_game

                    logging.info(f"🎮 [ui] Manual game selection: {selected_game}")

                    response_data = {
                        "success": True,
                        "game": selected_game,
                        "message": f"Game changed to {selected_game}",
                    }
                else:
                    response_data = {
                        "success": False,
                        "error": f"Unknown game: {selected_game}",
                        "available_games": list(GAMES_CONFIG.keys()),
                    }

                body_bytes = json.dumps(response_data).encode("utf-8")
                headers = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(body_bytes)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + body_bytes)
                await writer.drain()

            except Exception as e:
                logging.error(f"❗ [http] Error in set_game: {e}", exc_info=True)
                error_response = {"success": False, "error": str(e)}
                body_bytes = json.dumps(error_response).encode("utf-8")
                headers = (
                    "HTTP/1.1 500 Internal Server Error\r\n"
                    "Content-Type: application/json\r\n"
                    f"Content-Length: {len(body_bytes)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + body_bytes)
                await writer.drain()

        elif path.startswith("/refresh_discord"):
            # Manual Discord cache refresh endpoint
            try:
                logging.info("🔄 [debug] Manual Discord cache refresh triggered")
                await refresh_discord_messages_cache()

                total_messages = len(discord_messages_cache)
                game_counts = {
                    game: len(msgs) for game, msgs in discord_game_caches.items()
                }

                debug_info = {
                    "success": True,
                    "total_messages": total_messages,
                    "game_caches": game_counts,
                    "hunt_showdown_messages": game_counts.get("hunt_showdown", 0),
                    "message": "Discord cache refreshed successfully",
                }

                body_bytes = json.dumps(debug_info, indent=2).encode("utf-8")
                headers = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json; charset=utf-8\r\n"
                    f"Content-Length: {len(body_bytes)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + body_bytes)
                await writer.drain()
                return

            except Exception as e:
                logging.error(
                    f"❗ [debug] Error refreshing Discord cache: {e}", exc_info=True
                )
                error_body = json.dumps({"error": str(e)}).encode("utf-8")
                headers = (
                    "HTTP/1.1 500 Internal Server Error\r\n"
                    "Content-Type: application/json; charset=utf-8\r\n"
                    f"Content-Length: {len(error_body)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + error_body)
                await writer.drain()
                return

        elif path.startswith("/debug_video_lookup"):
            # DEBUG ENDPOINT: Test video lookup for specific game/action
            try:
                from urllib.parse import urlparse, parse_qs

                parsed_url = urlparse(raw_path)
                query_params = parse_qs(parsed_url.query)

                action = query_params.get("action", ["kill"])[0]
                project = query_params.get("project", ["hunt_showdown"])[0]

                logging.info(
                    f"🔍 [debug] Testing video lookup for action={action} project={project}"
                )

                # Use our fixed video lookup
                video_result = await get_cached_discord_video_with_weight(
                    action, project
                )
                video_url, weight, duration, original_url = video_result

                debug_info = {
                    "action": action,
                    "project": project,
                    "video_found": video_url is not None,
                    "video_url": video_url,
                    "weight": weight,
                    "duration": duration,
                    "original_url": original_url,
                    "cache_directories_checked": [
                        str(DISCORD_VIDEO_CACHE_DIR),
                        *[str(d) for d in ALTERNATIVE_VIDEO_CACHE_DIRS],
                    ],
                }

                # Also check how many total videos are in cache
                total_cached = 0
                for cache_dir in [
                    DISCORD_VIDEO_CACHE_DIR
                ] + ALTERNATIVE_VIDEO_CACHE_DIRS:
                    if cache_dir.exists():
                        mp4_count = len(list(cache_dir.glob("*.mp4")))
                        debug_info[f"videos_in_{cache_dir.name}"] = mp4_count
                        total_cached += mp4_count

                debug_info["total_cached_videos"] = total_cached

                body_bytes = json.dumps(debug_info, indent=2).encode("utf-8")
                headers = (
                    "HTTP/1.1 200 OK\r\n"
                    "Content-Type: application/json; charset=utf-8\r\n"
                    f"Content-Length: {len(body_bytes)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + body_bytes)
                await writer.drain()
                return

            except Exception as e:
                logging.error(
                    f"❗ [debug] Error in video lookup test: {e}", exc_info=True
                )
                error_body = json.dumps({"error": str(e)}).encode("utf-8")
                headers = (
                    "HTTP/1.1 500 Internal Server Error\r\n"
                    "Content-Type: application/json; charset=utf-8\r\n"
                    f"Content-Length: {len(error_body)}\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                )
                writer.write(headers.encode("ascii") + error_body)
                await writer.drain()
                return

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
                        result = subprocess.run(
                            [
                                "ffprobe",
                                "-v",
                                "quiet",
                                "-show_entries",
                                "format=duration",
                                "-of",
                                "default=noprint_wrappers=1:nokey=1",
                                str(video_file),
                            ],
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )

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
                        "runs": [],
                    }

                    body_bytes = json.dumps(debug_response).encode("utf-8")
                else:
                    body_bytes = json.dumps({"error": "No cached videos found"}).encode(
                        "utf-8"
                    )

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
            rel = path[len("/dsounds/") :].lstrip("/")
            fs_path = (DISCORD_SOUND_CACHE_DIR / rel).resolve()

            # Security: ensure it's inside DISCORD_SOUND_CACHE_DIR
            try:
                fs_path.relative_to(DISCORD_SOUND_CACHE_DIR.resolve())
            except ValueError:
                logging.warning(
                    f"🚫 [http] Attempted path escape for dsounds: {fs_path}"
                )
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
                logging.error(
                    f"❗ [http] Failed to read cached sound file {fs_path}: {e}",
                    exc_info=True,
                )
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
            rel = path[len("/dvideos/") :].lstrip("/")

            # Use fallback mechanism to find the video file
            fs_path = find_cached_video_file(rel)
            if not fs_path:
                logging.warning(f"❓ [http] Cached video not found anywhere: {rel}")
                resp = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

            # Security check: ensure the file is inside one of the allowed cache directories
            is_safe = False
            for safe_dir in [DISCORD_VIDEO_CACHE_DIR] + ALTERNATIVE_VIDEO_CACHE_DIRS:
                try:
                    fs_path.resolve().relative_to(safe_dir.resolve())
                    is_safe = True
                    break
                except (ValueError, OSError):
                    continue

            if not is_safe:
                logging.warning(
                    f"🚫 [http] Video file outside safe directories: {fs_path}"
                )
                resp = b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

            try:
                body_bytes = fs_path.read_bytes()
                mime, _ = mimetypes.guess_type(fs_path.name)
                mime = mime or "video/mp4"
            except Exception as e:
                logging.error(
                    f"❗ [http] Failed to read cached video file {fs_path}: {e}",
                    exc_info=True,
                )
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

        elif path.startswith("/dmemes/"):
            # Static served cached Discord memes
            rel = path[len("/dmemes/") :].lstrip("/")
            fs_path = (DISCORD_MEME_CACHE_DIR / rel).resolve()

            # Security: ensure it's inside DISCORD_MEME_CACHE_DIR
            try:
                fs_path.relative_to(DISCORD_MEME_CACHE_DIR.resolve())
            except ValueError:
                logging.warning(
                    f"🚫 [http] Attempted path escape for dmemes: {fs_path}"
                )
                resp = b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

            if not fs_path.exists() or not fs_path.is_file():
                logging.warning(f"❓ [http] Cached meme not found: {fs_path}")
                resp = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

            try:
                body_bytes = fs_path.read_bytes()
                mime, _ = mimetypes.guess_type(fs_path.name)
                mime = mime or "image/png"
            except Exception as e:
                logging.error(
                    f"❗ [http] Failed to read cached meme file {fs_path}: {e}",
                    exc_info=True,
                )
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

        elif path.startswith("/sounds/"):
            # Static served local sound files
            import os.path

            rel = path[len("/sounds/") :].lstrip("/")
            sounds_dir = "/sounds"
            fs_path = os.path.join(sounds_dir, rel)

            # Security: ensure it's inside sounds directory
            if not os.path.abspath(fs_path).startswith(os.path.abspath(sounds_dir)):
                logging.warning(
                    f"🚫 [http] Attempted path escape for sounds: {fs_path}"
                )
                resp = b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

            if not os.path.exists(fs_path):
                logging.warning(f"⚠️ [http] Sound file not found: {fs_path}")
                resp = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

            # Determine MIME type
            if fs_path.endswith(".mp3"):
                mime = "audio/mpeg"
            elif fs_path.endswith(".wav"):
                mime = "audio/wav"
            elif fs_path.endswith(".ogg"):
                mime = "audio/ogg"
            elif fs_path.endswith(".m4a"):
                mime = "audio/mp4"
            else:
                mime = "audio/mpeg"  # Default fallback

            try:
                with open(fs_path, "rb") as f:
                    body_bytes = f.read()
            except Exception as e:
                logging.error(
                    f"❗ [http] Failed to read sound file {fs_path}: {e}", exc_info=True
                )
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

        elif path.startswith("/fonts/"):
            # Serve font files from _data/fonts/
            rel = path[len("/fonts/"):].lstrip("/")
            from pathlib import Path as PathLib
            fonts_dir = PathLib("/app/_data/fonts")
            fs_path = (fonts_dir / rel).resolve()

            # Security: ensure it's inside fonts directory
            try:
                fs_path.relative_to(fonts_dir.resolve())
            except ValueError:
                logging.warning(f"🚫 [http] Attempted path escape for fonts: {fs_path}")
                resp = b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

            if not fs_path.exists() or not fs_path.is_file():
                logging.warning(f"❓ [http] Font file not found: {fs_path}")
                resp = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

            try:
                body_bytes = fs_path.read_bytes()
                # Determine MIME type based on font extension
                ext = fs_path.suffix.lower()
                if ext == ".ttf":
                    mime = "font/ttf"
                elif ext == ".otf":
                    mime = "font/otf"
                elif ext == ".woff":
                    mime = "font/woff"
                elif ext == ".woff2":
                    mime = "font/woff2"
                else:
                    mime = "application/octet-stream"
            except Exception as e:
                logging.error(f"❗ [http] Failed to read font file {fs_path}: {e}", exc_info=True)
                resp = b"HTTP/1.1 500 Internal Server Error\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                writer.write(resp)
                await writer.drain()
                return

            headers = (
                "HTTP/1.1 200 OK\r\n"
                f"Content-Type: {mime}\r\n"
                f"Content-Length: {len(body_bytes)}\r\n"
                "Cache-Control: public, max-age=31536000\r\n"  # Cache fonts for 1 year
                "Access-Control-Allow-Origin: *\r\n"
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
                    logging.warning(
                        "⚠️ TEMPLATE_FILE missing; using bare fallback HTML."
                    )
                    body_str = "<html><body>Socket Sentinel Overlay</body></html>"
            except Exception as e:
                logging.error(
                    f"❗ [http] Failed to read TEMPLATE_FILE: {e}", exc_info=True
                )
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
async def obs_state_poller():
    """
    Background task that polls OBS state every 2 seconds to keep it in sync.
    """
    await asyncio.sleep(5)  # Wait for OBS to connect
    logging.info("[obs] OBS state poller started")
    
    while True:
        try:
            from obs_controller import get_obs_controller
            obs_ctrl = await get_obs_controller()
            if obs_ctrl and obs_ctrl.connected:
                await obs_ctrl.refresh_state()
            await asyncio.sleep(2)  # Poll every 2 seconds
        except Exception as e:
            logging.debug(f"[obs] State poll error: {e}")
            await asyncio.sleep(5)


async def cta_scheduler_task() -> None:
    """
    Background task that triggers Subscribe and Merch CTAs on schedule.
    Runs continuously and triggers CTAs at specified intervals.
    """
    global current_subscribe_cta, subscribe_cta_display_until, last_subscribe_cta_time
    global current_merch_cta, merch_cta_display_until, last_merch_cta_time
    
    # Wait a bit after startup before first CTA
    await asyncio.sleep(60)  # Wait 1 minute after startup
    
    logging.info("[cta] CTA scheduler started - Subscribe: every 15min, Merch: every 22min")
    
    while True:
        try:
            now = time.time()
            
            # Check if we should trigger Subscribe CTA
            if now - last_subscribe_cta_time >= SUBSCRIBE_CTA_INTERVAL:
                async with state_lock:
                    current_subscribe_cta = {"trigger": True}
                    subscribe_cta_display_until = now + SUBSCRIBE_CTA_DURATION
                    last_subscribe_cta_time = now
                logging.info(f"[cta] 🔔 Triggered Subscribe CTA (will display for {SUBSCRIBE_CTA_DURATION}s)")
            
            # Check if we should trigger Merch CTA
            # Add collision detection - don't show if subscribe CTA just triggered
            time_since_subscribe = now - last_subscribe_cta_time
            if now - last_merch_cta_time >= MERCH_CTA_INTERVAL:
                # Avoid overlap: if subscribe CTA triggered in last 2 minutes, wait 3 more minutes
                if time_since_subscribe < 120:  # Within 2 minutes
                    logging.info(f"[cta] 🛍️ Merch CTA delayed to avoid overlap with Subscribe CTA")
                    await asyncio.sleep(180)  # Wait 3 more minutes
                    now = time.time()  # Update time after delay
                
                async with state_lock:
                    current_merch_cta = {"trigger": True}
                    merch_cta_display_until = now + MERCH_CTA_DURATION
                    last_merch_cta_time = now
                logging.info(f"[cta] 🛍️ Triggered Merch CTA (will display for {MERCH_CTA_DURATION}s)")
            
            # Sleep for 30 seconds before checking again
            await asyncio.sleep(30)
            
        except Exception as e:
            logging.error(f"[cta] Error in CTA scheduler: {e}", exc_info=True)
            await asyncio.sleep(60)  # Wait a bit before retrying on error


async def main() -> None:
    global last_project
    
    # Load YAML config (required) before anything else
    load_overlay_config()
    
    # Initialize last_project with DEFAULT_PROJECT_NAME so UI shows game on first load
    last_project = DEFAULT_PROJECT_NAME
    logging.info(f"🎮 Initial game set to: {last_project}")

    ensure_paths()
    logging.info("🚀 obs-socket-sentinel starting up...")

    # Security configuration logging
    if SS_TOKEN:
        logging.info(
            f"🔐 Security: Token authentication ENABLED (token length: {len(SS_TOKEN)})"
        )
        logging.info(f"🔐 Security: Token starts with: '{SS_TOKEN[:10]}...'")
    else:
        logging.warning(
            "⚠️ Security: Token authentication DISABLED - set SS_TOKEN for security!"
        )

    # ---- Discord cache bootstrap ----
    if DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID:
        logging.info(
            "[discord] Bot token + channel id present; building initial meme/sound cache..."
        )

        # Load failed videos list before warm caching
        await load_failed_videos()

        asyncio.create_task(refresh_discord_messages_cache())
        # Warm cache ALL media files on startup for instant playback
        logging.info("[warm_cache] Starting initial warm cache of all media...")
        asyncio.create_task(warm_cache_all_media())
        # Start periodic background refresh (every 10 minutes) which includes warm caching
        asyncio.create_task(discord_cache_refresher_task(interval_seconds=600))
        # Start cache cleanup task
        asyncio.create_task(cache_cleanup_task())
    else:
        logging.info(
            "[discord] Bot token or channel id missing; meme/sound cache disabled."
        )
    
    # ---- Start CTA scheduler ----
    logging.info("[cta] Starting CTA scheduler task...")
    asyncio.create_task(cta_scheduler_task())
    
    # ---- Start OBS state poller ----
    logging.info("[obs] Starting OBS state poller task...")
    asyncio.create_task(obs_state_poller())

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
