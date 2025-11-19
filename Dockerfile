FROM python:3.11.9-slim-bullseye
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Set working directory
WORKDIR /app

# Copy the application code
COPY app/ /app/

# Make sure Docker secrets are available to the app
RUN mkdir -p /run/secrets

# Install dependencies
RUN pip install --no-cache-dir aiohttp watchdog obsws-python pyyaml

# Default command
CMD ["python", "main.py"]
