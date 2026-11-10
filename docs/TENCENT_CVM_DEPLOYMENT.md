# Deploy PaidDrive to your Tencent CVM

This runbook adds PaidDrive to the CVM documented in your soccer project's
`docs/DEPLOYMENT-TENCENT.md`: **119.45.126.188, TencentOS Server 3.3, host Nginx
and Certbot**. The soccer project's `AGENTS.md` identifies that guide as
authoritative; its AWS deployment and redeployment guides are retired.

The server details below come from that document, not a live server inspection.
Recheck them in Step 1. No CVM deployment has been performed for PaidDrive.

The suggested new hostname is **drive.dolphincoder.cn**. Substitute your chosen
hostname consistently if different. These are the intended resources:

| Resource | Existing services | PaidDrive |
| --- | --- | --- |
| Public entry | Host Nginx on 80/443 | One additional Nginx virtual host |
| Application ports | 8000: dolphincoder.cn; 8080: Docker site 132855.cn; 8090: soccer systemd service | **127.0.0.1:8091** |
| Runtime | Soccer uses native Java/systemd; another site already uses Docker | Existing Docker Engine, independent Compose project `paid-drive` |
| Source checkout | Existing applications keep their paths | `/opt/paiddrive` |
| Persistent state | Existing databases and uploads keep their paths | `/var/lib/paiddrive/data` and `/var/lib/paiddrive/content` |
| Private configuration | Soccer's `/etc/soccer-match-analyzer.env` | `/opt/paiddrive/.env` |
| Nginx configuration | Existing files, including `soccer.conf` | `/etc/nginx/conf.d/paiddrive.conf` |
| Certificates | Existing Certbot installation and renewal scheduler | New certificate for the new hostname |

**Design decision — separation of concerns:** Nginx handles the shared HTTPS
entry point, Docker supplies PaidDrive's Python 3.12 runtime, and persistent
orders/images live outside the Git checkout so code updates cannot replace them.
PaidDrive uses SQLite; it needs no new MySQL, Redis, Java or host Python runtime.

Run the numbered steps in order. Blocks marked **Mac**, **CVM**, or **Console**
run in different places. Run one block at a time and stop on an unexpected error.
In every new Mac terminal, set the shown SSH destination again. Carry your
existing key option (`-i`) to both `ssh` and `scp`; a custom port uses `ssh -p`
but **`scp -P`**. The examples use port 22 and your existing default SSH identity.
Commands shown here are instructions, not commands already executed on the CVM.

## 1. Connect and verify the shared server

**Mac:** use the same SSH account/key/port that already works for your soccer
server. The old guide shows `root@119.45.126.188` as a transfer example; it does
not establish that everyone should log in as root. Replace the account below;
add your existing `-i` or `-p` options if needed.

```bash
PD_CVM='YOUR_EXISTING_SSH_USER@119.45.126.188'
ssh "$PD_CVM"
```

**CVM:** use Bash for the following commands and retain this session. Re-enter
these variables after reconnecting. `PD_STAMP` identifies this deployment's
private audit directory; record its value for recovery.

```bash
bash
PD_DOMAIN='drive.dolphincoder.cn'
PD_PORT='8091'
PD_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PD_AUDIT_DIR="/var/backups/paiddrive-$PD_STAMP"
PD_DEPLOY_USER="$(id -un)"
PD_DEPLOY_GROUP="$(id -gn)"
printf 'Audit directory: %s\n' "$PD_AUDIT_DIR"

cat /etc/os-release
uname -m
id
df -h / /var /tmp
free -h
sudo ss -lntp
sudo systemctl is-active nginx soccer-match-analyzer
sudo nginx -t
sudo docker version
sudo docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
sudo docker info --format '{{json .SecurityOptions}}'
sudo certbot --version
getenforce
sudo getsebool httpd_can_network_connect
```

Check that Nginx owns 80/443, soccer still uses 8090, and **8091 is unused**.
If 8091 is occupied, choose a free port and change `PD_PORT`, `.env`, Nginx and
both sides of the SSH tunnel consistently. Record the existing containers and
the status of all three existing websites. The old guide's free RAM/disk values
are historical; use the current output above.

This guide assumes the existing **rootful Docker daemon without user-namespace
remapping**, so container UID/GID 10001 maps to host 10001. If Docker reports
`rootless` or `userns`, adapt the bind-mount ownership to its actual mapping before
proceeding; do not change the shared daemon configuration to fit this guide.

