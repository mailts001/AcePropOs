#!/bin/bash
# PropOS VPS First-Time Setup — Ubuntu 26.04, Hetzner CPX12 Singapore
# Run as root: bash vps_setup.sh
# Then run: bash vps_setup.sh --ssl yourdomain.com   to add HTTPS
set -e

APP_DIR=/root/propos
REPO=https://github.com/mailts001/AcePropOs.git

# ── Step 1: System packages ────────────────────────────────────────────────
echo "[1/8] Installing system packages..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git python3 python3-venv python3-dev \
    build-essential curl wget \
    nginx certbot python3-certbot-nginx \
    ufw sqlite3 2>/dev/null

# ── Step 2: Firewall ───────────────────────────────────────────────────────
echo "[2/8] Configuring firewall..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 8502/tcp   # Direct Streamlit access (can remove after HTTPS set up)
ufw --force enable
echo "Firewall active"

# ── Step 3: Clone repo ─────────────────────────────────────────────────────
echo "[3/8] Cloning repo..."
if [ -d "$APP_DIR/.git" ]; then
    cd $APP_DIR && git pull --quiet
    echo "Repo updated"
else
    git clone --quiet $REPO $APP_DIR
    echo "Repo cloned"
fi
cd $APP_DIR

# ── Step 4: Python venv + deps ─────────────────────────────────────────────
echo "[4/8] Setting up Python venv..."
# pydantic-core requires Python <=3.13 (PyO3 limitation)
# Ubuntu 26.04 ships 3.14 — explicitly use 3.13 if available, install if not
if ! command -v python3.13 &>/dev/null; then
    echo "Python 3.13 not found — installing from deadsnakes PPA..."
    apt-get install -y software-properties-common
    add-apt-repository ppa:deadsnakes/ppa -y
    apt-get update -qq
    apt-get install -y python3.13 python3.13-venv python3.13-dev
fi
PYTHON=python3.13
echo "Using Python: $PYTHON ($($PYTHON --version))"
$PYTHON -m venv .venv
.venv/bin/pip install --upgrade pip setuptools wheel -q
.venv/bin/pip install -r requirements.txt -q
echo "Python deps installed"

# ── Step 5: Dirs + .env ────────────────────────────────────────────────────
echo "[5/8] Creating directories..."
mkdir -p cache/{hdb,ura,news,macro,llm_responses} logs
chmod 700 cache logs

if [ ! -f ".env" ]; then
    cp .env.example .env
    chmod 600 .env
    echo ""
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║  ACTION REQUIRED: Fill in your API keys             ║"
    echo "║  nano /root/propos/.env                             ║"
    echo "╚══════════════════════════════════════════════════════╝"
fi

# ── Step 6: Systemd services ───────────────────────────────────────────────
echo "[6/8] Installing systemd services..."

cat > /etc/systemd/system/propos-dashboard.service << 'EOF'
[Unit]
Description=PropOS Streamlit Dashboard
After=network.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
User=root
WorkingDirectory=/root/propos
EnvironmentFile=/root/propos/.env
ExecStart=/root/propos/.venv/bin/streamlit run dashboard/app.py \
    --server.port 8502 \
    --server.address 127.0.0.1 \
    --server.headless true \
    --server.fileWatcherType none
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/propos-api.service << 'EOF'
[Unit]
Description=PropOS FastAPI Backend
After=network.target

[Service]
User=root
WorkingDirectory=/root/propos
EnvironmentFile=/root/propos/.env
ExecStart=/root/propos/.venv/bin/uvicorn api.main:app \
    --host 127.0.0.1 --port 8503 --workers 1
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/propos-bot.service << 'EOF'
[Unit]
Description=PropOS Telegram Bot
After=network.target

[Service]
User=root
WorkingDirectory=/root/propos
EnvironmentFile=/root/propos/.env
ExecStart=/root/propos/.venv/bin/python bot/telegram_bot.py
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable propos-dashboard propos-api propos-bot
echo "Services installed (not started yet — fill .env first)"

# ── Step 7: Nginx (HTTP first, HTTPS added later) ──────────────────────────
echo "[7/8] Configuring nginx..."

cat > /etc/nginx/sites-available/propos << 'EOF'
# PropOS — HTTP (run certbot to upgrade to HTTPS)
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    # Streamlit WebSocket support
    location / {
        proxy_pass http://127.0.0.1:8502;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8503/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Health check endpoint
    location /health {
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }
}
EOF

rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/propos /etc/nginx/sites-enabled/
nginx -t && systemctl restart nginx
echo "Nginx configured (HTTP)"

# ── Step 8: Cron (times in UTC — Singapore is UTC+8) ──────────────────────
echo "[8/8] Installing cron jobs..."
(crontab -l 2>/dev/null | grep -v propos; cat << 'CRONEOF'
# PropOS — all times UTC (SGT = UTC+8)
# News sync every hour
0 * * * * cd /root/propos && .venv/bin/python scripts/sync_news.py >> logs/cron.log 2>&1
# Watchlist price alerts every hour (15 min offset to avoid clash)
15 * * * * cd /root/propos && .venv/bin/python scripts/run_watchlist_check.py >> logs/cron.log 2>&1
# HDB sync weekly, Sun 2AM SGT = Sat 18:00 UTC
0 18 * * 6 cd /root/propos && .venv/bin/python scripts/sync_hdb.py >> logs/cron.log 2>&1
# URA sync daily 3AM SGT = 19:00 UTC
0 19 * * * cd /root/propos && .venv/bin/python scripts/sync_ura.py >> logs/cron.log 2>&1
CRONEOF
) | crontab -
echo "Cron jobs installed"

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Setup complete! Next steps:                                ║"
echo "║                                                              ║"
echo "║  1. Fill in API keys:                                       ║"
echo "║     nano /root/propos/.env                                  ║"
echo "║                                                              ║"
echo "║  2. Start services:                                         ║"
echo "║     systemctl start propos-dashboard propos-api             ║"
echo "║                                                              ║"
echo "║  3. Test HTTP access:                                       ║"
echo "║     http://5.223.72.120  (via nginx)                        ║"
echo "║     http://5.223.72.120:8502  (direct)                      ║"
echo "║                                                              ║"
echo "║  4. Sync URA data (Singapore IP now active!):               ║"
echo "║     cd /root/propos && .venv/bin/python scripts/sync_ura.py ║"
echo "║                                                              ║"
echo "║  5. Add HTTPS (needs domain):                               ║"
echo "║     bash vps_setup.sh --ssl yourdomain.com                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"

# ── Optional: --ssl flag adds Let's Encrypt ────────────────────────────────
if [ "$1" = "--ssl" ] && [ -n "$2" ]; then
    DOMAIN=$2
    echo ""
    echo "Setting up HTTPS for $DOMAIN..."
    # Update nginx to use domain
    sed -i "s/server_name _;/server_name $DOMAIN;/" /etc/nginx/sites-available/propos
    nginx -t && systemctl reload nginx
    # Get cert
    certbot --nginx -d $DOMAIN --non-interactive --agree-tos \
        -m admin@$DOMAIN --redirect
    echo "HTTPS enabled at https://$DOMAIN"
    # Auto-renew cert (certbot installs a timer but add cron as backup)
    (crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet && systemctl reload nginx") | crontab -
fi
