# Steam Achievement Notification System

## Overview
The OBS Socket Sentinel now includes a Steam achievement notification system that displays beautiful achievement unlocks on stream when notified by an external Steam monitoring service.

## Features
- **Secure Authentication**: Uses the same SS_TOKEN for API security
- **Rich Notifications**: Displays achievement icon, title, description, and game name
- **Auto-Display Timing**: Shows notifications for 10 seconds by default
- **Golden UI**: Eye-catching golden achievement notification design
- **Overlay Integration**: Seamlessly integrates with existing overlay system

## Testing

### Quick Test

1. **Start the service**:
   ```bash
   docker-compose up -d
   ```

2. **Run the test script inside the container**:
   ```bash
   # Basic test
   docker-compose exec obs-socket-sentinel python test_achievement_simple.py
   
   # Custom achievement title
   docker-compose exec obs-socket-sentinel python test_achievement_simple.py "My Custom Achievement"
   ```

3. **View the result**: Open http://localhost:8088 in your browser to see the golden achievement notification appear at the top of the page.

### What You Should See
- **Large golden notification** slides down from top center (much bigger fonts!)
- Shows achievement title, description, and game name clearly
- **Xbox achievement sound** plays automatically
- Auto-hides after 10 seconds with glow animation
- Test script confirms API success and overlay data

## API Endpoint

### POST /achievement

Accepts achievement data via JSON POST request with authentication.

**Authentication**: Requires `Authorization: Bearer {SS_TOKEN}` header.

**Content-Type**: `application/json`

**Request Body Format**:
```json
{
  "achievement_title": "First Steps",
  "api_name": "FIRST_STEPS",
  "description": "Complete the tutorial level",
  "icon": "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/apps/123456/achievement_icon.jpg",
  "icon_gray": "https://steamcdn-a.akamaihd.net/steamcommunity/public/images/apps/123456/achievement_icon_gray.jpg", 
  "game_name": "Hunt: Showdown",
  "app_id": "594650",
  "unlock_time": 1700000000,
  "unlock_time_iso": "2023-11-14T22:13:20Z",
  "unlock_time_readable": "2023-11-14 22:13:20 UTC",
  "steam_id": "76561198000000000"
}
```

**Responses**:
- **200 OK**: `{"status": "success", "message": "Achievement displayed"}`
- **400 Bad Request**: `{"error": "Invalid data"}` or `{"error": "Invalid JSON"}`
- **401 Unauthorized**: `{"error": "Unauthorized: Missing or invalid token"}`

### Required Fields

- `achievement_title`: Display name of the achievement
- `api_name`: Steam API name for the achievement
- `description`: Achievement description text
- `icon`: URL to the achievement icon
- `game_name`: Name of the game
- `app_id`: Steam App ID
- `unlock_time`: Unix timestamp when unlocked
- `steam_id`: Steam ID of the player

### Optional Fields

- `icon_gray`: URL to the grayscale version of the icon
- `unlock_time_iso`: ISO format timestamp
- `unlock_time_readable`: Human-readable timestamp

## Integration Example

```python
import requests

def send_achievement_to_obs(achievement_data, obs_url="http://localhost:8088", token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    
    response = requests.post(f"{obs_url}/achievement", headers=headers, json=achievement_data)
    return response.status_code == 200

# Example usage
achievement = {
    "achievement_title": "Speed Demon",
    "api_name": "SPEED_DEMON", 
    "description": "Complete a level in under 30 seconds",
    "icon": "https://steamcdn-a.akamaihd.net/...",
    "game_name": "Hunt: Showdown",
    "app_id": "594650",
    "unlock_time": int(time.time()),
    "steam_id": "76561198123456789"
}

success = send_achievement_to_obs(achievement, token="your_ss_token")
```