FROM python:3.13-slim

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r joeai && useradd -r -g joeai -d /app -s /sbin/nologin joeai

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

COPY cloud/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set ownership and switch to non-root user
RUN chown -R joeai:joeai /app
USER joeai

ENTRYPOINT ["/entrypoint.sh"]
