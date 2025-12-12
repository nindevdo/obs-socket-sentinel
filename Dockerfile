FROM python:3.11.9-slim-bullseye
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Install system dependencies including ffmpeg for video duration detection
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the application code (everything is now in app/)
COPY app/ /app/

# Make sure Docker secrets are available to the app
RUN mkdir -p /run/secrets

# Install Python dependencies
RUN pip install --no-cache-dir aiohttp watchdog obsws-python pyyaml yt_dlp nltk

# Download NLTK WordNet corpus for synonym generation
RUN python -c "import nltk; nltk.download('wordnet', quiet=True); nltk.download('omw-1.4', quiet=True)"

# Default command
CMD ["python", "main.py"]
