FROM anasty17/mltb:latest

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH="/app/mltbenv/bin:$PATH"

WORKDIR /app

# Install system dependencies upfront for Docker layer caching
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    archivemount \
    fuse \
    libfuse2 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python3 -m venv /app/mltbenv

# Install python dependencies first to optimize build caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source repository
COPY . .

# Normalize line endings and set safe executable permissions
RUN sed -i 's/\r$//' *.sh && \
    chmod 755 *.sh

CMD ["bash", "start.sh"]
