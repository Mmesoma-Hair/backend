# Deployment — IdealCommerce API (nasuru-api)

Production runs on a single host (Ubuntu) behind nginx, with gunicorn serving
Django, Celery for async work, Postgres + Redis as datastores. Code lives at
`/home/prime/nasuru-api` owned by the unprivileged `prime` user.

```
client ──HTTPS──> nginx ──unix socket──> gunicorn (config.wsgi)
                    │                         │
                    └─ /static/ (collected)   ├─ Postgres (5432)
                                              └─ Redis (6379) ──> Celery worker + beat
```

## Files

| File | Installed as | Purpose |
|------|--------------|---------|
| `gunicorn.service`     | `/etc/systemd/system/gunicorn.service`      | WSGI app server (gunicorn) |
| `celery-worker.service`| `/etc/systemd/system/celery-worker.service` | Celery worker |
| `celery-beat.service`  | `/etc/systemd/system/celery-beat.service`   | Celery beat scheduler |
| `nginx.conf`           | `/etc/nginx/sites-available/nasuru-api`     | Reverse proxy + static (certbot adds TLS) |
| `sudoers.d-prime`      | `/etc/sudoers.d/prime-deploy`               | Passwordless service restart for deploys |
| `deploy.sh`            | run from repo                               | Pull + install + migrate + restart |

Settings module is `config.settings.prod`. All other config is read from
`/home/prime/nasuru-api/.env` (loaded by python-dotenv). The `.env` is **never**
committed — it holds the Django secret key, DB password and provider secrets.

## First-time provisioning (run once, as root)

```bash
# packages
apt-get update && apt-get install -y python3-venv build-essential libpq-dev \
    git curl nginx postgresql redis-server certbot python3-certbot-nginx

# user
adduser --disabled-password --gecos "" prime && usermod -aG sudo prime
install -d -m 700 -o prime -g prime /home/prime/.ssh
# (paste deploy_key.pub into /home/prime/.ssh/authorized_keys)

# uv (as prime)
sudo -iu prime bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
```

Postgres (remote access was requested — keep the password strong):
```bash
sudo -u postgres psql -c "CREATE USER idealcommerce WITH PASSWORD '<STRONG>';"
sudo -u postgres psql -c "CREATE DATABASE idealcommerce OWNER idealcommerce;"
# listen on all interfaces + allow remote auth (see Security note below)
```

App:
```bash
sudo -iu prime git clone https://github.com/NasuruAI/nasuru-api.git ~/nasuru-api
# write ~/nasuru-api/.env (see .env.example), then:
sudo -iu prime bash -lc 'cd ~/nasuru-api && uv sync --frozen --no-dev \
  && .venv/bin/python manage.py migrate --noinput \
  && .venv/bin/python manage.py collectstatic --noinput'

# services
cp deploy/gunicorn.service      /etc/systemd/system/gunicorn.service
cp deploy/celery-worker.service /etc/systemd/system/celery-worker.service
cp deploy/celery-beat.service   /etc/systemd/system/celery-beat.service
install -m 0440 deploy/sudoers.d-prime /etc/sudoers.d/prime-deploy
systemctl daemon-reload
systemctl enable --now gunicorn celery-worker celery-beat

# nginx + TLS
cp deploy/nginx.conf /etc/nginx/sites-available/nasuru-api
ln -sf /etc/nginx/sites-available/nasuru-api /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d api.eandewigs.com --non-interactive --agree-tos -m admin@eandewigs.com
```

## Ongoing deploys

- **Automatic:** push to `main` → GitHub Actions (`.github/workflows/deploy.yml`)
  scps the code to the server as `prime`, then installs, migrates and restarts.
- **Manual:** `ssh prime@api.eandewigs.com 'cd ~/nasuru-api && bash deploy/deploy.sh'`

### Required GitHub repository secrets

| Secret | Value |
|--------|-------|
| `SSH_KEY`    | contents of `backend/.ssh/deploy_key` (the **private** key) |
| `SERVER_IP`  | `46.101.47.77` |

The matching public key (`backend/.ssh/deploy_key.pub`) goes in the server's
`/home/prime/.ssh/authorized_keys`.

## Security notes

- **Postgres open to the internet** was explicitly requested. This is risky:
  keep the password long/random, and prefer restricting `pg_hba.conf` to known
  IPs or fronting it with the firewall (`ufw allow from <ip> to any port 5432`)
  as soon as you can. Anyone who reaches 5432 can brute-force the password.
- After confirming key-based login works, disable SSH password auth
  (`PasswordAuthentication no`) and rotate the root password you shared.
- The `prime` deploy sudo rule is scoped to three `systemctl` commands only.
