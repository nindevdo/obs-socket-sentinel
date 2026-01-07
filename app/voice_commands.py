#!/usr/bin/env python3
"""
Voice Command Processing for Socket Sentinel
Converts speech to text and maps to actions
"""

import logging
import re
from typing import Optional, Dict, Tuple

logger = logging.getLogger(__name__)

class VoiceCommandParser:
    """Parse voice commands and map to Socket Sentinel actions and OBS scenes"""
    
    def __init__(self, games_config: Dict):
        self.games_config = games_config
        self.scenes_list = []  # Will be updated dynamically from OBS
        
        # Build action mappings with synonyms for all game actions
        self.action_synonyms = {
            # Combat actions
            "kill": ["kill", "killed", "eliminated", "frag", "takedown", "got him", "got her", "enemy down"],
            "death": ["death", "died", "dead", "killed me", "i died", "rip", "im dead"],
            "downed": ["down", "downed", "knocked", "knocked down", "dbno"],
            "headshot": ["headshot", "head shot", "dome", "domed", "hs"],
            "melee": ["melee", "melee kill", "sword", "axe", "stabbed"],
            "traded": ["trade", "traded", "mutual kill"],
            "assist": ["assist", "assisted", "help", "helped"],
            
            # Area/status actions
            "clear": ["clear", "cleared", "safe", "all clear", "area clear"],
            "alert": ["alert", "alerted", "spotted", "they see us"],
            "stealth": ["stealth", "sneaking", "quiet", "stay quiet"],
            
            # Mission/run actions
            "run_start": ["start run", "begin run", "new run", "start game", "lets go", "starting"],
            "run_end": ["end run", "finish run", "game over", "run complete", "finished"],
            "extract": ["extract", "extracted", "extraction", "evac", "evacuate", "exfil"],
            "banish": ["banish", "banished", "banishing", "ritual"],
            
            # Support actions
            "revive": ["revive", "revived", "rez", "rezzed", "bring back", "res"],
            
            # Resource/environment actions
            "loot": ["loot", "looting", "looted", "found loot"],
            "mining": ["mining", "mine", "mined", "digging"],
            "fish": ["fish", "fishing", "caught fish"],
            "drowned": ["drowned", "drowning", "water death"],
            "teleport": ["teleport", "teleported", "tp", "portal"],
            
            # Combat effects
            "explosion": ["explosion", "exploded", "boom", "grenade", "explosive"],
            "fire": ["fire", "burning", "burned", "flame"],
            "magic": ["magic", "spell", "cast"],
            "trap": ["trap", "trapped", "tripwire"],
            
            # Enemy types (Hell Divers 2)
            "bots": ["bots", "bot", "robots", "automaton"],
            "squids": ["squids", "squid", "illuminate"],
            "terminids": ["terminids", "terminid", "bugs", "bug"],
            
            # Difficulty/player types
            "veterans": ["veterans", "veteran", "vet", "experienced"],
            "rookies": ["rookies", "rookie", "newbie", "new player"],
            
            # Misc
            "funny": ["funny", "lol", "hilarious", "laugh"],
            "intro": ["intro", "introduction", "show intro"],
        }
        
        # Common scene switching trigger words
        self.scene_triggers = [
            "switch to", "show", "go to", "scene", "display", "change to"
        ]
        
    def update_scenes(self, scenes: list):
        """Update the available scenes list from OBS"""
        self.scenes_list = scenes
        logger.debug(f"[voice] Updated scenes list: {len(scenes)} scenes available")
    
    def normalize_scene_name(self, name: str) -> str:
        """Normalize scene name for matching (lowercase, remove special chars)"""
        # Remove common prefixes/suffixes
        normalized = name.lower()
        normalized = re.sub(r'[#\-_]+', ' ', normalized)  # Replace separators with space
        normalized = re.sub(r'\s+', ' ', normalized).strip()  # Clean up spaces
        return normalized
    
    def match_scene(self, text: str) -> Optional[str]:
        """
        Try to match voice input to an OBS scene name
        
        Args:
            text: Transcribed speech text (already lowercased)
            
        Returns:
            Exact scene name if matched, None otherwise
        """
        if not self.scenes_list:
            return None
        
        # Remove common trigger words from the text
        cleaned_text = text
        for trigger in self.scene_triggers:
            cleaned_text = cleaned_text.replace(trigger, "").strip()
        
        # Try exact match first (normalized)
        cleaned_normalized = self.normalize_scene_name(cleaned_text)
        
        for scene in self.scenes_list:
            scene_name = scene.get('sceneName', '')
            scene_normalized = self.normalize_scene_name(scene_name)
            
            # Exact normalized match
            if cleaned_normalized == scene_normalized:
                logger.info(f"[voice] 🎬 Exact scene match: '{scene_name}'")
                return scene_name
            
            # Partial match (scene name contains the text or vice versa)
            if cleaned_normalized in scene_normalized or scene_normalized in cleaned_normalized:
                # Must be at least 3 characters to avoid false positives
                if len(cleaned_normalized) >= 3:
                    logger.info(f"[voice] 🎬 Partial scene match: '{scene_name}' (from '{cleaned_text}')")
                    return scene_name
        
        # Try word-by-word matching for multi-word scenes
        text_words = set(cleaned_normalized.split())
        if len(text_words) > 0:
            best_match = None
            best_match_score = 0
            
            for scene in self.scenes_list:
                scene_name = scene.get('sceneName', '')
                scene_normalized = self.normalize_scene_name(scene_name)
                scene_words = set(scene_normalized.split())
                
                # Count matching words
                matching_words = text_words & scene_words
                if len(matching_words) > best_match_score:
                    best_match_score = len(matching_words)
                    best_match = scene_name
            
            # If we matched at least 2 words or 1 word with 4+ chars
            if best_match_score >= 2 or (best_match_score == 1 and len(next(iter(text_words))) >= 4):
                logger.info(f"[voice] 🎬 Word-match scene: '{best_match}' ({best_match_score} words)")
                return best_match
        
        return None
    
    def match_thanks(self, text: str) -> Optional[str]:
        """
        Match thank you commands and extract name if present
        
        Args:
            text: Transcribed speech text (already lowercased)
            
        Returns:
            Name to thank (or empty string for generic thanks)
        """
        # Thank you trigger words
        thanks_triggers = [
            "thanks", "thank you", "shoutout", "shout out", 
            "appreciate", "props to", "props"
        ]
        
        # Check if any trigger is in the text
        triggered = False
        for trigger in thanks_triggers:
            if trigger in text:
                triggered = True
                # Remove the trigger to extract the name
                text = text.replace(trigger, "").strip()
                break
        
        if not triggered:
            return None
        
        # Clean up common filler words
        fillers = ["to", "for", "the", "a", "an"]
        words = text.split()
        name_words = [w for w in words if w not in fillers and len(w) > 1]
        
        if name_words:
            # Join remaining words as the name (capitalize each word)
            name = " ".join(name_words).title()
            logger.info(f"[voice] 🙏 Thanks command with name: '{name}'")
            return name
        else:
            # Generic thanks (no name)
            logger.info(f"[voice] 🙏 Generic thanks command")
            return ""
        
    def parse_command(self, text: str, current_game: Optional[str] = None) -> Optional[Tuple[str, str]]:
        """
        Parse voice command text and return (game, action) tuple or special commands
        
        Args:
            text: Transcribed speech text
            current_game: Currently selected game (for context)
            
        Returns:
            (game, action) tuple for game actions
            ('scene', scene_name) tuple for scene switching
            ('thanks', name) tuple for thank you animations
            None if no match
        """
        text = text.lower().strip()
        logger.info(f"[voice] Parsing command: '{text}' (current_game={current_game})")
        
        # Check for thank you commands
        thanks_match = self.match_thanks(text)
        if thanks_match:
            return ('thanks', thanks_match)
        
        # Check if this is a scene switching command
        scene_match = self.match_scene(text)
        if scene_match:
            return ('scene', scene_match)
        
        # Try to extract game and action from text
        detected_game = current_game
        detected_action = None
        
        # Check if a specific game is mentioned
        for game_key in self.games_config.keys():
            game_name = game_key.replace("_", " ")
            if game_name in text or game_key in text:
                detected_game = game_key
                logger.info(f"[voice] Detected game: {detected_game}")
                break
        
        # Try to match action synonyms
        for action, synonyms in self.action_synonyms.items():
            for synonym in synonyms:
                if synonym in text:
                    # Check if this action exists for the detected game
                    if detected_game and action in self.games_config.get(detected_game, {}).get("actions", {}):
                        detected_action = action
                        logger.info(f"[voice] Matched action: {detected_action} (synonym: '{synonym}')")
                        break
            if detected_action:
                break
        
        # If we found both game and action, return them
        if detected_game and detected_action:
            logger.info(f"[voice] ✅ Command parsed: game={detected_game}, action={detected_action}")
            return (detected_game, detected_action)
        
        # Log what we found/didn't find
        if not detected_game:
            logger.warning(f"[voice] ❌ No game detected in command: '{text}'")
        elif not detected_action:
            logger.warning(f"[voice] ❌ No action matched in command: '{text}' for game: {detected_game}")
            logger.debug(f"[voice] Available actions for {detected_game}: {list(self.games_config.get(detected_game, {}).get('actions', {}).keys())}")
        
        return None
    
    def get_available_commands(self, game: str) -> Dict[str, list]:
        """Get all available voice commands for a game"""
        if game not in self.games_config:
            return {}
        
        actions = self.games_config[game].get("actions", {})
        commands = {}
        
        for action in actions.keys():
            if action in self.action_synonyms:
                commands[action] = self.action_synonyms[action]
        
        return commands
