# obs-socket-sentinel

OBS overlay system with Discord integration that triggers videos, sounds, and memes based on emoji reactions to gameplay actions.

## Features

- **Real-time Overlay**: Display action counts with emojis (kills, deaths, etc.)
- **Discord Integration**: Automatically fetch and cache media from Discord messages
- **YouTube Video Support**: Play YouTube videos triggered by emoji reactions
- **Run Tracking**: Track gaming session statistics with visual run panels
- **Chapter Logging**: Automatic timestamped action logging for video editing
- **Multi-Game Support**: Configure different actions and emojis for different games
- **Rate Limited & Cached**: Smart caching prevents Discord API spam

## New: YouTube Playlist Poster 🎬

Easily import entire YouTube playlists into your Discord channel:

```bash
# Post all videos from a playlist to Discord
./post-playlist.sh 'https://www.youtube.com/playlist?list=YOUR_PLAYLIST_ID'

# Limit to first 25 videos
./post-playlist.sh 'https://www.youtube.com/playlist?list=YOUR_PLAYLIST_ID' 25
```

See [YOUTUBE-PLAYLIST-POSTER.md](YOUTUBE-PLAYLIST-POSTER.md) for complete documentation.

## Installation
- clone repo 
- update the yaml config file to match your games and emojis
- copy lua script into scripts in obs
- enter url and port into settings for the script
  - if console pops us then likely the server isn't up yet
  - this will create keybindings for all games and actions in obs
- update keybindings assignments
- add browser source into obs with the url of your url for socket-sentinel
  - resize to fit the window or whatever area you want to have it as it should resize for nearly any dimension

## Discord Setup

1. Create a Discord bot and get the bot token
2. Add the bot to your server with message posting permissions
3. Get your Discord channel ID
4. Configure in `.env` file:
   ```
   DISCORD_BOT_TOKEN=your_bot_token_here
   DISCORD_CHANNEL_ID=your_channel_id_here
   ```

## Quick Start

1. Start the container: `docker-compose up -d`
2. Post some YouTube videos to Discord (manually or use the playlist poster)
3. Add emoji reactions to the videos matching your game actions (💀 = kill, 🎯 = headshot, etc.)
4. Configure OBS hotkeys to trigger actions
5. Play and watch the overlay respond!


