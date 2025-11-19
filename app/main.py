#!/usr/bin/env python3
from pathlib import Path
import asyncio
import unicodedata
import json
import logging
import mimetypes
import os
import random
import time
from typing import Dict, List, Any, Optional

import aiohttp  # make sure this is installed in the container
import yaml     # pip install pyyaml
import hashlib  # for stable cache filenames

# -----------------------------
# CONFIG / GLOBALS
# -----------------------------
OVERLAY_DISPLAY_SECONDS = 7

# Task reference so we can cancel/replace timers
overlay_clear_task: Optional[asyncio.Task] = None

# Global references for overlay media
last_sound: Optional[str] = None        # URL string for sound (Discord cached)
last_meme_url: Optional[str] = None     # URL string for meme image/gif (Discord)

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

# Discord sound file cache (ephemeral)
DISCORD_SOUND_CACHE_DIR = Path(
    os.getenv("DISCORD_SOUND_CACHE_DIR", "/tmp/discord_sounds")
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

# Discord meme/sound cache
discord_messages_cache: List[dict] = []         # all messages from channel
discord_game_caches: Dict[str, List[dict]] = {} # per-game filtered messages
discord_cache_lock = asyncio.Lock()             # to avoid concurrent rebuilds

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


async def discord_cache_refresher_task(interval_seconds: int = 600) -> None:
    """
    Background task that periodically rebuilds the Discord message cache.
    Default: every 600 seconds (10 minutes).
    """
    while True:
        try:
            await refresh_discord_messages_cache()
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
                match_weight = max(match_weight, count)

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
            return url

    chosen = random.choice(list(weighted_candidates.keys()))
    logging.info(
        f"🖼️ [discord] Fallback selected cached meme URL for project={project} "
        f"action={action_key}: {chosen}"
    )
    return chosen


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

    # If already cached, just reuse
    if fs_path.exists():
        logging.debug(f"🔊 [discord] Using cached audio for {url} -> {fs_path}")
        return f"/dsounds/{fname}"

    # Download and cache
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logging.warning(
                        f"❗ [discord] Failed to download audio {url}: "
                        f"status={resp.status}, body={text[:200]!r}"
                    )
                    return None
                data = await resp.read()
        fs_path.write_bytes(data)
        logging.info(f"💾 [discord] Cached audio {url} -> {fs_path}")
        return f"/dsounds/{fname}"
    except Exception as e:
        logging.error(f"❗ [discord] Error caching audio {url}: {e}", exc_info=True)
        return None


# -----------------------------
# DISCORD SOUND SELECTION (Discord-only SFX)
# -----------------------------
async def fetch_random_discord_sound(action_key: str, project: Optional[str]) -> Optional[str]:
    """
    Choose a random sound (audio URL) for the given action from the cached
    Discord messages, then download & cache it locally and return a /dsounds/ URL.

    Requirements for a message to qualify:
      - It must have a reaction that matches the *action emoji* for this action
        under the given project (using config.games[project].actions[action_key]).
      - It must contain at least one audio-ish attachment / embed / link.

    NOTE: Unlike memes, this does NOT require a game emoji (GAME_EMOJI_MAP).
          Sounds are global per-action and are only keyed by the action emoji.
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

    if not discord_messages_cache:
        logging.info("[discord] Still no cached messages; cannot select sound.")
        return None

    logging.info(
        f"[discord] Selecting sound from {len(discord_messages_cache)} cached messages for "
        f"action={action_key}, emoji={target_emoji!r} (project={project})"
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

    # We scan all messages, independent of GAME_EMOJI_MAP, and look for the action emoji.
    for msg in discord_messages_cache:
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
                match_weight = max(match_weight, count)

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
# FILES & TIMESTAMPS
# -----------------------------
def ensure_paths() -> None:
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    CHAPTER_DIR.mkdir(parents=True, exist_ok=True)
    DISCORD_SOUND_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    logging.info(f"📁 WATCH_DIR      = {WATCH_DIR.resolve()}")
    logging.info(f"📁 CHAPTER_DIR    = {CHAPTER_DIR.resolve()}")
    logging.info(f"📝 TEMPLATE_FILE  = {TEMPLATE_FILE.resolve()}")
    logging.info(f"🎮 DEFAULT_PROJECT_NAME = {DEFAULT_PROJECT_NAME}")
    logging.info(f"🎧 DISCORD_SOUND_CACHE_DIR = {DISCORD_SOUND_CACHE_DIR.resolve()}")


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
# OVERLAY STATE
# -----------------------------
async def update_live_overlay(action: str, project_key: str) -> None:
    """
    Update the live overlay state (per project) exposed at /overlay.
    """
    global overlay_clear_task, last_overlay_output, last_action, last_sound, last_meme_url, last_project

    async with state_lock:
        if action.lower() == "clear":
            logging.info("🧹 [overlay] CLEAR action received; resetting counts.")
            action_counts.clear()
            last_overlay_output = ""
            last_action = ""
            last_sound = None
            last_meme_url = None
            last_project = ""
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

        # --- SOUNDS: Discord-only, cached locally ---
        last_sound = await fetch_random_discord_sound(key, project=project_key)

        # --- MEMES: project-scoped as before ---
        if key in actions_map and key != "clear":
            last_meme_url = await fetch_random_discord_meme(key, project=project_key)
        else:
            last_meme_url = None

        codepoints = " ".join(f"U+{ord(ch):04X}" for ch in output)
        logging.info(
            f"🖨️ [overlay] New overlay text: {output} [{codepoints}] "
            f"project={project_key} action={last_action} sound={last_sound} meme={last_meme_url}"
        )

        if overlay_clear_task and not overlay_clear_task.done():
            overlay_clear_task.cancel()

        overlay_clear_task = asyncio.create_task(_auto_clear_overlay())


async def _auto_clear_overlay() -> None:
    """
    Clears overlay after a short delay.
    """
    global last_overlay_output, last_action, last_sound, last_meme_url, last_project
    try:
        await asyncio.sleep(OVERLAY_DISPLAY_SECONDS)

        async with state_lock:
            last_overlay_output = ""
            last_action = ""
            last_sound = None
            last_meme_url = None
            last_project = ""
        logging.info(f"🧽 [overlay] Auto-cleared after {OVERLAY_DISPLAY_SECONDS}s")

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

    # When a recording/stream starts, rotate to a new chapter file
    if lower == "start":
        await start_new_chapter_session(project_key)

    if lower != "clear":
        await append_chapter_line(action, project_key)

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
      - GET /overlay      => JSON with latest overlay text + action + sound + meme + project
      - GET /config       => serves raw YAML config
      - GET /dsounds/<...> => serves cached Discord audio files
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
                project = last_project or ""
            body_obj = {
                "text": text,
                "action": action,
                "sound": sound,
                "meme": meme,
                "project": project,
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
        # Start periodic background refresh (every 10 minutes)
        asyncio.create_task(discord_cache_refresher_task(interval_seconds=600))
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

