# Deployment — Tencent Cloud CVM (co-tenant, Docker Compose)

Runbook for standing **PaidDrive** (FastAPI / Python 3.12 / SQLite, in Docker) up
on the **existing, already-busy** Tencent Cloud CVM that serves the soccer
project, on a **new subdomain** of a domain whose ICP filing is already approved.

This is **not** a fresh-box install. The CVM already runs three sites; we slot
PaidDrive in **next to them** without disturbing anything that already works.

> **Companion docs:** the primary-source facts behind these steps →
> [`CVM_DEPLOYMENT_RESEARCH.md`](CVM_DEPLOYMENT_RESEARCH.md); the local dev box →
> [`MAC_WORKSPACE_SETUP.md`](MAC_WORKSPACE_SETUP.md); what the code itself has
> been verified to do → [`VALIDATION.md`](../VALIDATION.md). Redeploy, restore,
> troubleshooting and the security checklist are at the bottom of this file.

> **Nothing has been deployed yet.** PaidDrive has never run on this CVM, and the
> box facts below are copied from the soccer project's `docs/DEPLOYMENT-TENCENT.md`
> — **not** from a live inspection. Step 1 re-verifies every one of them. The
> commands here are instructions, not a log of commands already run.

---

## This box, as found (`119.45.126.188`, TencentOS Server 3.3)

TencentOS 3.x is **RHEL 8-compatible** — `dnf`, nginx `conf.d/`, `firewalld`, and
**SELinux enforcing**. Docker Engine, nginx and certbot are already installed and
already in use, so PaidDrive adds **no new runtime to the host**.

**Already running — DO NOT TOUCH:**

| Port    | Process               | Site / role                    |
|---------|-----------------------|--------------------------------|
| 80, 443 | nginx (host)          | front door for every site below |
| 8000    | uvicorn (Python)      | `dolphincoder.cn`              |
| 8080    | Docker container      | `132855.cn`                    |
| 8090    | Spring Boot (systemd) | `soccer.dolphincoder.cn`       |
| 5432    | Postgres (Docker)     | the Python app's DB            |
| 22      | sshd                  | SSH                            |

**What PaidDrive adds:**

| Resource          | PaidDrive's slot |
|-------------------|------------------|
| Application port  | **`127.0.0.1:8091`** — never public |
| Runtime           | the **existing** Docker Engine; its own Compose project `paid-drive` |
| Source checkout   | `/opt/paiddrive` (pinned commit, detached HEAD) |
| Persistent state  | `/var/lib/paiddrive/data` (SQLite) and `/var/lib/paiddrive/content` (paid originals) |
| Private config    | `/opt/paiddrive/.env` + `compose.override.yaml`, both `0600` |
| Nginx             | **one added file**, `/etc/nginx/conf.d/paiddrive.conf` |
| Certificate       | a new certbot lineage for the new hostname |

**Nothing to install:** PaidDrive uses **SQLite** — no MySQL, no Redis, no Java,
no host Python runtime. Host `python3` renders the nginx config and nothing else;
the app, its tests, the importer and the backup all run inside the Python 3.12
image.

> **Design decision — separation of concerns.** nginx owns the shared HTTPS entry
> point, Docker supplies the runtime, and orders/originals live outside the Git
> checkout so a code update can never replace them.

---

## Target architecture

```
Internet ─▶ Nginx :80 / :443 ─┬─ dolphincoder.cn        ─▶ uvicorn      127.0.0.1:8000  (existing)
                              ├─ 132855.cn              ─▶ docker       127.0.0.1:8080  (existing)
                              ├─ soccer.dolphincoder.cn ─▶ Spring Boot  127.0.0.1:8090  (existing)
                              └─ drive.dolphincoder.cn  ─▶ docker       127.0.0.1:8091  (NEW)
                                                            │ paid-drive: UID/GID 10001,
                                                            │ read-only rootfs, cap_drop ALL
                                                            ├─▶ /var/lib/paiddrive/data    (SQLite, rw)
                                                            └─▶ /var/lib/paiddrive/content (originals, ro)
```

- 8091 is published **on loopback only** (`127.0.0.1:8091:8000`) — no Security
  Group change, ever.
- Demo mode stays behind an SSH tunnel. **Never** serve `APP_MODE=demo` through
  nginx: simulated payment unlocks any loaded collection.
- Paid bytes are served by FastAPI *after* an access check. Never add an nginx
  `root`/`alias` for the content tree.

---

## Placeholders

| Placeholder | Meaning / value here |
|-------------|----------------------|
| `NEW_CVM_IP` | `119.45.126.188` (the shared CVM) |
| `$PD_DOMAIN` | `drive.dolphincoder.cn` (the subdomain we serve) |
| `$PD_PORT` | `8091` (loopback app port) |
| `$PD_CVM` | `YOUR_EXISTING_SSH_USER@119.45.126.188` — the account/key that already works for soccer |
| `$PD_AUDIT_DIR` | this deployment's rollback baseline, `/var/backups/paiddrive-<stamp>` — **record it** |
| `REPLACE_WITH_*` | a value you must fill in from printed output |