Keep the existing firewall rules. The new application needs no public 8091,
SQLite, SMTP or Docker port. Check the Tencent security group still permits
public 80/443 and your existing restricted SSH access. For an older Docker
Engine, note the official [pre-28 localhost-publication caveat](https://docs.docker.com/engine/network/port-publishing/):
same-layer-2 peers may reach a localhost-published port. Resolve any exposure
before loading paid originals; plan any Engine upgrade separately from this
deployment.

Save the current Nginx state privately:

```bash
sudo install -d -m 0700 "$PD_AUDIT_DIR"
sudo tar -czf "$PD_AUDIT_DIR/nginx-before.tar.gz" -C /etc nginx
sudo bash -c 'nginx -T > "$1/nginx-before.txt" 2>&1' _ "$PD_AUDIT_DIR"
sudo bash -c 'docker ps --no-trunc > "$1/containers-before.txt"' _ "$PD_AUDIT_DIR"
```

Inspect the saved Nginx configuration on the server to confirm that it includes
`/etc/nginx/conf.d/*.conf`, and that `drive.dolphincoder.cn` is not already used.
Do not paste complete server configuration or private environment files into chat.

**Mac:** record baseline responses before making changes:

```bash
curl -I https://dolphincoder.cn/
curl -I https://132855.cn/
curl -I https://soccer.dolphincoder.cn/matches
```

## 2. Check Docker Compose

**CVM:**

```bash
sudo docker compose version
sudo docker compose ls
command -v git
python3 --version
```

If Compose works, retain it and go to Step 3. Host `python3` is used only for
the small standard-library configuration renderer; the app, tests, import and
backup run in the Python 3.12 image. If `git` or `python3` is missing, install
only that missing utility with TencentOS's `dnf`, reviewing the transaction.

If Compose is absent, install only its CLI plugin. Do not reinstall, upgrade or
restart the shared Docker daemon. The following optional block pins the official
Compose **v5.7.0** release and verifies its published binary digest. It refuses
to overwrite an existing plugin. A working plugin in a different path should
be reused instead. [Docker plugin installation](https://docs.docker.com/compose/install/linux/),
[official release](https://github.com/docker/compose/releases/tag/v5.7.0).

```bash
(
  set -eu
  PD_COMPOSE_VERSION='v5.7.0'
  case "$(uname -m)" in
    x86_64) PD_COMPOSE_ARCH='x86_64'; PD_COMPOSE_SHA='7758048ad38e580f22559603312874fec8bb638d021a9e64182385fc17cc12a2' ;;
    aarch64) PD_COMPOSE_ARCH='aarch64'; PD_COMPOSE_SHA='15861535d14e26555736b49376c95e14bfd94285366c8446bfac7156a972e76f' ;;
    *) echo 'Check the official release for this architecture.' >&2; exit 1 ;;
  esac
  PD_COMPOSE_TMP="$(mktemp -d /tmp/paiddrive-compose.XXXXXX)"
  PD_COMPOSE_FILE="docker-compose-linux-$PD_COMPOSE_ARCH"
  cd "$PD_COMPOSE_TMP"
  curl -fL --retry 3 --proto '=https' --tlsv1.2 \
    "https://github.com/docker/compose/releases/download/$PD_COMPOSE_VERSION/$PD_COMPOSE_FILE" \
    -o "$PD_COMPOSE_FILE"
  printf '%s  %s\n' "$PD_COMPOSE_SHA" "$PD_COMPOSE_FILE" | sha256sum --check -
  test ! -e /usr/local/lib/docker/cli-plugins/docker-compose
  sudo install -d -m 0755 /usr/local/lib/docker/cli-plugins
  sudo install -m 0755 "$PD_COMPOSE_FILE" /usr/local/lib/docker/cli-plugins/docker-compose
  sudo docker compose version
  sudo docker compose ls
)
```

This manual plugin does not auto-update. A client/Engine compatibility error
needs a separate decision about the existing Engine, not an automatic daemon
upgrade. A blocked download should be fetched from the same official source on
your Mac, checksum-verified, then transferred to the CVM; do not substitute an
unknown mirror or run a remote shell installer.

## 3. Give the CVM read access to the private repository

The repository is [mjmonster/paid-drive](https://github.com/mjmonster/paid-drive).
Your Mac's working GitHub login does not automatically authenticate the CVM.
If the CVM already has an identity authorized for **this** repository, verify it
with `git ls-remote git@github.com:mjmonster/paid-drive.git refs/heads/main` and
skip new key creation. An existing soccer-specific deploy key cannot be reused
as another repository's deploy key.

Otherwise, **CVM**, as the deployment user:

```bash
install -d -m 0700 "$HOME/.ssh"
PD_KEY="$HOME/.ssh/paiddrive_deploy_ed25519"
(
  set -eu
  test ! -e "$PD_KEY"
  test ! -e "$PD_KEY.pub"
  ssh-keygen -t ed25519 -C 'paid-drive CVM read-only deploy key' -f "$PD_KEY"
)
cat "$PD_KEY.pub"
```

Choose a passphrase according to your server's key policy; enter it interactively
when Git needs it, or load the key into your existing agent. Keep the private
file on the CVM. Copy **only the `.pub` output**.

**GitHub Console:** repository → Settings → Deploy keys → Add deploy key.
Name it `Tencent CVM PaidDrive`, paste the public key, and leave **Allow write
access unchecked**. [GitHub deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys).

**CVM:** for the new key, set a repository-specific SSH command; do not replace
your existing `~/.ssh/config` or other keys:

```bash
PD_GIT_SSH="ssh -i $PD_KEY -o IdentitiesOnly=yes"
GIT_SSH_COMMAND="$PD_GIT_SSH" git ls-remote \
  git@github.com:mjmonster/paid-drive.git refs/heads/main
```

On first connection, compare the presented host-key fingerprint with
[GitHub's published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)
before accepting. Expect a commit hash followed by `refs/heads/main`. Do not
disable SSH host-key verification. If you reused an existing identity, set
`PD_GIT_SSH='ssh'` instead for the next step.

## 4. Clone a known source release

**CVM:** these paths must be new. If either exists, stop and inspect it; an
existing deployment belongs in Step 15, not this first-install procedure.

```bash
(
  set -eu
  test ! -e /opt/paiddrive
  test ! -e /var/lib/paiddrive
  sudo install -d -m 0755 -o "$PD_DEPLOY_USER" -g "$PD_DEPLOY_GROUP" /opt/paiddrive
  GIT_SSH_COMMAND="$PD_GIT_SSH" git clone --branch main \
    git@github.com:mjmonster/paid-drive.git /opt/paiddrive
  cd /opt/paiddrive
  git config core.sshCommand "$PD_GIT_SSH"
  git checkout --detach d522b124e125e7911ee07bd76186213dfacdc1db
  git rev-parse HEAD
)
cd /opt/paiddrive
```

The pinned commit above is the initial 47-file source release already verified
against your Mac. It contains the app, Docker configuration, sample images,
tests and deployment helpers. A detached checkout here intentionally pins the
deployed version. Record its SHA; later updates select another reviewed commit.
Do not run the Mac workspace installer on the CVM.

## 5. Create private configuration and persistent directories

**CVM:**

```bash
cd /opt/paiddrive
(
  set -eu
  test ! -e .env
  test ! -e compose.override.yaml
  test ! -e /var/lib/paiddrive
  umask 077
  cp .env.example .env
  sudo install -d -m 0750 -o "$PD_DEPLOY_USER" -g "$PD_DEPLOY_GROUP" /var/lib/paiddrive
  sudo install -d -m 0700 -o 10001 -g 10001 /var/lib/paiddrive/data
  sudo install -d -m 0700 -o 10001 -g 10001 /var/lib/paiddrive/data/tmp
  cp -R content /var/lib/paiddrive/content
  cat > compose.override.yaml <<'YAML'
services:
  paid-drive:
    image: paiddrive:local
    environment:
      TMPDIR: /data/tmp
    volumes:
      - /var/lib/paiddrive/data:/data:Z
      - /var/lib/paiddrive/content:/app/content:ro,Z
YAML
  printf '\n/compose.override.yaml\n/compose.rollback.yaml\n' >> .git/info/exclude
)
sudo chgrp -R 10001 /var/lib/paiddrive/content
sudo find /var/lib/paiddrive/content -type d -exec chmod 0750 {} +
sudo find /var/lib/paiddrive/content -type f -exec chmod 0640 {} +
chmod 0600 .env compose.override.yaml
```

Compose automatically combines `compose.yaml` with `compose.override.yaml`.
Volume entries merge by container target, so these replace the repository's
`./data` and `./content` bindings. The override is local server configuration,
excluded from Git. It gives the built image a predictable tag and puts Python's
temporary ZIP files/SQLite backup snapshots on private disk instead of filling
RAM-backed `/tmp`. Provision disk for originals, concurrent ZIPs, database
snapshots and backup archives.

`:Z` gives these dedicated directories a private SELinux container label;
`:ro,Z` also makes originals read-only to the app. Never relabel another site's
directories or disable SELinux. Before the service starts, one-off Compose
commands are fine; after startup use `compose exec` for inspections so another
container does not relabel its active private mounts.
[Docker bind-mount labels](https://docs.docker.com/engine/storage/bind-mounts/#configure-the-selinux-label).

Edit `.env` with your preferred terminal editor, e.g. `vi .env`. Start with:

```dotenv
APP_MODE=demo
APP_URL=http://localhost:8091
PAIDDRIVE_PORT=8091
MAIL_MODE=file
FORWARDED_ALLOW_IPS=127.0.0.1
ZPAY_BASE_URL=
ZPAY_PID=
ZPAY_KEY=
SUPPORT_QR_PATH=
```

Keep the other sample settings. If you selected another port, change both
`APP_URL` and `PAIDDRIVE_PORT`. Compose supplies the container paths for SQLite,
content and mail. Do not copy the soccer environment file or its credential
examples. Use `docker compose config --quiet`, not a command that prints all
expanded credentials.

## 6. Build, run tests and start the private demo

**CVM:**

```bash
cd /opt/paiddrive
(
  set -eu
  sudo docker compose config --quiet
  sudo docker compose build paid-drive
  sudo docker compose run --rm --no-deps --entrypoint python \
    -v "$PWD/tests:/app/tests:ro,Z" \
    -v "$PWD/deploy:/app/deploy:ro,Z" \
    paid-drive -m unittest discover -s tests -v
)
```

Expect **38 tests passed** for the pinned source release. The tests use temporary
databases and mocked payment responses; they do not charge customers or send
real mail. The extra mounts are necessary because the runtime image does not
contain `tests/` or the Nginx templates in `deploy/`. A failed dependency download,
build or test must be resolved before continuing. Use the server's established
trusted registry/network setup if Docker Hub or PyPI cannot be reached; do not
modify the shared Docker daemon just to try an arbitrary mirror.

Check mount readability as the image's actual UID 10001, then start:

```bash
(
set -eu
sudo docker compose run --rm --no-deps -T --entrypoint python paid-drive - <<'PY'
import json
from pathlib import Path
root = Path('/app/content')
catalog = json.loads((root / 'collections.json').read_text('utf-8'))
for collection in catalog['collections']:
    for item in collection['items']:
        with (root / item['file']).open('rb') as handle:
            handle.read(1)
probe = Path('/data/tmp/mount-check')
with probe.open('x') as handle:
    handle.write('ok')
probe.unlink()
print('Content readable; persistent and temporary data writable.')
PY
sudo docker compose up -d --wait --wait-timeout 180 paid-drive
sudo docker compose ps
sudo docker compose logs --tail=50 paid-drive
curl -fsS "http://127.0.0.1:$PD_PORT/health"
sudo docker compose port paid-drive 8000
)
```

Expected health: `{"status":"ok","mode":"demo"}`. Expected published port:
`127.0.0.1:8091`. Allow the health check time to become healthy. Docker manages
restarts with `unless-stopped`; do not create a second systemd app service or
launch an extra Uvicorn process on the host.

**Mac, separate terminal:** keep this tunnel open, using your existing SSH
account/key options:

```bash
PD_CVM='YOUR_EXISTING_SSH_USER@119.45.126.188'
ssh -N -L 8091:127.0.0.1:8091 "$PD_CVM"
```

Open **http://localhost:8091/c/slow-days**. Check three free previews, a locked
fourth card, explicitly labelled simulated payment, unlock, individual download,
ZIP, refresh and revisit. Test email recovery through the private file-mail
outbox if needed; it does not send real mail. Never expose demo mode through
Nginx: simulated payment can unlock any loaded collection.

## 7. Add the DNS record and ACME preparation site

**Tencent DNSPod Console:** choose the existing `dolphincoder.cn` zone. Check
whether `drive` already exists before making any change. For an unused hostname,
add:

| Setting | Value |
| --- | --- |
| Host record | `drive` |
| Type | `A` |
| Value | `119.45.126.188` |
| TTL | 600 seconds, or the console's supported default |

Keep the existing `@`, `soccer` and other records. Do not add AAAA without a
working IPv6 destination. Confirm the parent domain's current Tencent filing/
access status in the console; the old guide's statement is not a fresh check.
[Tencent subdomain filing guidance](https://cloud.tencent.com/document/product/243/19630).

**CVM:** generate the HTTP preparation site. The host renderer uses standard
Python 3 libraries and refuses to overwrite an existing output file.

```bash
cd /opt/paiddrive
sudo install -d -m 0755 /var/www/paiddrive-acme/.well-known/acme-challenge
sudo restorecon -RF /var/www/paiddrive-acme
PD_HTTP_CONF="/tmp/paiddrive-http-$PD_STAMP.conf"
python3 scripts/render_deploy_config.py --domain "$PD_DOMAIN" \
  --phase http --port "$PD_PORT" --output "$PD_HTTP_CONF"
cat "$PD_HTTP_CONF"
(
  set -eu
  test ! -e /etc/nginx/conf.d/paiddrive.conf
  sudo install -m 0644 "$PD_HTTP_CONF" /etc/nginx/conf.d/paiddrive.conf
  sudo nginx -t
  sudo systemctl reload nginx
)
printf 'paiddrive-acme-ok\n' | sudo tee \
  /var/www/paiddrive-acme/.well-known/acme-challenge/paiddrive-check >/dev/null
```

If `nginx -t` fails, no reload occurs. Fix the new file, or move only that new
PaidDrive file into the private audit directory, then validate again. Existing
Nginx workers continue serving the current configuration.

**Mac:**

```bash
dig +short A drive.dolphincoder.cn
dig +short AAAA drive.dolphincoder.cn
curl -fsS http://drive.dolphincoder.cn/.well-known/acme-challenge/paiddrive-check
curl -i http://drive.dolphincoder.cn/
curl -I https://soccer.dolphincoder.cn/matches
```

Expect the A result to be the CVM IP, the challenge response to be
`paiddrive-acme-ok`, and the new site's `/` to return **503**. This is the intended
preparation page. The application is still private. HTTP-01 certificate
validation uses public port 80. [Let's Encrypt HTTP-01](https://letsencrypt.org/docs/challenge-types/#http-01-challenge).

## 8. Obtain the new HTTPS certificate

**CVM:** reuse the existing Certbot installation. Webroot obtains the certificate
without asking Certbot to rewrite any site's Nginx configuration.

```bash
sudo certbot certificates
sudo certbot certonly --webroot --webroot-path /var/www/paiddrive-acme \
  --cert-name "$PD_DOMAIN" -d "$PD_DOMAIN"
sudo certbot certificates
```

Follow Certbot's account/email prompts. Confirm the certificate covers the exact
hostname, and note its actual fullchain/private-key paths. Normally these are
`/etc/letsencrypt/live/drive.dolphincoder.cn/fullchain.pem` and `privkey.pem`.
If a certificate with this name already existed, inspect it before issuance;
do not overwrite an unrelated certificate.

Generate the final proxy configuration, but do not install it yet:

```bash
PD_HTTPS_CONF="/tmp/paiddrive-https-$PD_STAMP.conf"
python3 scripts/render_deploy_config.py --domain "$PD_DOMAIN" \
  --phase https --port "$PD_PORT" --output "$PD_HTTPS_CONF"
cat "$PD_HTTPS_CONF"
```

If Certbot reports different paths, edit only the two certificate paths in the
generated file. Keep the existing HTTP preparation site active through Step 11.
The HTTPS template sends every application/media request through FastAPI;
do not add a static `root` or `alias` for the paid originals.

## 9. Load your real collection and support QR code

This step is required before selling your own content. The repository contains
nine generated sample SVGs and a non-scannable support placeholder.

**CVM:** stop only PaidDrive while changing content. Create a private incoming
directory and record the printed path:

```bash
cd /opt/paiddrive
sudo docker compose stop paid-drive
PD_INCOMING="$(mktemp -d /tmp/paiddrive-images.XXXXXX)"
chmod 0700 "$PD_INCOMING"
printf 'Upload destination: %s\n' "$PD_INCOMING"
```

**Mac:** select the source images and the actual support QR file. Replace the
remote directory with the exact value printed above. `scp -r` below creates an
`Images` subdirectory inside it; supported image files must be directly inside
the selected folder. Use at least four images for three free previews.

```bash
PD_CVM='YOUR_EXISTING_SSH_USER@119.45.126.188'
PD_REMOTE_INCOMING='/tmp/paiddrive-images.REPLACE_WITH_PRINTED_SUFFIX'
scp -r /Users/mewtwo/Images "$PD_CVM:$PD_REMOTE_INCOMING/"
scp /absolute/path/to/your-real-wechat-qr.png \
  "$PD_CVM:$PD_REMOTE_INCOMING/wechat.png"
```

Confirm the QR identifies your intended support account. If it is JPEG, keep
its real extension and use that path consistently; renaming does not convert it.

**CVM:** import with the built Python 3.12 image, not TencentOS's system Python.
This importer copies files, naturally sorts their names, and refuses an existing
collection version. Adjust title, slug and price before running; `1900` means
CNY 19.00. Choose the first three source images deliberately.

```bash
sudo docker run --rm --network none --read-only --tmpfs /tmp \
  --user "$(id -u):$(id -g)" --entrypoint python \
  -v "$PD_INCOMING/Images:/import:ro,Z" \
  -v /var/lib/paiddrive/content:/work/content:Z \
  paiddrive:local scripts/import_collection.py /import \
  --content-root /work/content --slug my-collection --version v1 \
  --title 'My collection' --price-cents 1900 --preview-count 3
install -d -m 0750 /var/lib/paiddrive/content/support
install -m 0640 "$PD_INCOMING/wechat.png" /var/lib/paiddrive/content/support/wechat.png
sudo chgrp -R 10001 /var/lib/paiddrive/content
sudo find /var/lib/paiddrive/content -type d -exec chmod 0750 {} +
sudo find /var/lib/paiddrive/content -type f -exec chmod 0640 {} +
```

Review `/var/lib/paiddrive/content/collections.json` in your editor. The importer
appends your collection; remove the `slow-days` **manifest entry** before live
launch if you do not intend to sell the demo. Keep the JSON `collections` array
valid. After sales, preserve every sold version's files and IDs; updates need a
new version and directory. Never use `rsync --delete` on this content tree.

Set `SUPPORT_QR_PATH=/app/content/support/wechat.png` in `.env`. Then recreate
the demo container so its private SELinux mount label is applied again:

```bash
sudo docker compose up -d --force-recreate --wait --wait-timeout 180 paid-drive
curl -fsS "http://127.0.0.1:$PD_PORT/health"
```

Through the existing Mac SSH tunnel, open
**http://localhost:8091/c/my-collection** and verify order, price, previews,
simulated unlock, images, ZIP and QR. Treat the incoming directory as private;
remove only that staging copy after confirming the imported files, retaining
your Mac originals. Do not commit real configurations or runtime assets.

## 10. Set the actual trusted proxy source

**CVM:**

```bash
curl -fsS "http://127.0.0.1:$PD_PORT/health"
sudo docker compose logs --tail=30 paid-drive
sudo docker network inspect paid-drive_default --format '{{json .IPAM.Config}}'
```

Identify the immediate connection source in Uvicorn's access log for that
request; with host Nginx through Docker it may be the Docker bridge gateway.
Match it to the actual network. Put `127.0.0.1` and that exact trusted address in
`.env`'s `FORWARDED_ALLOW_IPS`, comma-separated. If it really is loopback only,
the existing value suffices. Do not copy an arbitrary `172.x` example or use `*`.

The Nginx template replaces `X-Forwarded-For` with its own `$remote_addr`. If you
use a CDN/CLB in front, first configure real-client IP handling for its documented
trusted ranges. This guide assumes the documented direct host-Nginx topology.
Recheck trust after Docker network changes. [Uvicorn proxy settings](https://uvicorn.dev/settings/#http).

## 11. Configure real payments and email

**CVM:** edit `/opt/paiddrive/.env` privately. Keep the runtime path settings and
use this table to replace the relevant values:

| Variable | Production value |
| --- | --- |
| `APP_MODE` | `live` |
| `APP_URL` | `https://drive.dolphincoder.cn` — origin only, no path |
| `PAIDDRIVE_PORT` | Your chosen loopback port, normally `8091` |
| `FORWARDED_ALLOW_IPS` | Actual trusted source from Step 10 |
| `ZPAY_BASE_URL` | Current merchant's confirmed HTTPS gateway base URL |
| `ZPAY_PID` | Current merchant ID |
| **`ZPAY_KEY`** | Current merchant key; PaidDrive does **not** read soccer's `ZPAY_MERCHANT_KEY` name |
| `MAIL_MODE` | `smtp`, or deliberately `disabled` if using manual support only |
| `SMTP_HOST`, `SMTP_FROM` | Actual SMTP endpoint and verified sender |
| `SMTP_USER`, `SMTP_PASSWORD` | Actual SMTP authentication, if required |
| `SMTP_PORT`, `SMTP_STARTTLS` | Usually `587` + `true`; implicit TLS uses `465` |
| `SUPPORT_QR_PATH` | `/app/content/support/wechat.png` |

The soccer guide documents `https://zpayz.cn` as its gateway. Verify the current
merchant dashboard/protocol before using that endpoint here. Do not copy
credential strings from documentation, and do not copy soccer's environment
file. PaidDrive sends `submit.php` forms and queries `api.php`; validate both
supported payment channels with your provider.

PaidDrive derives these URLs from `APP_URL`:

| Purpose | PaidDrive URL |
| --- | --- |
| Server notification | `https://drive.dolphincoder.cn/api/payments/zpay/notify` |
| Browser return | `https://drive.dolphincoder.cn/payment/return` |

Add the new domain/callbacks to provider allowlists as required. Preserve soccer's
existing callback; if the merchant account only allows one global callback,
resolve that with the provider or use a separate merchant configuration before
launch. Browser return parameters alone never grant purchase access.

Live mode requires HTTPS and populated ZPay settings; it rejects file email.
`MAIL_MODE=disabled` removes email recovery, so only the current buyer browser
and verified manual support remain. SMTP requires outbound connectivity, not an
inbound SMTP security-group rule. For Compose passwords containing `$`, follow
its [single-quoted literal value rules](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/#env-file-syntax)
in `.env`; never print an expanded configuration containing secrets.

Before switching modes, preserve the demo database/content and private config:

```bash
cd /opt/paiddrive
PD_BACKUP_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
(
  set -eu
  sudo docker compose exec -T paid-drive python scripts/backup.py \
    --output "/data/backups/before-live-$PD_BACKUP_STAMP.tar.gz"
  sudo install -m 0600 .env "$PD_AUDIT_DIR/paiddrive-live.env"
  sudo install -m 0600 compose.override.yaml "$PD_AUDIT_DIR/compose.override.yaml"
  sudo docker compose config --quiet
  sudo docker compose up -d --force-recreate --wait --wait-timeout 180 paid-drive
  sudo docker compose ps
  sudo docker compose logs --tail=50 paid-drive
  curl -fsS "http://127.0.0.1:$PD_PORT/health"
)
```

Expected: **`{"status":"ok","mode":"live"}`**. This confirms startup and
database access, not a real payment or SMTP delivery. Demo purchases do not
become live purchases. Secure production cookies require HTTPS: after this
switch the HTTP tunnel is suitable for health checks, not buyer-flow testing.
If startup fails, fix PaidDrive while the public preparation page stays active.

## 12. Enable the HTTPS site and test it

**CVM:** only after the certificate, real content, support QR and live health
check are ready:

```bash
(
  set -eu
  sudo cp -a /etc/nginx/conf.d/paiddrive.conf "$PD_AUDIT_DIR/paiddrive-http.conf"
  sudo install -m 0644 "$PD_HTTPS_CONF" /etc/nginx/conf.d/paiddrive.conf
  sudo nginx -t
  sudo systemctl reload nginx
)
```

If validation fails, restore `"$PD_AUDIT_DIR/paiddrive-http.conf"` to the
PaidDrive conf path and run `nginx -t` again. Do not restart the shared proxy or
replace its global configuration. If HTTPS gives 502 while loopback health works,
check the PaidDrive Nginx error log and SELinux denials. On an enforcing host,
an actual `name_connect` denial with `httpd_can_network_connect` off may require
`sudo setsebool -P httpd_can_network_connect 1`; confirm the denial first because
this is a host-wide Nginx policy setting. Never turn SELinux off.

**Mac:**

```bash
curl -I http://drive.dolphincoder.cn/
curl -fsS https://drive.dolphincoder.cn/health
curl -i https://drive.dolphincoder.cn/api/payments/zpay/notify
curl -I https://dolphincoder.cn/
curl -I https://132855.cn/
curl -I https://soccer.dolphincoder.cn/matches
```

Expect HTTP→HTTPS redirect, `ok/live`, and **400 with `fail`** for the empty
notification request. That rejection is correct; do not make the notification
endpoint return unconditional success. All existing websites must match their
baseline behavior.

Open **https://drive.dolphincoder.cn/c/my-collection** and complete this acceptance
sequence before sharing the link with buyers:

1. In a fresh browser, verify the first three images are free and the rest locked.
2. Verify a paid image URL and the collection ZIP are denied in that browser.
   For the imported example, fresh unauthenticated GETs to
   `/media/my-collection/v1/004` and `/files/my-collection/v1/download` must return
   403. Removing a UI blur must not reveal downloaded paid pixels.
3. Make one controlled small real purchase through an enabled channel. Match
   the order and amount to the merchant dashboard, not just the return page.
4. Confirm unlock, single-image download, ZIP, refresh and later revisit. Confirm
   a different browser still cannot use the first buyer's paid image/ZIP URLs.
5. With SMTP enabled, verify an address, receive the actual message, and restore
   access in a second browser. Reusing the same recovery link must fail.
6. Test WeChat's embedded browser and your target iPhone/Android browsers. A
   payment may return to a different browser session; use the original session,
   verified email or support. ZIP downloads are files, not automatic album saves.
7. Check support QR recognition on the same phone and retention after a PaidDrive
   container recreation. Confirm external requests from two networks appear as
   different client IPs, rather than one Docker gateway/rate-limit bucket.

For order inspection, **CVM**:

```bash
sudo docker compose exec paid-drive python -m app.admin list-orders --limit 20
```

If refunding the test purchase, refund through the provider first, then revoke
its PaidDrive access as in Step 14. The application does not issue refunds.

## 13. Verify certificate renewal and Nginx reload

**CVM:** inspect existing renewal automation and deploy hooks privately:

```bash
sudo certbot certificates
systemctl list-timers --all
sudo ls -l /etc/letsencrypt/renewal-hooks/deploy
command -v nginx
command -v systemctl
sudo certbot renew --cert-name "$PD_DOMAIN" --dry-run
```

Reuse the existing scheduler. Check its cron configuration if there is no
Certbot timer; do not create a duplicate schedule. Webroot certificates need
Nginx to reload after renewal. Reuse an existing applicable deploy hook if it
already validates and reloads Nginx. If none covers this certificate, create a
new scoped hook using the actual paths returned above. This block refuses an
existing filename and validates the certificate directory and executables:

```bash
sudo python3 - "$PD_DOMAIN" "$(command -v nginx)" "$(command -v systemctl)" <<'PY'
import os
from pathlib import Path
import shlex
import sys
domain, nginx, systemctl = sys.argv[1:]
lineage = Path('/etc/letsencrypt/live') / domain
if not (lineage / 'fullchain.pem').is_file():
    raise SystemExit('Set the actual certificate lineage before creating the hook.')
for executable in (nginx, systemctl):
    if not Path(executable).is_file() or not os.access(executable, os.X_OK):
        raise SystemExit('Executable path is invalid.')
hook = Path('/etc/letsencrypt/renewal-hooks/deploy/paiddrive-reload-nginx.sh')
hook.parent.mkdir(parents=True, exist_ok=True)
q = shlex.quote
script = '\n'.join([
    '#!/bin/sh', 'set -eu',
    '[ "${RENEWED_LINEAGE:-}" = ' + q(str(lineage)) + ' ] || exit 0',
    q(nginx) + ' -t', q(systemctl) + ' reload nginx', '',
])
with hook.open('x') as output:
    output.write(script)
hook.chmod(0o750)
print('Created', hook)
PY
sudo certbot renew --cert-name "$PD_DOMAIN" --dry-run --run-deploy-hooks
```

If Certbot used another lineage name, adjust it before running the hook-creation
block. `--run-deploy-hooks` really runs applicable hooks on a successful test,
so a reload occurs; recheck the existing sites afterward. Keep the ACME location
on port 80 in the final Nginx configuration. [Certbot renewal behavior](https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates).

## 14. Back up and operate the service

**CVM:** backup uses SQLite's consistent backup API and includes the matching
content tree. Freeze content edits while it runs; the application may continue
serving buyers. Do not copy only a live SQLite main file while WAL is active.

```bash
cd /opt/paiddrive
PD_BACKUP_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PD_BACKUP_NAME="paiddrive-$PD_BACKUP_STAMP.tar.gz"
sudo docker compose exec -T paid-drive python scripts/backup.py \
  --output "/data/backups/$PD_BACKUP_NAME"
sudo tar -tzf "/var/lib/paiddrive/data/backups/$PD_BACKUP_NAME"
git rev-parse HEAD
```

Keep that SHA with the backup. `.env`, the Compose override, Nginx configuration
and certificate management configuration need separate private backup. The
database archive itself contains customer/session data and must remain private.

Export just the selected archive to the deployment user's private temporary
directory; this does not change the ownership of the running database:

```bash
PD_EXPORT_DIR="$(mktemp -d /tmp/paiddrive-export.XXXXXX)"
chmod 0700 "$PD_EXPORT_DIR"
sudo install -m 0600 -o "$PD_DEPLOY_USER" -g "$PD_DEPLOY_GROUP" \
  "/var/lib/paiddrive/data/backups/$PD_BACKUP_NAME" "$PD_EXPORT_DIR/$PD_BACKUP_NAME"
sha256sum "$PD_EXPORT_DIR/$PD_BACKUP_NAME"
printf 'Download this file: %s\n' "$PD_EXPORT_DIR/$PD_BACKUP_NAME"
```

**Mac:** replace the source with that exact printed path:

```bash
PD_CVM='YOUR_EXISTING_SSH_USER@119.45.126.188'
mkdir -p /Users/mewtwo/Workspace/PaidDrive-backups
chmod 0700 /Users/mewtwo/Workspace/PaidDrive-backups
scp "$PD_CVM:/tmp/paiddrive-export.REPLACE/paiddrive-REPLACE.tar.gz" \
  /Users/mewtwo/Workspace/PaidDrive-backups/
shasum -a 256 /Users/mewtwo/Workspace/PaidDrive-backups/paiddrive-REPLACE.tar.gz
```

Compare hashes, retain a copy outside the CVM, and remove only the temporary
export when done. Establish a backup frequency appropriate to accepted order
loss; the source package does not install an automatic offsite backup service.

Routine commands, **CVM**:

```bash
cd /opt/paiddrive
sudo docker compose ps
sudo docker compose logs --tail=100 paid-drive
sudo docker compose exec paid-drive python -m app.admin list-orders --limit 20
```

After verifying the purchaser against merchant records, use the actual order
reference with either `python -m app.admin restore --reference ...` or
`python -m app.admin revoke --reference ...` through `docker compose exec
paid-drive`. Restore prints a temporary, single-use private link for a confirmed
paid order; send it only to the verified buyer. Revoke removes access but does
not refund or erase downloads already obtained. An order number alone is not
payment proof; never manually change a pending order to paid.

## 15. Update code and roll back safely

This layout keeps all real content and SQLite outside the checkout. Preserve
`.env` and `compose.override.yaml`; do not run `git clean -fdx`, delete runtime
directories, prune shared Docker images, or stop the Docker daemon.

**CVM:** first make and export the Step 14 backup. Then record the current source,
image and local configuration. `PD_UPDATE_STAMP` identifies this update only:

```bash
cd /opt/paiddrive
PD_UPDATE_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PD_UPDATE_DIR="/var/backups/paiddrive-update-$PD_UPDATE_STAMP"
sudo install -d -m 0700 "$PD_UPDATE_DIR"
git rev-parse HEAD | sudo tee "$PD_UPDATE_DIR/source-sha.txt" >/dev/null
PD_CONTAINER="$(sudo docker compose ps -q paid-drive)"
PD_OLD_IMAGE="$(sudo docker inspect --format '{{.Image}}' "$PD_CONTAINER")"
PD_ROLLBACK_IMAGE="paiddrive:before-$PD_UPDATE_STAMP"
sudo docker image tag "$PD_OLD_IMAGE" "$PD_ROLLBACK_IMAGE"
printf '%s\n' "$PD_ROLLBACK_IMAGE" | sudo tee "$PD_UPDATE_DIR/image-tag.txt" >/dev/null
sudo install -m 0600 .env "$PD_UPDATE_DIR/paiddrive.env"
sudo install -m 0600 compose.override.yaml "$PD_UPDATE_DIR/compose.override.yaml"
sudo cp -a /etc/nginx/conf.d/paiddrive.conf "$PD_UPDATE_DIR/paiddrive.conf"
git status --short
git fetch origin main
git log --oneline HEAD..origin/main
git diff --stat HEAD origin/main
```

Inspect the changes and their release instructions, especially database or
configuration changes. There is no general migration/downgrade framework in
this MVP. Resolve uncommitted code changes instead of discarding them. Choose
the reviewed full commit SHA, then:

```bash
PD_NEW_SHA='REPLACE_WITH_REVIEWED_FULL_COMMIT_SHA'
(
  set -eu
  git checkout --detach "$PD_NEW_SHA"
  sudo docker compose config --quiet
  sudo docker compose build paid-drive
)
```

Run the new release's tests in an isolated container without production mounts.
For this release's suite, the following uses only disposable container storage
and read-only test/template mounts; it does not relabel live data or content:

```bash
(
  set -eu
  sudo docker run --rm --network none --read-only \
    --tmpfs /tmp:mode=1777 --entrypoint python \
    -v "$PWD/tests:/app/tests:ro,Z" \
    -v "$PWD/deploy:/app/deploy:ro,Z" \
    paiddrive:local -m unittest discover -s tests -v
  sudo docker compose up -d --no-build --force-recreate --wait --wait-timeout 180 paid-drive
  sudo docker compose ps
  curl -fsS "http://127.0.0.1:$PD_PORT/health"
)
```

Recheck a pre-existing paid order, anonymous denial, downloads, mail and the
other sites. A single-worker restart has a brief interruption; this is not a
zero-downtime release process. New content versions are separate operator
imports into `/var/lib/paiddrive/content`, preserving old originals.

**Code rollback, only if the database remains compatible:** restore the previous
code checkout and image without restoring an old order database. If configuration
changed, compare the saved private files before restoring the applicable values.

```bash
cd /opt/paiddrive
(
  set -eu
  PD_OLD_SHA="$(sudo cat "$PD_UPDATE_DIR/source-sha.txt")"
  PD_ROLLBACK_IMAGE="$(sudo cat "$PD_UPDATE_DIR/image-tag.txt")"
  git checkout --detach "$PD_OLD_SHA"
  sudo docker image tag "$PD_ROLLBACK_IMAGE" paiddrive:local
  sudo docker compose config --quiet
  sudo docker compose up -d --no-build --force-recreate --wait --wait-timeout 180 paid-drive
  curl -fsS "http://127.0.0.1:$PD_PORT/health"
)
```

Retagging only the dedicated `paiddrive:local` image leaves the immutable rollback
tag available. Do not rebuild during rollback. Do not restore an old database
merely to roll back code: it could erase payments received since that backup.

## 16. Restore a backup when data recovery is actually necessary

First decide the recovery point and how to reconcile payments since that point.
Record the current source/image/configuration and preserve the current data even
if damaged. Pause public sales by restoring the PaidDrive HTTP preparation site;
if HTTPS was already active, retain its certificate and return 503 in its HTTPS
`location /` as well, rather than allowing the shared default HTTPS site to
answer for this hostname. Validate and reload Nginx before stopping PaidDrive.

Then, **CVM**, using only your own trusted backup:

```bash
cd /opt/paiddrive
sudo docker compose stop paid-drive
PD_RESTORE_DIR="$(mktemp -d /tmp/paiddrive-restore.XXXXXX)"
chmod 0700 "$PD_RESTORE_DIR"
PD_RESTORE_ARCHIVE='/absolute/path/to/your-selected-paiddrive-backup.tar.gz'
sudo tar -tzf "$PD_RESTORE_ARCHIVE"
sudo tar -xzf "$PD_RESTORE_ARCHIVE" -C "$PD_RESTORE_DIR" --no-same-owner
sudo docker run --rm --network none --read-only --user 0:0 --entrypoint python \
  -v "$PD_RESTORE_DIR:/restore:ro,Z" paiddrive:local -c \
  "import sqlite3; c=sqlite3.connect('file:/restore/data/paiddrive.sqlite3?mode=ro', uri=True); r=c.execute('PRAGMA integrity_check').fetchone(); print(r); assert r==('ok',)"
```

Check `backup.json`, the recorded source SHA and the matching content tree.
Stop if integrity is not `ok`. Once you have resolved the recovery-point and
later-transaction questions, move the current directories aside rather than
deleting them, restore into new empty directories, and recreate the container:

```bash
PD_RECOVERY_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
(
  set -eu
  test ! -e "/var/lib/paiddrive/data-before-$PD_RECOVERY_STAMP"
  test ! -e "/var/lib/paiddrive/content-before-$PD_RECOVERY_STAMP"
  sudo mv /var/lib/paiddrive/data "/var/lib/paiddrive/data-before-$PD_RECOVERY_STAMP"
  sudo mv /var/lib/paiddrive/content "/var/lib/paiddrive/content-before-$PD_RECOVERY_STAMP"
  sudo cp -a "$PD_RESTORE_DIR/data" /var/lib/paiddrive/data
  sudo cp -a "$PD_RESTORE_DIR/content" /var/lib/paiddrive/content
  sudo chown -R 10001:10001 /var/lib/paiddrive/data
  sudo chmod 0700 /var/lib/paiddrive/data
  sudo chmod 0600 /var/lib/paiddrive/data/paiddrive.sqlite3
  sudo install -d -m 0700 -o 10001 -g 10001 /var/lib/paiddrive/data/tmp
  sudo chown -R "$PD_DEPLOY_USER":10001 /var/lib/paiddrive/content
  sudo find /var/lib/paiddrive/content -type d -exec chmod 0750 {} +
  sudo find /var/lib/paiddrive/content -type f -exec chmod 0640 {} +
)
```

Before starting, select the matching compatible source/image and private `.env`/
override. The snapshot contains no old WAL/SHM files; do not copy any in from
the quarantined directory. Preserve any newer sold content versions while
reconciling later orders. If a support image was backed up separately, restore
it to the configured private location as well.

```bash
sudo docker compose up -d --no-build --force-recreate --wait --wait-timeout 180 paid-drive
curl -fsS "http://127.0.0.1:$PD_PORT/health"
sudo docker compose exec paid-drive python -m app.admin list-orders --limit 20
```

Validate known orders and content before reopening the final HTTPS proxy. Keep
the quarantined state and backup until recovery is accepted.

## 17. Troubleshooting

| Symptom | Check and action |
| --- | --- |
| Private clone denied | Correct repository identity/deploy key; Mac authentication does not authenticate the CVM |
| GitHub, Docker Hub or PyPI download fails | DNS/outbound reachability and existing trusted network route; keep unrelated services running |
| Container cannot read originals | UID/GID 10001, directory traversal and SELinux label; check actual runtime `/var/lib/paiddrive/content` |
| SQLite read-only / permission denied | `/var/lib/paiddrive/data` ownership, mount and disk space; do not chmod it 777 |
| 503 on the new HTTP site before launch | Expected ACME preparation behavior |
| ACME fails | Public port 80, A/AAAA, challenge file, Nginx site selection and webroot SELinux label |
| 502 after launch | Loopback health first, then PaidDrive Nginx logs and actual SELinux network denials |
| Live startup rejected | HTTPS APP_URL, ZPay base/ID/key, SMTP or disabled email, support image path |
| Everyone is rate-limited together | Observed Docker proxy source and `FORWARDED_ALLOW_IPS`; verify actual external client IPs |
| Paid at provider but not unlocked | Order matching, signature/query result, merchant amount and notification reachability; never trust the browser return alone |
| Email missing | SMTP credentials/TLS, outbound port, verified sender and spam; queueing is not delivery |
| Purchase missing in another browser | Different session; verified email recovery or manually verified support |
| Paid image returns 410 | Sold-version bytes/files changed; restore exact originals and create a new version for new content |
| ZIP/backup fails | Free disk under `/var/lib/paiddrive/data/tmp`, concurrent archive sizes and permissions |
| New subdomain displays another site | DNS record, duplicate server_name, loaded conf.d file, TLS/SNI and successful reload |
| Another site regresses | Compare baseline; undo only this deployment's new Nginx/service changes |

Source and official-reference details are recorded in
[CVM_DEPLOYMENT_RESEARCH.md](CVM_DEPLOYMENT_RESEARCH.md). Current software
verification results are in [VALIDATION.md](../VALIDATION.md); deployment,
real payments, real SMTP and phone acceptance still need the steps above.
