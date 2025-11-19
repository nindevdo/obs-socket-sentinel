# OBS Chapter Watcher

## Overview 📋
OBS Chapter Watcher is a Python-based tool that monitors OBS chapter marker files and provides a live display of the latest chapter marker in your OBS scenes. It also includes an automated cleanup feature to help manage your recording files.

## Features ✨

### Chapter Marker Display 🎬
- Monitors OBS chapter marker files in real-time
- Extracts the latest chapter marker information
- Maps chapter markers to emojis for visual enhancement
- Creates a continuously updated text file that can be used as a source in OBS
- Clears the display after 15 seconds of inactivity

### Recording Cleanup 🧹
- Automatically scans recording directories
- Keeps recordings with chapter labels
- Deletes recordings without labels after they're older than 60 seconds
- Removes associated .txt, .xml, and video files

## Setup 🚀

### Prerequisites
- Docker and Docker Compose
- OBS Studio

### Installation
1. Clone this repository:
   ```bash
   git clone https://github.com/yourusername/obs-chapter-watch.git
   cd obs-chapter-watch
   ```

2. Edit the `.env` file to configure your paths:
   ```properties
   CHAPTER_MARKERS_DIR=/path/to/your/obs/markers
   CHAPTER_MARKERS_SYM=/path/to/your/obs/live
   ```

3. Build and start the container:
   ```bash
   docker-compose up -d
   ```

## Configuration ⚙️

### Docker Compose
The `docker-compose.yml` file configures the container with low resource usage:
- 0.10 CPU cores limit
- 64MB memory limit
- Read-only access to markers directory
- Read-write access to live output directory

### Chapter Actions and Emojis
The script maps specific actions in chapter markers to emojis:
- Kill: 💀
- Headshot: 💥
- Revive: ❤️
- Downed: ✝️
- Assist: 🤝
- And many more!

## Usage in OBS 🎮

1. Add a "Text (GDI+)" source to your scene
2. Check "Read from file" and select the `live_chapters.txt` file
3. When you add a chapter marker in OBS, it will appear with the corresponding emoji
4. The text automatically clears after 15 seconds

## How It Works 🔍

- The script uses watchdog to monitor the chapter marker files
- When a new marker is added, it extracts the action and maps it to an emoji
- It updates the live text file with this information
- After 15 seconds of no new markers, it clears the file
- Every 10 minutes, it scans for and cleans up unlabeled recordings

## Resource Usage 📊
This tool is designed to be lightweight:
- Uses polling observer for reliable file detection in Docker/WSL environments
- Avoids CPU-intensive operations
- Limited to 0.10 CPU cores and 64MB memory

## Contributing 🤝
Feel free to submit issues or pull requests if you have suggestions for improvements!