Unless a block is marked **Mac** or **Console**, **commands run on the CVM over
SSH as a sudo-capable user.** Run one block at a time and stop on an unexpected
error. The shell variables above live in that SSH session — **re-enter them after
every reconnect.**

> Carry your existing key/port options on both `ssh` and `scp`: a custom port is
> `ssh -p` but **`scp -P`**. The examples assume port 22 and your default identity.

---

## Step 0 — Pre-flight (read once)

1. **ICP — already covered.** `dolphincoder.cn` already serves 80/443 from this
   mainland CVM, so its 备案 is already 接入'd to Tencent. A **二级域名** of an
   already-filed domain needs **no new filing** — you only add a DNS record
   (Step 7). Confirm the parent domain's current filing/access status in the
   console anyway; the soccer doc's statement is not a fresh check.
   [Tencent subdomain filing guidance](https://cloud.tencent.com/document/product/243/19630)
2. **You are co-tenant.** Three sites must keep working the entire time. Every
   step below is **additive**. If a command would edit another site's nginx file,
   soccer's systemd unit, or the shared Docker daemon config, you've gone
   off-script.
3. **This box is SELinux-enforcing with rootful Docker.** Bind mounts carry `:Z`
   private labels. Never relabel another site's directories, and never turn
   SELinux off.
4. **Money and paid files only become real at Step 11.** Steps 1–10 are private:
   demo mode, SSH tunnel, and a public 503 holding page. The site opens to buyers
   in Step 12, after acceptance.
5. **Your Mac keeps the masters.** The CVM holds a working copy of the paid
   images, not the only copy.

---

## Step 1 — Verify the shared box, save a rollback baseline

**Mac** — log in with the account/key that already works for soccer:

```bash
PD_CVM='YOUR_EXISTING_SSH_USER@119.45.126.188'
ssh "$PD_CVM"
```

> The soccer doc shows `root@119.45.126.188` in a transfer example. That is not a
> reason to log in as root.

**CVM** — set this session's variables (re-enter them after any reconnect):

```bash
bash
PD_DOMAIN='drive.dolphincoder.cn'
PD_PORT='8091'
PD_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PD_AUDIT_DIR="/var/backups/paiddrive-$PD_STAMP"
PD_DEPLOY_USER="$(id -un)"
PD_DEPLOY_GROUP="$(id -gn)"
printf 'Audit directory: %s\n' "$PD_AUDIT_DIR"      # record this value for recovery
```

Re-verify the box — the soccer doc's RAM/disk figures are historical, so trust
this output instead:

```bash
cat /etc/os-release; uname -m; id        # RHEL8-compatible, arch, your sudo rights
df -h / /var /tmp; free -h               # room for originals + ZIPs + snapshots
sudo ss -lntp                            # nginx owns 80/443, soccer 8090, 8091 FREE
sudo systemctl is-active nginx soccer-match-analyzer     # active, active
sudo nginx -t                            # must already pass before you add anything
sudo docker version                      # Engine present
sudo docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
sudo docker info --format '{{json .SecurityOptions}}'    # expect rootful, NO userns
sudo certbot --version
getenforce                               # expect Enforcing
sudo getsebool httpd_can_network_connect # nginx already proxies :8000/:8080/:8090
```

- **8091 must be unused.** If it is taken, pick a free port and change `PD_PORT`,
  `.env`, the nginx render and **both ends** of the SSH tunnel consistently.
- **UID/GID mapping:** this runbook assumes **rootful Docker with no
  user-namespace remapping**, so container `10001` is host `10001`. If
  `docker info` reports `rootless` or `userns`, adapt the bind-mount ownership to
  the real mapping — do **not** reconfigure the shared daemon to suit this guide.
- **Engine age:** before Engine 28, a localhost-published port could be reachable
  from same-layer-2 peers
  ([port-publishing caveat](https://docs.docker.com/engine/network/port-publishing/)).
  Resolve any such exposure **before** loading paid originals, and plan an Engine
  upgrade separately from this deployment.
- **Firewall:** leave it as-is. Confirm the Tencent Security Group still permits
  public 80/443 and your existing restricted SSH. PaidDrive needs no public 8091,
  SQLite, SMTP or Docker port.

Save the rollback baseline, then confirm `conf.d/*.conf` is included and that
`drive.dolphincoder.cn` is not already claimed:

```bash
sudo install -d -m 0700 "$PD_AUDIT_DIR"
sudo tar -czf "$PD_AUDIT_DIR/nginx-before.tar.gz" -C /etc nginx
sudo bash -c 'nginx -T > "$1/nginx-before.txt" 2>&1' _ "$PD_AUDIT_DIR"
sudo bash -c 'docker ps --no-trunc > "$1/containers-before.txt"' _ "$PD_AUDIT_DIR"
sudo grep -n 'conf\.d\|server_name' "$PD_AUDIT_DIR/nginx-before.txt" | head -40
```

> Read those files **on the server**. Do not paste whole server configurations or
> private environment files into a chat.

**Mac** — record the baseline the other three sites must still match in Step 12:

```bash
curl -I https://dolphincoder.cn/
curl -I https://132855.cn/
curl -I https://soccer.dolphincoder.cn/matches
```

---

## Step 2 — Docker Compose plugin (verify; install only if absent)

```bash
sudo docker compose version      # if this works, keep it and go to Step 3
sudo docker compose ls
command -v git; python3 --version
```

If `git` or `python3` is missing, install **only** that one utility with
TencentOS's `dnf`, reviewing the transaction first.

If Compose is absent, install **only its CLI plugin** — never reinstall, upgrade
or restart the shared daemon. This pins [Compose **v5.7.0**](https://github.com/docker/compose/releases/tag/v5.7.0),
verifies its digest, and refuses to overwrite an existing plugin
([install docs](https://docs.docker.com/compose/install/linux/)):

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

> A manual plugin does **not** auto-update, and a client/Engine compatibility
> error is a decision about the shared Engine — never a reason to auto-upgrade the
> daemon. Reuse a working plugin at another path instead of duplicating it. If the
> download is blocked, fetch and checksum it from the same official source on your
> Mac and transfer it — never an unknown mirror or a piped remote installer.

---

## Step 3 — Deploy key for the private repository

Repository: [mjmonster/paid-drive](https://github.com/mjmonster/paid-drive). **Your
Mac's working GitHub login does not authenticate the CVM.** If the CVM already
has an identity authorized for *this* repository, verify it and skip the key:

```bash
git ls-remote git@github.com:mjmonster/paid-drive.git refs/heads/main
# a commit SHA + refs/heads/main = done; then use PD_GIT_SSH='ssh' in Step 4
```

> A deploy key is scoped to one repository: soccer's existing deploy key **cannot**
> be reused here.

Otherwise create a dedicated read-only key as the deployment user:

```bash
install -d -m 0700 "$HOME/.ssh"
PD_KEY="$HOME/.ssh/paiddrive_deploy_ed25519"
(
  set -eu
  test ! -e "$PD_KEY"
  test ! -e "$PD_KEY.pub"
  ssh-keygen -t ed25519 -C 'paid-drive CVM read-only deploy key' -f "$PD_KEY"
)
cat "$PD_KEY.pub"          # copy ONLY this public line
```

Choose a passphrase according to your server's key policy; enter it interactively
when Git needs it, or load the key into your existing agent. The private file
stays on the CVM.

**GitHub Console:** repository → Settings → Deploy keys → Add deploy key. Name it
`Tencent CVM PaidDrive`, paste the public key, and leave **Allow write access
unchecked**
([GitHub deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys)).

Bind the new key to this repository only — do not replace `~/.ssh/config` or your
other keys:

```bash
PD_GIT_SSH="ssh -i $PD_KEY -o IdentitiesOnly=yes"
GIT_SSH_COMMAND="$PD_GIT_SSH" git ls-remote \
  git@github.com:mjmonster/paid-drive.git refs/heads/main   # SHA + refs/heads/main
```

> On first connection, compare the offered host-key fingerprint against
> [GitHub's published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints)
> before accepting. Never disable SSH host-key verification.

---

## Step 4 — Clone and pin the source release

Both paths must be new. If either exists, stop and inspect it — an existing
deployment belongs in [Redeploying](#redeploying-after-code-changes), not in this
first install.

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
  git rev-parse HEAD                      # record this SHA
)
cd /opt/paiddrive
```

> **Why detached:** the deployed version is pinned deliberately rather than
> tracking `main`. That commit is the 47-file initial source release already
> verified against your Mac — app, Docker configuration, sample images, tests and
> deployment helpers. Later updates select another reviewed commit.

Do not run the Mac workspace installer on the CVM.

---

## Step 5 — Private configuration and persistent directories

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

> **Why an override file:** Compose merges it into `compose.yaml`, and volumes
> merge **by container target** — so these two replace the repo's `./data` and
> `./content` bindings. It is local config, excluded from Git, and it pins the
> image tag and moves temp ZIPs and SQLite snapshots off RAM-backed `/tmp`.

> **Why `:Z`:** a private SELinux label for these dedicated directories; `:ro,Z`
> also makes originals read-only to the app. Never relabel another site's
> directories; never disable SELinux. One-off Compose commands are fine before
> startup — **after** it, inspect via `compose exec` so a second container does not
> relabel the live mounts.
> [Bind-mount labels](https://docs.docker.com/engine/storage/bind-mounts/#configure-the-selinux-label)

Provision disk for originals, concurrent ZIPs, DB snapshots and backup archives.

Edit `.env` with your preferred editor (`vi .env`). Start in **demo**:

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

Keep the other sample settings — Compose supplies the container paths for SQLite,
content and mail. If you chose another port, change **both** `APP_URL` and
`PAIDDRIVE_PORT`.

> Do **not** copy soccer's environment file or its credential examples. Validate
> with `docker compose config --quiet`, never with a command that prints the
> expanded configuration and its secrets.

---

## Step 6 — Build, run the tests, start the private demo

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

Expect **38 tests passed** on the pinned release. The suite uses temporary
databases and mocked payments — no customer is charged, no real mail is sent. The
extra mounts are needed because the runtime image carries neither `tests/` nor
`deploy/`.

> Resolve any failed download, build or test before continuing. If Docker Hub or
> PyPI is unreachable, use the box's established trusted route — do not modify the
> shared daemon to try an arbitrary mirror.

Prove the mounts are readable as the image's real UID 10001, then start:

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
curl -fsS "http://127.0.0.1:$PD_PORT/health"      # {"status":"ok","mode":"demo"}
sudo docker compose port paid-drive 8000          # 127.0.0.1:8091
)
```

Allow the health check time to go healthy. Docker restarts it via
`unless-stopped` — do **not** add a second systemd service or a stray host Uvicorn.

**Mac, separate terminal** — keep this tunnel open:

```bash
PD_CVM='YOUR_EXISTING_SSH_USER@119.45.126.188'
ssh -N -L 8091:127.0.0.1:8091 "$PD_CVM"
```

Open **http://localhost:8091/c/slow-days** and walk the flow: three free
previews, a locked fourth card, the labelled simulated payment, unlock, single
download, ZIP, refresh, revisit. Email recovery can be tested through the private
file-mail outbox; it sends nothing real.

> **Never expose demo mode through nginx** — simulated payment can unlock any
> loaded collection.

---

## Step 7 — DNS record and the ACME preparation site

**Tencent DNSPod Console** → the existing `dolphincoder.cn` zone. Check whether
`drive` already exists before changing anything. For an unused hostname, **add**:

| 主机记录 (Host) | 记录类型 (Type) | 记录值 (Value)   | TTL |
|-----------------|-----------------|------------------|-----|
| `drive`         | `A`             | `119.45.126.188` | 600 |

Keep the existing `@`, `soccer` and other records. Do not add AAAA without a
working IPv6 destination.

**CVM** — render and install the HTTP preparation vhost. The renderer uses only
the Python 3 standard library and refuses to overwrite an existing output file:

```bash
cd /opt/paiddrive
sudo install -d -m 0755 /var/www/paiddrive-acme/.well-known/acme-challenge
sudo restorecon -RF /var/www/paiddrive-acme
PD_HTTP_CONF="/tmp/paiddrive-http-$PD_STAMP.conf"
python3 scripts/render_deploy_config.py --domain "$PD_DOMAIN" \
  --phase http --port "$PD_PORT" --output "$PD_HTTP_CONF"
cat "$PD_HTTP_CONF"                       # review before installing
(
  set -eu
  test ! -e /etc/nginx/conf.d/paiddrive.conf
  sudo install -m 0644 "$PD_HTTP_CONF" /etc/nginx/conf.d/paiddrive.conf
  sudo nginx -t                           # must pass; no reload happens otherwise
  sudo systemctl reload nginx
)
printf 'paiddrive-acme-ok\n' | sudo tee \
  /var/www/paiddrive-acme/.well-known/acme-challenge/paiddrive-check >/dev/null
```

> If `nginx -t` fails, nothing is reloaded and the existing workers keep serving
> the current configuration. Fix the new file, or move **only** PaidDrive's new
> file into `$PD_AUDIT_DIR`, then validate again.

**Mac:**

```bash
dig +short A drive.dolphincoder.cn        # 119.45.126.188
dig +short AAAA drive.dolphincoder.cn     # empty unless you really run IPv6
curl -fsS http://drive.dolphincoder.cn/.well-known/acme-challenge/paiddrive-check
                                          # paiddrive-acme-ok
curl -i http://drive.dolphincoder.cn/     # 503 — the intended holding page
curl -I https://soccer.dolphincoder.cn/matches    # unchanged
```

The 503 is correct: the application is still private, and HTTP-01 validation only
needs port 80.
[Let's Encrypt HTTP-01](https://letsencrypt.org/docs/challenge-types/#http-01-challenge)

---

## Step 8 — Obtain the HTTPS certificate (webroot)

**CVM** — reuse the existing certbot installation. Webroot gets the certificate
without letting certbot rewrite any site's nginx configuration:

```bash
sudo certbot certificates                 # inspect what already exists first
sudo certbot certonly --webroot --webroot-path /var/www/paiddrive-acme \
  --cert-name "$PD_DOMAIN" -d "$PD_DOMAIN"
sudo certbot certificates                 # confirm the exact hostname + real paths
```

Follow certbot's account/email prompts. Normal paths are
`/etc/letsencrypt/live/drive.dolphincoder.cn/fullchain.pem` and `privkey.pem`.

> If a certificate with this name already existed, inspect it before issuance —
> do not overwrite an unrelated lineage.

Render the final proxy configuration, but **do not install it yet**:

```bash
PD_HTTPS_CONF="/tmp/paiddrive-https-$PD_STAMP.conf"
python3 scripts/render_deploy_config.py --domain "$PD_DOMAIN" \
  --phase https --port "$PD_PORT" --output "$PD_HTTPS_CONF"
cat "$PD_HTTPS_CONF"
```

If certbot reported different paths, edit **only** the two certificate paths in
the generated file. The HTTP preparation site stays active until Step 12.

> The HTTPS template routes every application/media request through FastAPI. Do
> **not** add a static `root` or `alias` for the paid originals.

---

## Step 9 — Load your real collection and support QR code

Required before selling your own content: the repository ships nine generated
sample SVGs and a deliberately non-scannable support placeholder.

**CVM** — stop only PaidDrive while content changes, and record the printed path:

```bash
cd /opt/paiddrive
sudo docker compose stop paid-drive
PD_INCOMING="$(mktemp -d /tmp/paiddrive-images.XXXXXX)"
chmod 0700 "$PD_INCOMING"
printf 'Upload destination: %s\n' "$PD_INCOMING"
```

**Mac** — upload the source images and the real support QR, replacing the remote
directory with the exact value printed above. `scp -r` creates an `Images`
subdirectory inside it, and supported image files must sit **directly** in the
folder you select. Use at least four images so three can be free previews:

```bash
PD_CVM='YOUR_EXISTING_SSH_USER@119.45.126.188'
PD_REMOTE_INCOMING='/tmp/paiddrive-images.REPLACE_WITH_PRINTED_SUFFIX'
scp -r /Users/mewtwo/Images "$PD_CVM:$PD_REMOTE_INCOMING/"
scp /absolute/path/to/your-real-wechat-qr.png \
  "$PD_CVM:$PD_REMOTE_INCOMING/wechat.png"
```

> Confirm the QR really identifies your intended support account. If it is a
> JPEG, keep its real extension and use that path consistently — renaming does
> not convert the format.

**CVM** — import with the built image, not TencentOS's system Python. The importer
copies files, sorts names naturally, and refuses an existing collection version.
Set title, slug and price first (`1900` = CNY 19.00), and choose the first three
images deliberately — those are the free previews:

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

Review `/var/lib/paiddrive/content/collections.json`. The importer **appends**
your collection; if you will not sell the demo, remove the `slow-days` **manifest
entry**, keeping the `collections` array valid.

> **Sold content is immutable.** After any sale, preserve every sold version's
> files and IDs — new content means a new version and a new directory. Never run
> `rsync --delete` against this tree.

Set `SUPPORT_QR_PATH=/app/content/support/wechat.png` in `.env`, then recreate the
container so the private SELinux mount label is reapplied:

```bash
sudo docker compose up -d --force-recreate --wait --wait-timeout 180 paid-drive
curl -fsS "http://127.0.0.1:$PD_PORT/health"      # {"status":"ok","mode":"demo"}
```

Through the tunnel, open **http://localhost:8091/c/my-collection** and verify
order, price, previews, simulated unlock, images, ZIP and QR. The incoming
directory is private: once the import is confirmed remove only that staging copy,
keeping your Mac originals. Never commit real config or runtime assets.

---

## Step 10 — Pin the actual trusted proxy source

```bash
curl -fsS "http://127.0.0.1:$PD_PORT/health"
sudo docker compose logs --tail=30 paid-drive
sudo docker network inspect paid-drive_default --format '{{json .IPAM.Config}}'
```

Find the **immediate** connection source for that request in Uvicorn's access log
— with host nginx through Docker it is often the bridge gateway, not loopback —
and match it to the network above. Put `127.0.0.1` **and** that exact address in
`.env`'s `FORWARDED_ALLOW_IPS`, comma-separated; if it really is loopback only,
the existing value suffices.

> Never copy an arbitrary `172.x` example, and never use `*`.

The template replaces `X-Forwarded-For` with its own `$remote_addr`. Putting a
CDN/CLB in front later means configuring real-client-IP handling for its
documented trusted ranges first — this runbook assumes direct host nginx. Recheck
after any Docker network change.
[Uvicorn proxy settings](https://uvicorn.dev/settings/#http)

---

## Step 11 — Configure real payments and email

**CVM** — edit `/opt/paiddrive/.env` privately. Keep the runtime path settings and
replace these:

| Variable | Production value |
|----------|------------------|
| `APP_MODE` | `live` |
| `APP_URL` | `https://drive.dolphincoder.cn` — origin only, no path |
| `PAIDDRIVE_PORT` | your chosen loopback port, normally `8091` |
| `FORWARDED_ALLOW_IPS` | the actual trusted source from Step 10 |
| `ZPAY_BASE_URL` | your merchant's confirmed HTTPS gateway base URL |
| `ZPAY_PID` | your merchant ID |
| **`ZPAY_KEY`** | your merchant key. PaidDrive does **not** read soccer's `ZPAY_MERCHANT_KEY` name |
| `MAIL_MODE` | `smtp`, or deliberately `disabled` for manual support only |
| `SMTP_HOST`, `SMTP_FROM` | actual SMTP endpoint and verified sender |
| `SMTP_USER`, `SMTP_PASSWORD` | actual SMTP authentication, if required |
| `SMTP_PORT`, `SMTP_STARTTLS` | usually `587` + `true`; implicit TLS uses `465` |
| `SUPPORT_QR_PATH` | `/app/content/support/wechat.png` |

> The soccer guide documents `https://zpayz.cn` — verify your current merchant
> dashboard and protocol before using that endpoint here. Never copy credential
> strings out of documentation, or soccer's env file. PaidDrive posts `submit.php`
> forms and queries `api.php`; validate both channels with your provider.

PaidDrive derives its callbacks from `APP_URL`:

| Purpose | PaidDrive URL |
|---------|---------------|
| Server notification | `https://drive.dolphincoder.cn/api/payments/zpay/notify` |
| Browser return | `https://drive.dolphincoder.cn/payment/return` |

Add the new domain and callbacks to the provider allowlists, **preserving
soccer's existing callback**. If the account allows only one global callback,
settle that with the provider or use a separate merchant configuration before
launch. Browser return parameters alone never grant purchase access.

Live mode requires HTTPS and populated ZPay settings, and rejects file email.
`MAIL_MODE=disabled` leaves only the buyer's current browser and verified manual
support. SMTP needs **outbound** connectivity, not an inbound rule. For Compose
passwords containing `$`, follow its
[single-quoted literal value rules](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/#env-file-syntax).

Preserve the demo state and private config, then switch modes:

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
  curl -fsS "http://127.0.0.1:$PD_PORT/health"    # {"status":"ok","mode":"live"}
)
```

That confirms startup and database access — not a real payment or SMTP delivery.
Demo purchases do **not** become live purchases. Production cookies require HTTPS,
so the tunnel now serves health checks, not buyer-flow testing.

> If startup fails, fix PaidDrive while the public 503 preparation page stays up.

---

## Step 12 — Enable the HTTPS site and run acceptance

**CVM** — only once the certificate, real content, support QR and live health
check are all ready:

```bash
(
  set -eu
  sudo cp -a /etc/nginx/conf.d/paiddrive.conf "$PD_AUDIT_DIR/paiddrive-http.conf"
  sudo install -m 0644 "$PD_HTTPS_CONF" /etc/nginx/conf.d/paiddrive.conf
  sudo nginx -t
  sudo systemctl reload nginx
)
```

> If validation fails, restore `"$PD_AUDIT_DIR/paiddrive-http.conf"` to the
> PaidDrive conf path and run `nginx -t` again. Never restart the shared proxy or
> replace its global configuration.

> **502 while loopback health is fine:** check PaidDrive's nginx error log and
> actual SELinux denials. A real `name_connect` denial with
> `httpd_can_network_connect` off needs
> `sudo setsebool -P httpd_can_network_connect 1` — confirm the denial first,
> because that is a host-wide nginx policy setting. Never turn SELinux off.

**Mac:**

```bash
curl -I http://drive.dolphincoder.cn/              # 301 → https
curl -fsS https://drive.dolphincoder.cn/health     # {"status":"ok","mode":"live"}
curl -i https://drive.dolphincoder.cn/api/payments/zpay/notify   # 400 + fail
curl -I https://dolphincoder.cn/                   # matches Step 1 baseline
curl -I https://132855.cn/                         # matches Step 1 baseline
curl -I https://soccer.dolphincoder.cn/matches      # matches Step 1 baseline
```

The `400 fail` for an empty notification is **correct** — never make that endpoint
return unconditional success. All three existing sites must match their baseline.

Open **https://drive.dolphincoder.cn/c/my-collection** and complete this
acceptance sequence before giving the link to any buyer:

1. In a fresh browser: the first three images are free, the rest locked.
2. In that same browser, a paid image URL and the ZIP are denied. For the
   imported example, fresh unauthenticated GETs of
   `/media/my-collection/v1/004` and `/files/my-collection/v1/download` must
   return **403**. Removing a UI blur must not reveal downloaded paid pixels.
3. One controlled small **real** purchase through an enabled channel. Match the
   order and amount against the **merchant dashboard**, not the return page.
4. Confirm unlock, single-image download, ZIP, refresh and a later revisit. Then
   confirm a different browser still cannot use the first buyer's paid URLs.
5. With SMTP enabled: verify an address, receive the actual message, restore
   access in a second browser. Reusing that recovery link must fail.
6. Test WeChat's embedded browser plus your target iPhone/Android browsers. A
   payment may return to a different browser session — recover via the original
   session, verified email, or support. ZIP downloads are files, not automatic
   album saves.
7. Check QR recognition on the same phone, and that it survives a container
   recreation. Confirm requests from two networks appear as **different** client
   IPs rather than one Docker-gateway rate-limit bucket.

Order inspection, **CVM**:

```bash
sudo docker compose exec paid-drive python -m app.admin list-orders --limit 20
```

> If you refund the test purchase, refund at the provider **first**, then revoke
> its PaidDrive access (see below). The application does not issue refunds.

---

## Step 13 — Verify certificate renewal and the nginx reload hook

**CVM** — inspect the existing renewal automation privately:

```bash
sudo certbot certificates
systemctl list-timers --all
sudo ls -l /etc/letsencrypt/renewal-hooks/deploy
command -v nginx; command -v systemctl
sudo certbot renew --cert-name "$PD_DOMAIN" --dry-run
```

Reuse the existing scheduler — check cron if there is no certbot timer, and never
add a duplicate schedule. Webroot certificates need nginx to reload after renewal:
reuse a deploy hook that already validates and reloads it, or create a scoped one.
This block refuses an existing filename and validates the lineage and executables:

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

> Adjust the lineage name first if certbot used another. `--run-deploy-hooks`
> really runs hooks on a successful test, so a real reload happens — recheck the
> other sites after. Keep the ACME location on port 80 in the final config.
> [Certbot renewal behavior](https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates)

---

## Step 14 — Back up and operate the service

Backup uses SQLite's consistent backup API and includes the matching content
tree. Freeze content edits while it runs; the app may keep serving buyers.

> Never copy a live SQLite main file alone while WAL is active.

```bash
cd /opt/paiddrive
PD_BACKUP_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PD_BACKUP_NAME="paiddrive-$PD_BACKUP_STAMP.tar.gz"
sudo docker compose exec -T paid-drive python scripts/backup.py \
  --output "/data/backups/$PD_BACKUP_NAME"
sudo tar -tzf "/var/lib/paiddrive/data/backups/$PD_BACKUP_NAME"
git rev-parse HEAD                        # keep this SHA with the backup
```

`.env`, the Compose override, the nginx config and the certificate management
config need **separate** private backup. The archive holds customer and session
data — keep it private.

Export just the selected archive to a private temp directory (this does not
change ownership of the running database):

```bash
PD_EXPORT_DIR="$(mktemp -d /tmp/paiddrive-export.XXXXXX)"
chmod 0700 "$PD_EXPORT_DIR"
sudo install -m 0600 -o "$PD_DEPLOY_USER" -g "$PD_DEPLOY_GROUP" \
  "/var/lib/paiddrive/data/backups/$PD_BACKUP_NAME" "$PD_EXPORT_DIR/$PD_BACKUP_NAME"
sha256sum "$PD_EXPORT_DIR/$PD_BACKUP_NAME"
printf 'Download this file: %s\n' "$PD_EXPORT_DIR/$PD_BACKUP_NAME"
```

**Mac** — replace the source with that exact printed path:

```bash
PD_CVM='YOUR_EXISTING_SSH_USER@119.45.126.188'
mkdir -p /Users/mewtwo/Workspace/PaidDrive-backups
chmod 0700 /Users/mewtwo/Workspace/PaidDrive-backups
scp "$PD_CVM:/tmp/paiddrive-export.REPLACE/paiddrive-REPLACE.tar.gz" \
  /Users/mewtwo/Workspace/PaidDrive-backups/
shasum -a 256 /Users/mewtwo/Workspace/PaidDrive-backups/paiddrive-REPLACE.tar.gz
```

Compare the hashes, keep a copy **off** the CVM, remove only the temp export, and
set a frequency matching the order loss you would accept — the package installs no
automatic offsite backup.

Routine commands, **CVM**:

```bash
cd /opt/paiddrive
sudo docker compose ps
sudo docker compose logs --tail=100 paid-drive
sudo docker compose exec paid-drive python -m app.admin list-orders --limit 20
```

After verifying the purchaser against merchant records, run
`python -m app.admin restore --reference ...` or `revoke --reference ...` through
`docker compose exec paid-drive`. Restore prints a single-use private link for a
confirmed paid order — send it only to the verified buyer. Revoke removes access
but refunds nothing and cannot erase downloads already taken.

> An order number alone is not payment proof. Never hand-edit a pending order to
> paid.

---

## Redeploying after code changes

Real content and SQLite live outside the checkout, so an update touches code and
the image only. Preserve `.env` and `compose.override.yaml`; never run
`git clean -fdx`, delete runtime directories, prune shared images, or stop the
daemon.

Take and export the Step 14 backup first, then record the current source, image
and private configuration:

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
git status --short                        # resolve local changes, do not discard
git fetch origin main
git log --oneline HEAD..origin/main
git diff --stat HEAD origin/main
```

Review the incoming changes and release notes, especially database or
configuration ones — **this MVP has no migration/downgrade framework.** Then pin
the reviewed commit and rebuild:

```bash
PD_NEW_SHA='REPLACE_WITH_REVIEWED_FULL_COMMIT_SHA'
(
  set -eu
  git checkout --detach "$PD_NEW_SHA"
  sudo docker compose config --quiet
  sudo docker compose build paid-drive
)
```

Run the new release's tests in an isolated container with **no production
mounts** — disposable storage plus read-only test/template mounts, so live data is
never relabelled — then roll it out:

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

Recheck a pre-existing paid order, anonymous denial, downloads, mail and the other
three sites. A single-worker restart briefly interrupts service — this is not a
zero-downtime release. New content versions are separate operator imports that
preserve the old originals.

**Code rollback — only while the database stays compatible.** Restore the previous
checkout and image **without** restoring an old order database. If configuration
changed, compare the saved private files before restoring any value:

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

> Retagging only the dedicated `paiddrive:local` tag leaves the immutable rollback
> tag intact. Do not rebuild during a rollback. **Do not restore an old database
> merely to roll back code** — it could erase payments received since that backup.

---

## Restoring a backup (only when data recovery is actually necessary)

Decide the recovery point and how to reconcile payments taken since it. Record the
current source/image/configuration and **preserve the current data even if
damaged**.

Pause public sales first by restoring PaidDrive's HTTP preparation site. If HTTPS
is live, keep its certificate and return 503 from its HTTPS `location /` too,
rather than letting the shared default site answer for this hostname. Validate and
reload nginx **before** stopping PaidDrive.

Then, using only your own trusted backup:

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

Check `backup.json`, the recorded source SHA and the matching content tree. **Stop
if integrity is not `ok`.** Once the recovery-point and later-transaction questions
are settled, move the current directories aside rather than deleting them, restore
into new empty ones, and recreate the container:

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

Select the matching source/image and private `.env`/override before starting. The
snapshot holds no old WAL/SHM files — **do not copy any in** from the quarantined
directory. Preserve newer sold content versions while reconciling later orders, and
restore a separately backed-up support image to its configured location.

```bash
sudo docker compose up -d --no-build --force-recreate --wait --wait-timeout 180 paid-drive
curl -fsS "http://127.0.0.1:$PD_PORT/health"
sudo docker compose exec paid-drive python -m app.admin list-orders --limit 20
```

Validate known orders and content **before** reopening the HTTPS proxy. Keep the
quarantined state and the backup until recovery is accepted.

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Private clone denied | Wrong repository identity or deploy key — your Mac's GitHub login does not authenticate the CVM (Step 3). Soccer's deploy key cannot be reused. |
| GitHub / Docker Hub / PyPI download fails | DNS or outbound reachability; use the box's established trusted route. Keep unrelated services running; do not reconfigure the shared daemon for a mirror. |
| Container cannot read originals | UID/GID 10001 ownership, directory traversal bits, or the SELinux label — check the actual runtime `/var/lib/paiddrive/content` (Step 5/9). |
| SQLite read-only / permission denied | `/var/lib/paiddrive/data` ownership, mount, or disk space. **Do not** `chmod 777` it. |
| New HTTP site returns 503 before launch | Expected — that is the ACME preparation page (Step 7). |
| ACME validation fails | Public port 80, the A/AAAA records, the challenge file, nginx site selection, and the webroot's SELinux label (`restorecon -RF /var/www/paiddrive-acme`). |
| `502` after launch | Check loopback health first, then PaidDrive's nginx logs, then real SELinux denials — `httpd_can_network_connect` is host-wide, so confirm the denial before setting it. |
| Live startup rejected | HTTPS `APP_URL`, ZPay base/ID/key, SMTP or deliberately disabled mail, support image path (Step 11). |
| Everyone shares one rate-limit bucket | The observed Docker proxy source is not in `FORWARDED_ALLOW_IPS` — verify real external client IPs from two networks (Step 10). |
| Paid at the provider but not unlocked | Order matching, signature/query result, merchant amount, notification reachability. Never trust the browser return alone. |
| Email missing | SMTP credentials/TLS, outbound port, verified sender, spam folder. Queued is not delivered. |
| Purchase missing in another browser | Different session — use verified email recovery or manually verified support. |
| Paid image returns `410` | A sold version's bytes/files changed. Restore the exact originals and publish new content as a **new version**. |
| ZIP or backup fails | Free disk under `/var/lib/paiddrive/data/tmp`, concurrent archive sizes, permissions. |
| New subdomain shows another site | DNS record, duplicate `server_name`, whether the `conf.d` file actually loaded, TLS/SNI, and whether the reload succeeded. |
| Another site regressed | Compare against the Step 1 baseline and undo **only** this deployment's new nginx/service changes from `$PD_AUDIT_DIR`. |
| Shell stuck at `>` after a heredoc | The closing token (`YAML`, `PY`) had leading spaces — it must start at column 0. |

---

## Security checklist

- [ ] **8091 is published on loopback only** and is NOT open in the Tencent Security Group.
- [ ] The three **existing** nginx vhosts, soccer's systemd unit and the shared Docker daemon config were never edited — only `paiddrive.conf` was added.
- [ ] Demo mode was **never** reachable through nginx; `APP_MODE=live` before Step 12 opened the site.
- [ ] `.env` and `compose.override.yaml` are `0600`; no real credential was committed or pasted into a chat.
- [ ] `ZPAY_KEY` holds PaidDrive's own value — soccer's environment file was not copied, and its callback still works.
- [ ] `FORWARDED_ALLOW_IPS` lists loopback plus the one **verified** source; never `*`.
- [ ] `/var/lib/paiddrive/data` is `0700` owned by 10001; content is `0750`/`0640` and mounted `ro,Z`.
- [ ] SELinux is still **Enforcing**, and only PaidDrive's own directories were relabelled.
- [ ] Anonymous GETs of a paid media URL and the collection ZIP return **403**; an empty ZPay notification returns **400 `fail`**.
- [ ] A hash-verified backup exists **off** the CVM with its source SHA recorded — and is stored privately, because it contains customer data.
- [ ] Certificate renewal was validated with `--dry-run --run-deploy-hooks`, and the other sites were rechecked afterwards.
- [ ] Every sold content version's files and IDs are intact; no `rsync --delete` has ever run against the content tree.

---

Primary-source details behind these steps are recorded in
[CVM_DEPLOYMENT_RESEARCH.md](CVM_DEPLOYMENT_RESEARCH.md). Current software
verification results are in [VALIDATION.md](../VALIDATION.md) — deployment, real
payments, real SMTP and phone acceptance still require the steps above.
