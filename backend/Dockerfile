FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies + all Chromium runtime deps manually
# (avoids playwright --with-deps which breaks on Debian Trixie renamed packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build / DB tools
    gcc libpq-dev curl wget gnupg \
    # Chromium runtime dependencies
    libnss3 libnspr4 \
    libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 \
    libatspi2.0-0 \
    libx11-6 libxext6 libxrender1 \
    libx11-xcb1 libxcb1 libxcb-dri3-0 \
    libdbus-1-3 libexpat1 \
    libasound2t64 \
    # Fonts (Debian Trixie renamed ttf-unifont → fonts-unifont)
    fonts-liberation fonts-noto fonts-unifont \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium browser only (system deps already installed above)
RUN playwright install chromium

# Install official Node.js 22 LTS and Unlighthouse CLI for site-wide multi-page audits
RUN curl -fsSL https://nodejs.org/dist/v22.14.0/node-v22.14.0-linux-x64.tar.gz | tar -xz -C /usr/local --strip-components=1 \
    && npm install -g @unlighthouse/cli

# Copy application source code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
