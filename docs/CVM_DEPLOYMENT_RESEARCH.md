# PaidDrive CVM deployment research

Checked 2026-11-10. This note records the primary-source facts used by the [deployment runbook](TENCENT_CVM_DEPLOYMENT.md). The server itself has not been inspected or changed.

## Existing deployment boundary

The sibling project's `../soccer-match-analyzer/AGENTS.md` identifies `../soccer-match-analyzer/docs/DEPLOYMENT-TENCENT.md` as authoritative and its AWS guides as historical (paths relative to the PaidDrive project root on your Mac). It documents host Nginx on 80/443, existing applications on 8000/8080, and Soccer Match Analyzer as a native systemd service on 8090. Recheck that inventory on the CVM before deploying. PaidDrive's [Compose file](../compose.yaml) publishes only `127.0.0.1:8091` and has independent data/content mounts; it does not require soccer's MariaDB or Redis.

The resulting deployment choice is to reuse the existing host Nginx and Docker Engine, while giving PaidDrive its own Compose project, directory, port and Nginx site. This is an inference from the documented server and current PaidDrive implementation, not a claim that the soccer application itself uses Docker.

## Compose installation without changing the Engine

Docker documents a separate Compose CLI plugin for machines that already have Engine and CLI. A manual installation can use `/usr/local/lib/docker/cli-plugins/docker-compose` for all users; match the binary architecture to the server, set executable permissions and verify `docker compose version`. Manual plugins do not auto-update. [Docker installation documentation](https://docs.docker.com/compose/install/linux/)

For this shared host, installing only that binary avoids an Engine package transaction or daemon restart. This is an operational inference from the plugin's installation steps. Do not run a general `yum update`, replace Docker, or restart its daemon as part of adding PaidDrive. An existing usable Compose plugin should be retained. The selected plugin still needs to work with the installed Engine; an incompatibility requires a separate maintenance decision.

The current official release is `v5.7.0`, dated 2026-11-02. Its assets include `checksums.txt` and per-binary `.sha256` files. The Linux binary digests are `7758048ad38e580f22559603312874fec8bb638d021a9e64182385fc17cc12a2` for `x86_64`, and `15861535d14e26555736b49376c95e14bfd94285366c8446bfac7156a972e76f` for `aarch64`. [Release](https://github.com/docker/compose/releases/tag/v5.7.0), [official asset list](https://github.com/docker/compose/releases/expanded_assets/v5.7.0)

Compose v5.7.0 depends on Moby client v0.6.2; that client's API negotiation lower bound is 1.40. This does not guarantee every Compose operation works with every older Engine. Retain a usable installed plugin; after any separate plugin installation, check `docker compose version`, read-only `docker compose ls`, and this project's config/build. [Compose dependencies](https://github.com/docker/compose/blob/v5.7.0/go.mod), [client minimum](https://github.com/moby/moby/blob/client/v0.6.2/client/client.go), [API negotiation](https://docs.docker.com/reference/api/engine/#minimum-api-version)

## SELinux and persistent mounts

Compose supports `:ro`, `:z` and `:Z` mount options. `Z` marks the host content for private use by one container; `z` marks shared content. The SELinux options are ignored on platforms without SELinux. Thus the single-service deployment can use `./data:/data:Z` and `./content:/app/content:ro,Z` when SELinux is enabled. [Compose volume syntax](https://docs.docker.com/reference/compose-file/services/#volumes)

Relabeling affects host files. Apply it only to PaidDrive's dedicated directories, never `/home`, `/usr`, shared application trees or the soccer project. A read-only content mount still needs readable ownership and directory traversal permissions. [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/#configure-the-selinux-label)

Operational inference: use any one-off container mount check before starting the persistent service. Once it is running, use `docker compose exec` for backup or inspection; concurrently mounting its private `:Z` directories in another container can change the label expected by the first container.

## Loopback publication and proxy trust

Keep `127.0.0.1:8091:8000`; omitting the host address publishes on external interfaces by default. Docker warns that versions earlier than 28.0.0 can expose localhost-published ports to peers on the same layer-2 network. Check the Engine version and actual network exposure before introducing private content. Resolve an old-Engine exposure concern separately from this app deployment, without an unplanned shared-daemon upgrade. [Docker port publication](https://docs.docker.com/engine/network/port-publishing/)

Uvicorn accepts forwarding headers only from configured trusted peers. Set `FORWARDED_ALLOW_IPS` to the actual immediate proxy source observed inside this Docker topology, which may be the bridge gateway. `*` trusts every source and is not appropriate for an unverified topology. Recheck the source after network changes. [Uvicorn settings](https://uvicorn.dev/settings/#http)

## Nginx and certificate sequence

The HTTP bootstrap should serve only `/.well-known/acme-challenge/` from a dedicated public directory, returning the preparation response elsewhere. Paid collection files remain outside Nginx static roots. Nginx maps `root` plus the request URI to the requested file, and `try_files` can return 404 for missing challenge files. [Nginx core module](https://nginx.org/en/docs/http/ngx_http_core_module.html#try_files)

HTTP-01 validation reaches port 80; publishing PaidDrive's 8091 port is not a substitute. [Let's Encrypt HTTP-01](https://letsencrypt.org/docs/challenge-types/#http-01-challenge)

Use `certbot certonly --webroot` against the already running Nginx. `certonly` obtains the certificate without installing it into server configuration. Webroot is an authenticator rather than an Nginx configuration installer. Renewals reuse the certificate's saved authentication options. A deploy hook runs after successful issuance/renewal; `$RENEWED_LINEAGE` can restrict a hook to the PaidDrive certificate. `--dry-run` skips deploy hooks unless `--run-deploy-hooks` is supplied; with that flag a successful test runs applicable hooks using the active certificate. A reload hook can therefore really reload Nginx during that test. Reuse existing timers and inspect existing hooks before adding one. [Certbot user guide](https://eff-certbot.readthedocs.io/en/stable/using.html)

Enable the final HTTPS proxy after the certificate exists and PaidDrive's live configuration works privately. `nginx -t` checks syntax and tries to open referenced files; reload starts new workers and gracefully shuts down old ones. [Nginx command-line documentation](https://nginx.org/en/docs/switches.html)

## Private repository access

A dedicated deploy key grants the CVM access to one repository. Add only its public half to the repository's Settings → Deploy keys, leaving write access disabled. Keep the private half on the CVM. Keys cannot be reused as deploy keys for multiple repositories, so retain existing application keys and use a separate key for PaidDrive. [GitHub deploy keys](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys)

Verify GitHub's host fingerprint against its [published fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints) before accepting the first SSH connection. `ssh -T` can authenticate successfully and still exit with status 1 because GitHub does not provide a shell; assess its message rather than using `&&` to gate the clone on zero status. [GitHub SSH connection test](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/testing-your-ssh-connection)

## Domain filing status

Tencent's guidance distinguishes a parent domain already filed with Tencent from one filed only with another provider. Its child-domain FAQ says no separate filing is needed for the former, while the latter requires Tencent access filing. Check the actual domain's current status in the Tencent console before public DNS setup; the presence of an existing working site is not the account-status check itself. [Tencent filing FAQ](https://cloud.tencent.com/document/product/243/19630)
