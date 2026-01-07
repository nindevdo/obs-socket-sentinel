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
    """Parse voice commands and map to Socket Sentinel actions"""
    
    def __init__(self, games_config: Dict):
        self.games_config = games_config
        
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
        
    def parse_command(self, text: str, current_game: Optional[str] = None) -> Optional[Tuple[str, str]]:
        """
        Parse voice command text and return (game, action) tuple
        
        Args:
            text: Transcribed speech text
            current_game: Currently selected game (for context)
            
        Returns:
            (game, action) tuple or None if no match
        """
        text = text.lower().strip()
        logger.info(f"[voice] Parsing command: '{text}' (current_game={current_game})")
        
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
