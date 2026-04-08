FROM python:3.13-slim

# Install ffmpeg, Node.js 20, and dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    nodejs \
    npm \
    && npm install -g n \
    && n 20 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install bgutil PO token provider globally
RUN npm install -g @imputnet/bgutil-ytdlp-pot-provider

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["bash", "start.sh"]
