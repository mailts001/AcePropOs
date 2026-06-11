#!/bin/bash
# PropOS VPS Setup Script
# Run on Hetzner CPX12 Singapore (Ubuntu 26.04) as root
# Usage: bash deploy_vps.sh
set -e

VPS_USER=root
APP_DIR=/root/propos
REPO=https://github.com/mailts001/AcePropOs.git
PYTHON=python3.13

echo "=== PropOS VPS Deploy ==="

# 1. System deps
apt-get update -qq
apt-get install -y git python3.13 python3.13-venv python3.13-dev \
    build-essential curl nginx certbot python3-certbot-nginx \
    supervisor cron sqlite3

# 2. Clone / pull repo
if [ -d "$APP_DIR/.git" ]; then
    cd $APP_DIR && git pull
else
    git clone $REPO $APP_DIR
fi
cd $APP_DIR

# 3. Python venv
if [ ! -d ".venv" ]; then
    $PYTHON -m venv .venv
fi
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q
echo "Dependencies installed"

# 4. Create .env (you must fill in your keys after this runs)
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "!!! ACTION REQUIRED: Edit /root/propos/.env with your API keys !!!"
    echo "    nano /root/propos/.env"
fi

# 5. Create dirs
mkdir -p cache/{hdb,ura,news,macro,llm_responses} logs

# 6. Systemd services
cat > /etc/systemd/system/propos-dashboard.service << 'SVCEOF'
[Unit]
Description=PropOS Streamlit Dashboard
After=network.target

[Service]
User=root
WorkingDirectory=/root/propos
ExecStart=/root/propos/.venv/bin/streamlit run dashboard/app.py --server.port 8502 --server.address 0.0.0.0 --server.headless true
Restart=always
RestartSec=10
EnvironmentFile=/root/propos/.env

[Install]
WantedBy=multi-user.target
SVCEOF

cat > /etc/systemd/system/propos-api.service << 'SVCEOF'
[Unit]
Description=PropOS FastAPI Backend
After=network.target

[Service]
User=root
WorkingDirectory=/root/propos
ExecStart=/root/propos/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8503
Restart=always
RestartSec=10
EnvironmentFile=/root/propos/.env

[Install]
WantedBy=multi-user.target
SVCEOF

cat > /etc/systemd/system/propos-bot.service << 'SVCEOF'
[Unit]
Description=PropOS Telegram Bot
After=network.target

[Service]
User=root
WorkingDirectory=/root/propos
ExecStart=/root/propos/.venv/bin/python bot/telegram_bot.py
Restart=always
RestartSec=30
EnvironmentFile=/root/propos/.env

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable propos-dashboard propos-api propos-bot
echo "Systemd services registered"

# 7. Cron jobs (SGT = UTC+8)
(crontab -l 2>/dev/null | grep -v propos; cat << 'CRONEOF'
# PropOS cron jobs (all times in SGT / UTC+8, server runs UTC so subtract 8h)

# News sync — every hour
0 * * * * cd /root/propos && .venv/bin/python scripts/sync_news.py >> logs/cron.log 2>&1

# HDB sync — Sunday 2AM SGT (Sunday 18:00 UTC Saturday)
0 18 * * 0 cd /root/propos && .venv/bin/python scripts/sync_hdb.py >> logs/cron.log 2>&1

# URA sync — daily 3AM SGT (daily 19:00 UTC)
0 19 * * * cd /root/propos && .venv/bin/python scripts/sync_ura.py >> logs/cron.log 2>&1

CRONEOF
) | crontab -
echo "Cron jobs set"

# 8. Nginx reverse proxy
cat > /etc/nginx/sites-available/propos << 'NGINXEOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8502;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8503/;
        proxy_set_header Host $host;
    }
}
NGINXEOF

ln -sf /etc/nginx/sites-available/propos /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo "Nginx configured"

# 9. Initial data sync
echo "Running initial HDB sync..."
cd $APP_DIR && .venv/bin/python scripts/sync_hdb.py

echo ""
echo "=== Deploy complete ==="
echo "Dashboard: http://5.223.72.120:8502"
echo "API:       http://5.223.72.120:8503/docs"
echo ""
echo "Next steps:"
echo "  1. nano /root/propos/.env          — fill in API keys"
echo "  2. systemctl start propos-dashboard propos-api propos-bot"
echo "  3. .venv/bin/python scripts/sync_ura.py   — sync URA private data (SG IP now active)"
echo "  4. Check logs: journalctl -u propos-dashboard -f"
