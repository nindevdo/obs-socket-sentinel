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
        
        # Build action mappings with synonyms
        self.action_synonyms = {
            "kill": ["kill", "killed", "eliminated", "frag", "takedown", "got him", "got her"],
            "death": ["death", "died", "dead", "killed me", "i died", "rip"],
            "downed": ["down", "downed", "knocked", "knocked down"],
            "clear": ["clear", "cleared", "safe", "all clear"],
            "headshot": ["headshot", "head shot", "dome", "domed"],
            "run_start": ["start run", "begin run", "new run", "start game", "lets go"],
            "run_end": ["end run", "finish run", "game over", "run complete"],
            "extract": ["extract", "extracted", "extraction", "evac", "evacuate"],
            "revive": ["revive", "revived", "rez", "rezzed", "bring back"],
            "assist": ["assist", "assisted", "help", "helped"],
            "banish": ["banish", "banished", "banishing"],
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
