# YouTube Playlist to Discord Poster

This feature allows you to extract all videos from a YouTube playlist and post each video individually to your Discord channel, where they can be used with obs-socket-sentinel's emoji reaction system.

## Overview

The YouTube Playlist Poster extracts video URLs from any public YouTube playlist and posts them one by one to your configured Discord channel. Once posted, these videos can be triggered by emoji reactions in your Discord channel and will play through the obs-socket-sentinel overlay system.

## Features

- ✅ **Extract Complete Playlists**: Get all videos from any public YouTube playlist
- ✅ **Rate Limited Posting**: Respects Discord API limits with configurable delays
- ✅ **Safety Limits**: Default maximum of 50 videos per run to prevent spam
- ✅ **Docker Integration**: Runs seamlessly within the existing container
- ✅ **Error Handling**: Robust error handling and logging
- ✅ **Title Preservation**: Posts both video title and URL for easy identification

## Installation

The playlist poster is included with obs-socket-sentinel. No additional installation steps are required beyond the normal setup.

## Usage

### Quick Start

1. Make sure your obs-socket-sentinel container is running:
   ```bash
   docker-compose up -d
   ```

2. Post a playlist to Discord:
   ```bash
   ./post-playlist.sh 'https://www.youtube.com/playlist?list=YOUR_PLAYLIST_ID'
   ```

### Advanced Usage

**Limit number of videos:**
```bash
./post-playlist.sh 'https://www.youtube.com/playlist?list=YOUR_PLAYLIST_ID' 25
```

**Run from inside the container:**
```bash
docker exec obs-socket-sentinel-obs-socket-sentinel-1 /app/post-playlist.sh 'PLAYLIST_URL'
```

**Manual execution:**
```bash
docker exec obs-socket-sentinel-obs-socket-sentinel-1 python /app/youtube_playlist_poster.py 'PLAYLIST_URL' 25
```

## Configuration

The playlist poster uses the same Discord configuration as obs-socket-sentinel:

- `DISCORD_BOT_TOKEN` - Your Discord bot token
- `DISCORD_CHANNEL_ID` - The channel ID where videos will be posted

These are automatically loaded from your `.env` file.

## How It Works

1. **Extract Playlist**: Uses yt-dlp to extract all video URLs from the playlist
2. **Process Videos**: Converts each video to a standard YouTube watch URL
3. **Post to Discord**: Posts each video with its title to your Discord channel
4. **Rate Limiting**: Waits 2 seconds between posts to respect Discord API limits

## Integration with obs-socket-sentinel

Once videos are posted to Discord:

1. **Add Reactions**: React to posted videos with emojis that match your game actions (💀 for kills, 🎯 for headshots, etc.)
2. **Trigger Videos**: When obs-socket-sentinel receives actions, it will randomly select from videos with matching emoji reactions
3. **Play in Overlay**: Videos play automatically in your OBS browser source overlay

## Example Workflow

1. Find a YouTube playlist of gaming highlights
2. Run the playlist poster:
   ```bash
   ./post-playlist.sh 'https://www.youtube.com/playlist?list=PLrAXtmRdnEQy6nuLMCSM05Zo1Jzwg_kkF' 20
   ```
3. Go to your Discord channel and add emoji reactions to the videos
4. Configure your OBS hotkeys to trigger actions
5. During gameplay, trigger actions and watch the videos play in your overlay!

## Safety Features

- **Maximum Limit**: Default maximum of 50 videos per run
- **Rate Limiting**: 2-second delay between Discord posts
- **Error Recovery**: Continues posting even if individual videos fail
- **Validation**: Validates playlist URLs and environment variables

## Troubleshooting

### Container Not Running
```
❗ Error: Container 'obs-socket-sentinel-obs-socket-sentinel-1' is not running
```
**Solution**: Start the container with `docker-compose up -d`

### Missing Environment Variables
```
❗ Error: DISCORD_BOT_TOKEN environment variable is not set
```
**Solution**: Check your `.env` file contains the required Discord configuration

### Invalid Playlist URL
```
❗ Failed to extract playlist: Could not extract playlist info
```
**Solution**: 
- Ensure the playlist is public
- Check the URL format is correct
- Try a different playlist to test

### Rate Limiting
```
❗ Discord API error 429: Too Many Requests
```
**Solution**: 
- Wait a few minutes before retrying
- The script automatically includes rate limiting to prevent this

## Technical Details

### Files Added
- `/app/youtube_playlist_poster.py` - Main Python module
- `/app/post-playlist.sh` - Container entry point script  
- `/post-playlist.sh` - Host wrapper script
- `/YOUTUBE-PLAYLIST-POSTER.md` - This documentation

### Dependencies
Uses existing obs-socket-sentinel dependencies:
- `yt-dlp` - YouTube playlist extraction
- `aiohttp` - Discord API communication
- Standard Python libraries

### Rate Limiting
- 2 seconds between Discord posts
- Respects Discord's rate limits
- Configurable delay for different use cases

### Security
- Validates all inputs
- Uses existing Discord bot permissions
- No additional API keys or tokens required

## FAQ

**Q: Can I use private playlists?**
A: No, only public YouTube playlists are supported.

**Q: Will this work with YouTube Music playlists?**
A: Yes, as long as the playlist is public and contains regular YouTube videos.

**Q: Can I post more than 50 videos?**
A: You can override the safety limit, but it's not recommended to avoid Discord spam.

**Q: Will this delete existing Discord messages?**
A: No, it only posts new messages. Existing content is not affected.

**Q: Can I cancel while posting?**
A: Yes, use Ctrl+C to interrupt. Already posted videos will remain in Discord.

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review the obs-socket-sentinel logs: `docker logs obs-socket-sentinel-obs-socket-sentinel-1`
3. Ensure your Discord bot has permission to post in the target channel