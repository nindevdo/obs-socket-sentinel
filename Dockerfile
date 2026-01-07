FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Install Python 3.11 and system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
  python3.11 \
  python3-pip \
  ffmpeg \
  nodejs \
  npm \
  wget \
  unzip \
  && rm -rf /var/lib/apt/lists/*

# Make python3.11 the default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Download and install ProggyClean Nerd Font for serving
RUN mkdir -p /app/_data/fonts && \
  wget -q https://github.com/ryanoasis/nerd-fonts/releases/download/v3.1.1/ProggyClean.zip -O /tmp/ProggyClean.zip && \
  unzip -q /tmp/ProggyClean.zip -d /app/_data/fonts/ && \
  rm /tmp/ProggyClean.zip

# Set working directory
WORKDIR /app

# Copy the application code (everything is now in app/)
COPY app/ /app/

# Make sure Docker secrets are available to the app
RUN mkdir -p /run/secrets

# Install Python dependencies
RUN pip install --no-cache-dir aiohttp watchdog obsws-python pyyaml yt_dlp nltk faster-whisper numpy

# Download NLTK WordNet corpus for synonym generation
RUN python -c "import nltk; nltk.download('wordnet', quiet=True); nltk.download('omw-1.4', quiet=True)"

# Default command
CMD ["python", "main.py"]
