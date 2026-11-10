# PaidDrive：腾讯云 CVM 与子域名部署手册

**文档状态：详细参考流程，待与足球分析器的第一份 CVM 部署指南对齐。**

本手册根据当前 PaidDrive 源码和随包配置编写，覆盖从服务器盘点、子域名、演示运行、HTTPS 到真实支付、邮件、备份和回滚的完整过程。文中命令尚未在你的 CVM 上执行。

## 0. 先明确已知事实与未确认项

当前构建环境无法访问这两个 Mac 路径：

- `/Users/mewtwo/Workspace/soccer-match-analyzer`
- `/Users/mewtwo/Workspace/PaidDrive`

因此，不能声称已经读取足球项目的第一份 CVM 指南，也不能声称已把文件直接写入你的 Mac。请先按 [Mac 工作区创建说明](MAC_WORKSPACE_SETUP.md)，在解压后的源码根目录运行 `python3 scripts/install_macos_workspace.py --dry-run`，检查后再运行 `python3 scripts/install_macos_workspace.py`。安装器只会在 Mac 上创建一个全新的 `/Users/mewtwo/Workspace/PaidDrive`；目标已经存在时会停止，不覆盖或合并。确认新目录中直接包含 `compose.yaml` 后，再执行本手册的部署步骤。

`/Users/mewtwo/Images` 同样未能从构建环境读取。目前随包提供的是演示插画和微信客服占位图；真实图片可在你的 Mac 上导入。

### 0.1 已按当前源码确认

| 项目 | 当前实现 |
| --- | --- |
| 后端 | Python 3.12、FastAPI、Uvicorn，一个工作进程 |
| 前端 | 原生 HTML/CSS/JavaScript；中文、手机叠卡画廊；没有 Node 构建步骤 |
| 数据库 | SQLite，WAL 模式；不需要另外安装 MySQL/PostgreSQL |
| 容器进程身份 | UID/GID `10001` |
| 容器端口 | `8000` |
| 宿主机端口 | 默认 `127.0.0.1:8091`；由 `PAIDDRIVE_PORT` 调整 |
| Compose 项目／服务名 | `paid-drive` / `paid-drive` |
| 持久数据 | 宿主机 `./data` → 容器 `/data` |
| 合集原图 | 宿主机 `./content` → 容器 `/app/content`，只读挂载 |
| 公开静态资源 | `/assets` 只服务 `app/static/`，不包括合集原图 |
| 健康检查 | `GET /health`，检查数据库连接并返回当前模式 |
| 真实付款 | ZPay／易支付兼容的 `submit.php` 表单提交及 `api.php` 订单查询 |
| 恢复访问 | 浏览器会话；可选已验证邮箱；微信人工客服 |
| 邮件 | SQLite 持久队列；单进程后台发送；演示模式可写私有 `.eml` 文件 |

### 0.2 必须填入的实际信息

| 待确认项 | 为什么需要 |
| --- | --- |
| 原部署指南的确切文件及内容 | 判断应复用 Docker、systemd、宿主机 nginx、容器代理还是其他方式 |
| CVM 地域及操作系统版本 | 影响域名接入、安装命令、防火墙、证书管理方式 |
| CVM 公网 IPv4／IPv6 | 用于 DNS；不能把内网 IP 填到公开 A 记录 |
| SSH 用户、端口和密钥 | 沿用现有登录方法，不假设用户一定叫 `ubuntu` 或端口一定是 22 |
| 足球站点域名、端口和部署目录 | 防止覆盖已有服务或复用已占用端口 |
| 谁占用 80／443 | 决定应在哪里增加子域名配置 |
| 当前证书签发与续期工具 | 避免给同一域名引入两套互相冲突的续期方式 |
| 已有主域及其权威 DNS 服务商 | 在实际管理 DNS 的地方增加 `drive` 记录，通常不需要修改 NS |
| ZPay 实际网关、商户 ID、密钥 | 名称相同不代表接口地址和商户配置相同 |
| SMTP 服务及发件地址 | 用于真实邮箱验证和恢复访问 |

在这些信息确定前，可以准备源码和运行演示；不要把示例值当作已经查到的真实配置。

### 0.3 贯穿全文的发布顺序

1. 通过服务器回环地址或 SSH 隧道私下验证演示应用。
2. 公网子域先只开放证书验证路径；其他请求统一返回“网站正在准备中”的 503。
3. 签出有效证书，生成但暂不安装最终 HTTPS 代理配置。
4. 配好真实 ZPay、真实客服图片和 SMTP 或明确关闭邮件；将应用切到 `live`，先检查回环健康状态。
5. 最后启用 HTTPS 代理，再完成真实支付和手机端验收。

**不把演示模式公开到互联网。**演示付款本来就能模拟解锁；如果目录中已导入真实收费图片，公开演示模式会让访问者免费解锁。示例站点准备页是有意保留的发布屏障。

## 1. 本文使用的名字与执行位置

示例采用以下约定，全部可以根据原指南调整：

| 名称 | 本文示例 | 含义 |
| --- | --- | --- |
| Mac 项目目录 | `/Users/mewtwo/Workspace/PaidDrive` | 你要求保存新项目的本地路径 |
| CVM 应用目录 | `/opt/paiddrive` | 建议的新目录，不是已经发现的原路径 |
| 新子域名 | `drive.example.com` | 应改成 `drive.你的已有域名` |
| 公网 IPv4 | `203.0.113.10` | 文档专用示例地址，必须替换 |
| SSH 用户 | `your-user` | 改成现有 CVM 登录用户 |
| SSH 端口 | `22` | 如原项目使用其他端口，保持原值 |
| PaidDrive 内部端口 | `8091` | 如已占用，换一个未使用端口，并同步代理配置 |
| ACME 验证目录 | `/var/www/paiddrive-acme` | 只存证书验证文件，绝不能存合集原图 |
| nginx 新配置 | `/etc/nginx/conf.d/paiddrive.conf` | 仅在确认该目录已被现有 nginx 加载时采用 |

**后文所有“Mac”命令在你的 Mac 终端执行；所有“CVM”命令在 SSH 登录后的服务器终端执行。两个终端的变量不会自动共享。**

示例中的 `your-user`、`example.com`、公网 IP、证书邮箱和文件名都要先替换。命令不需要向聊天中粘贴商户密钥、SMTP 密码或完整 `.env`。

## 2. 在修改服务器前，先找到原指南并盘点现状

### 2.1 在 Mac 找到原来的 CVM 指南

在 Mac 执行只读搜索：

```bash
cd /Users/mewtwo/Workspace/soccer-match-analyzer
rg --files -g '*.md' -g '*deploy*' -g '*CVM*' -g '*nginx*' -g '*compose*' -g 'Dockerfile*'
rg -n -i 'cvm|tencent|腾讯|nginx|docker compose|certbot|acme|systemd' --glob '*.md'
```

从结果中确认你所指的“第一份 CVM 指南”，不要把搜索结果中的第一行自动当作那份文件。重点提取操作系统、部署目录、代理位置、域名、TLS、容器网络和更新方法。不要导出或分享 `.env`、私钥、完整数据库。

如果 Mac 没有 `rg`，可以先在 Finder 或编辑器中按文件名搜索；这不影响后面的应用运行。

### 2.2 登录 CVM，先只读检查

沿用足球项目已有的 SSH 方法。以下只是形式示例：

```bash
ssh -p 22 your-user@203.0.113.10
```

登录后执行：

```bash
cat /etc/os-release
uname -m
id
df -h
free -h
sudo ss -lntp
docker version
docker compose version
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
command -v nginx
command -v certbot
```

如果 Docker 需要 `sudo` 才能使用，后面的 Docker 命令也按原环境加 `sudo`。不要为了完成本手册而修改现有 Docker 用户组策略。

重点看：

- 80／443 是否已被宿主机 nginx 或某个代理容器使用。
- 8091 是否空闲；足球项目的端口是什么。
- 当前服务器架构是 `x86_64` 还是 `aarch64`。在 Mac 本地构建的镜像不一定适合该架构，本文默认上传源码后在 CVM 构建。
- 磁盘和内存是否足以容纳镜像、数据库、全部旧版本原图及下载时生成的 ZIP。
- 是否已有正常运行的 Docker Engine、Compose、nginx 和证书工具。

**不要在已有业务的 CVM 上照抄新机器教程，盲目卸载或重装 Docker、停止整个 nginx、清空防火墙、重置默认站点，或执行 `docker system prune`。**如果缺少组件，先根据实际操作系统和原指南选安装路径。Docker 官方提供按发行版区分的安装说明，并明确区分经过验证的平台与衍生发行版：[Docker Engine 安装文档](https://docs.docker.com/engine/install/)。

### 2.3 识别代理类型

| 现状 | 本文适用路径 |
| --- | --- |
| nginx 运行在宿主机，转发到本地端口 | 使用第 8～10 节的完整参考流程 |
| nginx／Traefik／Caddy 在容器里 | 阅读第 11 节；必须对齐原代理网络后再接入 |
| 由宝塔等面板维护站点 | 沿用面板的站点／证书机制，不能直接覆盖面板生成文件 |
| 前面还有 CLB、CDN、WAF 或其他入口 | 先确定 TLS 终止点、回源及回调规则，再调整代理链 |
| 足球项目完全不使用 Docker | 当前容器模板不能称为沿用原方案；应先审阅原指南，再决定是否同机增加 Docker 或提供对应进程配置 |

宿主机 nginx 场景下，可以执行：

```bash
sudo nginx -t
sudo nginx -V
```

需要确认 nginx 实际加载哪个目录时，可以将完整配置输出保存到私有盘点目录再本地查看。完整配置可能含内部地址或认证头，不要直接粘贴到公开聊天。

### 2.4 先备份原配置

在 CVM 设置本次盘点标记：

```bash
PD_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
PD_AUDIT_DIR="/var/backups/paiddrive-preflight-$PD_STAMP"
sudo install -d -m 0700 "$PD_AUDIT_DIR"
```

确认宿主机使用 `/etc/nginx` 后再备份：

```bash
sudo tar -czf "$PD_AUDIT_DIR/nginx-config.tar.gz" -C /etc nginx
sudo nginx -T 2>&1 | sudo tee "$PD_AUDIT_DIR/nginx-rendered.txt" >/dev/null
```

同时按足球项目既有方法保留它的 Compose 文件、部署脚本、应用版本和当前正常访问结果。它的私有环境文件／证书应保留在受保护的备份里，不混入 PaidDrive 源码包。

如果 nginx 在容器中，备份的是其宿主机配置挂载目录及所属项目配置，不要假设 `/etc/nginx` 就是生效配置。

## 3. 同一台 CVM 上的隔离方式

PaidDrive 与足球分析器可以使用同一公网 IP，通过不同 `server_name`／子域名进入各自应用。一个代理可以同时处理多个站点，不需要第二个程序去争抢 80／443。[nginx：server names](https://nginx.org/en/docs/http/server_names.html)

| 资源 | 足球分析器 | PaidDrive |
| --- | --- | --- |
| 域名 | 保持原值 | 新增 `drive.已有域名` |
| 应用目录 | 保持原值 | 独立 `/opt/paiddrive` 或原指南约定的新目录 |
| 应用端口 | 保持原值 | 默认宿主机回环 `8091` |
| Compose 项目 | 保持原值 | `paid-drive` |
| 数据 | 保持原值 | 新建 `data/` 和 `content/` |
| nginx 配置 | 保持原文件 | 只新增专属站点文件 |
| 商户回调 | 保持原路由 | PaidDrive 自己的 HTTPS 通知路径 |

原图目录必须与所有公开静态根目录分开。当前应用已经拒绝 `CONTENT_ROOT` 与 `app/static` 互相包含的配置；但实际代理仍需保持一致。不要新增 `/content` 的 nginx `alias`，也不要把原图复制到 `/assets`、公开 bucket、ACME 验证目录或 CDN 公开目录。

当前未解锁卡片由独立占位图形生成，不含付费原图像素。每个原图和 ZIP 请求仍由 Python 检查权限；“只读挂载”控制的是容器写入，不能代替这个权限检查。

## 4. 设置新子域名 DNS

### 4.1 在实际权威 DNS 服务商增加一条记录

假设已有主域为 `example.com`：

| 字段 | 建议值 |
| --- | --- |
| 主机记录 | `drive` |
| 类型 | `A` |
| 记录值 | 这台 CVM 的真实公网 IPv4 |
| 线路 | 沿用主域正常使用的默认线路策略 |
| TTL | 采用控制台允许的合理短值或默认值；以实际生效查询为准 |

普通情况下，只在已有主域的 DNS 区域里新增 `drive` 即可，不需要把整个域名迁移到新 DNS，也不需要改动足球站点使用的 `@` 或其他记录。腾讯云官方说明了主机记录及 A／AAAA 的含义：[主机记录和记录值](https://cloud.tencent.com/document/product/302/3468)、[A 记录](https://cloud.tencent.com/document/product/302/3449)。

### 4.2 AAAA、已有 CNAME 与代理服务

- 不具备可用公网 IPv6 时，不要为新子域新增 AAAA。
- 如果 `drive` 已有记录，先确认它是否在使用；不要直接覆盖另一个服务。
- 如果有错误的 AAAA，浏览器或证书验证可能访问错误的 IPv6 目标；只有确定该记录属于本次新站点且不需要 IPv6 后，才调整它。
- 不要为了 PaidDrive 改动主域或足球子域的记录。
- 如果现有域名经过 CDN／代理，先确认回源地址、缓存和支付通知放行策略。第一轮排错最好能明确请求究竟进入哪个源站。

Let's Encrypt 在 A 和 AAAA 同时存在时会优先尝试 IPv6，错误的 IPv6 站点可能让验证失败，即使 IPv4 正常：[IPv6 验证说明](https://letsencrypt.org/docs/ipv6-support/)。

在 Mac 或有 DNS 查询工具的机器上检查：

```bash
dig +short A drive.example.com
dig +short AAAA drive.example.com
```

没有 `dig` 时可以使用 `nslookup drive.example.com`。A 记录应返回该 CVM 的公网 IPv4；没有启用 IPv6 的站点不应意外返回旧的 AAAA。不要仅以“控制台保存成功”作为 DNS 已经全网生效的证据。

### 4.3 中国大陆地域的域名接入

如果 CVM 在中国大陆，核对该域名的备案及腾讯云接入状态；如果在非中国大陆地域，规则不同。已有足球站点能访问，不足以自动证明新业务和域名接入状态已经核对完毕。按实际地域、主体和域名情况参照腾讯云当前说明处理：[ICP 备案接入相关](https://cloud.tencent.com/document/product/243/43878)。本手册不假设这些手续已经完成。

## 5. 安全组与宿主机防火墙

在腾讯云控制台找到**该 CVM 实际绑定**的安全组，保留原有业务需要的规则，仅检查新站点需要的入口：

| 端口 | 来源 | 用途 |
| --- | --- | --- |
| TCP 443 | 需要访问网站的公众来源 | 正式 HTTPS 网站和支付通知 |
| TCP 80 | 使用 HTTP-01 验证时所需公众来源 | 证书验证和 HTTP → HTTPS 跳转 |
| SSH 实际端口 | 你的管理 IP 或既有受控来源 | 管理服务器；不要先改规则把自己锁在外面 |
| TCP 8091／其他 PaidDrive 内部端口 | 不新增公网放通 | 仅供同机代理访问 |
| 数据库端口 | 不需要 | SQLite 是文件，不监听网络端口 |

不要使用“一键放通全部端口”替代上述配置。腾讯云安全组支持 IPv4／IPv6 规则，也需要正确选择规则来源和优先级：[添加安全组规则](https://cloud.tencent.com/document/product/213/112614)。

宿主机若启用了 `ufw`、`firewalld` 或其他规则，也需要与安全组一起检查。只在确认所用工具后查看状态，例如 `sudo ufw status` 或 `sudo firewall-cmd --list-all`；不要为了排错整体关闭防火墙。腾讯云说明安全组与系统防火墙可以同时生效：[安全组问题](https://cloud.tencent.com/document/faq/213/43698)。

Compose 必须保留 `127.0.0.1:端口:8000` 的回环绑定。不要改成只写 `8091:8000` 来解决代理问题，那会改变暴露范围。[Docker：端口发布与映射](https://docs.docker.com/engine/network/port-publishing/)

## 6. 将源码放到 CVM 的独立目录

### 6.1 在 Mac 检查项目并运行测试

```bash
cd /Users/mewtwo/Workspace/PaidDrive
python3.12 --version
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

如果 `python3.12` 不存在，先安装或选择一个实际的 Python 3.12 解释器，再创建虚拟环境。不要直接假设 Mac 自带的 `python3` 就是 3.12。如果它确实显示 3.12，也可以使用对应的 `python3` 命令。

此测试验证应用自身逻辑，不会证明 CVM、ZPay 或 SMTP 已接通。实际完成的验证及限制见 `VALIDATION.md`。

需要导入你的真实图片时，在 Mac 执行：

```bash
python scripts/import_collection.py /Users/mewtwo/Images --slug my-collection --title "我的图片集" --price-cents 1900
```

先确认图片顺序、前三张免费内容、合集价格及标题，再上传。导入脚本会复制图片，不会修改来源目录。保留所有已售出的旧版本文件。

### 6.2 放入真实客服二维码

演示阶段可以继续使用占位图；但在真实收款之前，必须换成你们实际提供客服的二维码。先在 Mac 导出或保存一张真正的 PNG 二维码图片，手动选定来源文件，再执行：

```bash
PD_QR_SOURCE='/填写你实际选择的路径/微信客服二维码.png'
test -f "$PD_QR_SOURCE"
mkdir -p content/support
cp "$PD_QR_SOURCE" content/support/wechat.png
```

上述路径必须替换成你真实选择的文件。先用微信确认这张二维码对应正确的客服账号。如果实际是 JPEG，请保留真实扩展名，例如 `wechat.jpg`，并同步修改后面的 `SUPPORT_QR_PATH`；只改文件名不会转换图片格式。

放在 `content/support/` 的二维码不会自动加入合集 `items`，也不要把它混入收费图片清单。如果尚未完成真实二维码准备，可以先完成后面的私下演示，正式切换 `live` 前再补齐。

### 6.3 打包源码，排除本地数据与密钥

在 Mac 的项目目录中：

```bash
PD_RELEASE="$(date -u +%Y%m%dT%H%M%SZ)"
PD_SOURCE_ARCHIVE="/tmp/paiddrive-source-$PD_RELEASE.tar.gz"
tar --exclude='./.git' --exclude='./.venv' --exclude='./data' --exclude='./backups' --exclude='./.env' --exclude='__pycache__' --exclude='*.pyc' -czf "$PD_SOURCE_ARCHIVE" .
tar -tzf "$PD_SOURCE_ARCHIVE"
```

确认包内包含 `app/`、`content/`、`Dockerfile`、`compose.yaml`、`.env.example`、`requirements.txt`、`deploy/` 和 `scripts/`，不包含私有 `.env` 或本地购买数据库。不要将包含真实购买数据的旧归档放在源码目录后又一起打包。

上传时替换 SSH 参数：

```bash
scp -P 22 "$PD_SOURCE_ARCHIVE" your-user@203.0.113.10:/tmp/
```

### 6.4 在 CVM 解压

首次部署时，创建独立目录并将其交给当前部署用户管理；下面的 `/opt/paiddrive` 必须先确认不是现有业务目录：

```bash
PD_SERVER_DIR='/opt/paiddrive'
PD_DEPLOY_USER="$(id -un)"
PD_DEPLOY_GROUP="$(id -gn)"
sudo install -d -m 0750 -o "$PD_DEPLOY_USER" -g "$PD_DEPLOY_GROUP" "$PD_SERVER_DIR"
cd "$PD_SERVER_DIR"
```

如果这里已经有 `compose.yaml`、`data/` 或自己的代码，先按第 15 节升级流程处理，不执行“首次解压覆盖”。把下面归档名换成刚刚上传的实际名字：

```bash
tar -tzf /tmp/paiddrive-source-实际版本号.tar.gz
tar -xzf /tmp/paiddrive-source-实际版本号.tar.gz --no-same-owner
```

在应用目录中以部署用户解压，保留对源码的维护能力。不要用原项目的目录作为 PaidDrive 的解压目标。

## 7. 先启动独立的演示容器

### 7.1 创建演示配置

首次部署且确认 `.env` 不存在时：

```bash
cd /opt/paiddrive
cp .env.example .env
chmod 600 .env
```

通过编辑器调整，而不是把真实密钥写在命令参数或聊天中。第一轮设置：

```dotenv
APP_MODE=demo
APP_URL=http://localhost:8091
PAIDDRIVE_PORT=8091
SESSION_DAYS=90
MAIL_MODE=file
FORWARDED_ALLOW_IPS=127.0.0.1
ZPAY_BASE_URL=
ZPAY_PID=
ZPAY_KEY=
SUPPORT_QR_PATH=
```

如果选择其他空闲端口，`PAIDDRIVE_PORT` 与本地演示 `APP_URL` 的端口保持一致，后续代理渲染也传入同一个值。

`.env` 由 Compose 读取。Compose 文件会将 `DATABASE_PATH`、`CONTENT_ROOT` 和 `MAIL_FILE_DIR` 覆盖为容器路径，因此不要把 Mac 的 `/Users/...` 路径放进容器配置。

Compose 会处理环境变量插值；若密钥或密码包含 `$` 等特殊字符，按其 `.env` 规则使用合适的引号。不要为了排查而把展开后的所有密钥打印出来。[Docker：环境变量插值](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation)

### 7.2 数据与图片的权限

当前 Dockerfile 使用 UID/GID `10001`。数据目录归应用所有；源码和合集仍可以由部署用户维护，但合集必须让容器所属组读取。

在 CVM 的 `/opt/paiddrive` 执行：

```bash
sudo install -d -m 0700 -o 10001 -g 10001 data
sudo chown -R 10001:10001 data
sudo chgrp -R 10001 content
sudo find content -type d -exec chmod 0750 {} +
sudo find content -type f -exec chmod 0640 {} +
```

`content` 的拥有者保持部署用户，不要把整个源码目录递归改成容器用户。每次同步或导入新图片后，都重新执行针对 `content` 的组和权限调整。导入时创建的目录可能是 `0700`，仅在宿主机上能打开，不代表容器能遍历。不要用 `chmod 777` 解决这个问题。

如果真实二维码位于 `content/support/wechat.png`，它也会被上述权限设置覆盖；容器中的 `SUPPORT_QR_PATH` 应为 `/app/content/support/wechat.png`。

### 7.3 验证配置并构建

```bash
docker compose config --quiet
docker compose build paid-drive
```

`--quiet` 只验证配置，不输出包含密钥的最终配置。若拉取 Python 基础镜像或下载 Python 包失败，先排查 CVM 网络、DNS 和原项目使用的镜像来源，不盲目替换成不明第三方源。

启动前检查容器是否能读取真实挂载的内容：

```bash
docker compose run --rm --no-deps -T --entrypoint python paid-drive - <<'PY'
import json
import os
from pathlib import Path
root = Path('/app/content')
catalog = json.loads((root / 'collections.json').read_text('utf-8'))
count = 0
for collection in catalog['collections']:
    for item in collection['items']:
        with (root / item['file']).open('rb') as image:
            image.read(1)
        count += 1
qr = os.getenv('SUPPORT_QR_PATH')
if qr:
    with Path(qr).open('rb') as image:
        image.read(1)
print(f'容器读取成功：{count} 张图片；客服图片配置已检查。')
PY
```

随后启动，仅操作新服务：

```bash
docker compose up -d paid-drive
docker compose ps
docker compose logs --tail=100 paid-drive
curl -fsS http://127.0.0.1:8091/health
```

如端口已调整，同步修改最后一条命令。预期健康检查返回类似 `{"status":"ok","mode":"demo"}`。

不要把 `/health` 正常误认为支付已经接通；它只证明应用和数据库可以响应。

### 7.4 先通过 SSH 隧道试用

在 Mac 新开一个终端，替换真实 SSH 参数：

```bash
ssh -p 22 -L 8091:127.0.0.1:8091 your-user@203.0.113.10
```

如把服务端口改成 8092，需要把隧道命令中**两处** 8091 也改成 8092，并使用 `http://localhost:8092` 打开页面；演示 `APP_URL` 也应与这个浏览器地址一致。不要只改 Compose 端口却让 SSH 隧道继续连接旧端口。

只使用随包示例时，打开 `http://localhost:8091/c/slow-days`；按第 6.1 节导入了 `my-collection` 时，打开 `http://localhost:8091/c/my-collection` 检查自己的合集。对应替换实际端口和 slug，验证叠卡、前三张预览、模拟支付、解锁、下载及客服图片。暂不进行真实收款。

## 8. 宿主机 nginx：先接通仅用于验证的 HTTP 子域名

**本节仅适用于确认 nginx 运行在宿主机的场景。**现有代理若在容器里，跳到第 11 节，不在宿主机另启动 nginx。

### 8.1 确定配置安装位置

从原指南或已保存的 `nginx -T` 结果确认当前加载了哪个目录。以下以已生效的 `/etc/nginx/conf.d/*.conf` 为例。

如果现有环境使用 `sites-available` / `sites-enabled`，应将新文件放入对应目录并新增单独的链接。不要改全局 `/etc/nginx/nginx.conf` 来强行适配本文，也不要覆盖原站点文件。

### 8.2 准备只用于 ACME 的公开目录

```bash
sudo install -d -m 0755 /var/www/paiddrive-acme/.well-known/acme-challenge
```

它仅用于证书签发和续期的临时验证文件，与合集原图目录没有关系。不要在里面放图片、数据库、`.env` 或符号链接到私有目录。

### 8.3 渲染并检查 HTTP 配置

在 CVM 应用目录设置实际域名和空闲端口：

```bash
PD_DOMAIN='drive.example.com'
PD_PORT='8091'
python3 scripts/render_deploy_config.py --domain "$PD_DOMAIN" --phase http --port "$PD_PORT" --output /tmp/paiddrive-http.conf
```

渲染器会验证输入，并拒绝覆盖已有输出文件。如果上一次生成的临时文件还在，请检查后换一个新的输出名；不要绕过这个保护覆盖不确定文件。

检查生成文件是否包含正确 `server_name` 和 ACME 目录；HTTP 准备模板没有应用代理，`/` 应返回中性的 503。`--port` 在这里保持与部署参数一致，但只有最终 HTTPS 模板会将它用于应用 upstream。首次安装且确认目标文件不存在时：

```bash
sudo install -m 0644 /tmp/paiddrive-http.conf /etc/nginx/conf.d/paiddrive.conf
sudo nginx -t
```

只有 `nginx -t` 成功后才执行：

```bash
sudo systemctl reload nginx
```

如果测试失败，不重新加载。先修复新文件；原 nginx 工作进程仍应继续服务原站点。不要用重启服务器来处理语法错误。

### 8.4 确认公网只出现准备页

此时保持应用在回环端口运行演示，不把它代理到公网，也不把演示 `APP_URL` 改成公开 HTTP 域名。

在外部网络测试：

```bash
curl -i http://drive.example.com/
curl -i http://drive.example.com/health
```

两条请求均应得到准备页的 `503`，因为此阶段 nginx 还没有把任何业务路径转发到应用。不要使用 `curl -f` 把这个预期状态误判为部署故障。

同时重新打开足球站点，确认它继续正常工作。只有下文 ACME 验证路径应该直接返回其验证文件。应用仍可通过第 7.4 节的 SSH 隧道检查。

### 8.5 验证 ACME 路径

在 CVM 创建临时测试文件：

```bash
printf 'paiddrive-acme-ok\n' | sudo tee /var/www/paiddrive-acme/.well-known/acme-challenge/paiddrive-check >/dev/null
```

从 Mac 或外部网络请求：

```bash
curl -fsS http://drive.example.com/.well-known/acme-challenge/paiddrive-check
```

应收到 `paiddrive-acme-ok`。这个测试比只在服务器上访问 `localhost` 更能发现 DNS、安全组、错误代理或 CDN 回源问题。

## 9. 配置可信代理来源，避免全部用户共用限流桶

当前应用按 `request.client.host` 做部分访问和下单限流。宿主机 nginx 转发到 Docker 时，应用看到的即时连接来源可能是 Docker 网桥网关，而不是 `127.0.0.1`。

Uvicorn 默认只信任配置中的代理来源；它支持通过 `FORWARDED_ALLOW_IPS` 指定地址。不能简单设置成 `*` 来掩盖不清楚的代理链。[Uvicorn：代理头设置](https://uvicorn.dev/settings/)

### 9.1 查到真实来源后再配置

先看 Compose 网络；默认项目名下通常叫 `paid-drive_default`，但以实际结果为准：

```bash
docker network ls
docker network inspect paid-drive_default --format '{{json .IPAM.Config}}'
```

公网目前还是准备页，不会产生应用访问日志。可先在 CVM 通过回环端口发起一次健康请求，再看应用访问日志中的即时连接来源：

```bash
curl -fsS http://127.0.0.1:8091/health
```

```bash
docker compose logs --tail=30 paid-drive
```

如端口已调整，使用实际端口。结合 Docker 网络结果核实这个来源是否就是宿主机代理转发时使用的网桥网关。将准确的可信来源加入 `.env`，例如：

```dotenv
FORWARDED_ALLOW_IPS=127.0.0.1,172.20.0.1
```

`172.20.0.1` **只是格式示例，不能照抄**。实际地址取决于这台 CVM 的 Docker 网络。应用重建后会读取该值；等第 12.5 节真正开放 HTTPS 后，再从两个不同外部网络访问，确认应用能够区分来源。

现有 nginx 模板会覆盖 `X-Forwarded-For` 为其直接看到的 `$remote_addr`。如果 nginx 前面还有 CDN／CLB，则还需要按实际上游的可信代理范围处理真实 IP；不要信任公网客户端随意提供的转发头。

仅修复新服务的代理信任，不修改足球项目的既有设置。更新 Docker 网络或重建代理容器后也要重新核对来源地址。

## 10. 申请 HTTPS 证书，暂不公开演示应用

### 10.1 先复用原有证书管理方式

如果足球项目已经使用 acme.sh、Certbot、面板或现有通配符证书，优先沿用同一管理方式。先确认现有证书是否覆盖新的子域名，不能仅因主域 HTTPS 正常就认为 `drive` 已被覆盖。

以下是**确认使用宿主机 Certbot**时的参考流程。若没有 Certbot，应先根据真实操作系统和原指南选择安装方式，不要给运行中的服务器同时装多套证书管理器。[Certbot 官方安装入口](https://certbot.eff.org/instructions)

### 10.2 使用 webroot 签发，保持共用 nginx 运行

先确认第 8 节的 HTTP 子域与 ACME 测试正常，再执行：

```bash
sudo certbot certonly --webroot --webroot-path /var/www/paiddrive-acme --cert-name "$PD_DOMAIN" -d "$PD_DOMAIN"
```

按 Certbot 提示填写你控制的管理邮箱并完成所需确认。`certonly --webroot` 只申请证书，不自动改写足球站点的 nginx 配置，也不需要停止正在占用 80 端口的共用 nginx。[Certbot：webroot 与 certonly](https://eff-certbot.readthedocs.io/en/stable/using.html#webroot)

HTTP-01 验证需要外部能访问端口 80 的验证路径；不能把它改成从 8091 验证。如果端口 80 确实无法对外使用，则按现有证书方案采用可自动续期的 DNS-01 验证，而不是关闭足球站点争抢端口。[Let's Encrypt：验证方式](https://letsencrypt.org/docs/challenge-types/)

### 10.3 确认证书路径并暂存最终配置

```bash
sudo certbot certificates
```

检查证书覆盖的域名及 `fullchain.pem`、`privkey.pem` 的实际路径。通常在 `/etc/letsencrypt/live/域名/`，但如果已有同名证书产生了其他名称，以命令结果为准。

**证书未签出前，不安装引用该证书的 HTTPS 模板，否则 `nginx -t` 会失败。**

生成 HTTPS 配置：

```bash
python3 scripts/render_deploy_config.py --domain "$PD_DOMAIN" --phase https --port "$PD_PORT" --output /tmp/paiddrive-https.conf
```

若实际证书路径与渲染默认路径不同，只调整生成文件中的证书路径。**此时仅检查并保留生成文件，不安装到 nginx。**公网继续是 ACME 验证路径和 503 准备页。

接下来顺序完成第 12 节的真实运行配置：应用切成 `live`、客服图片及内容权限就绪、回环健康检查通过。最终安装 HTTPS 配置的具体命令统一放在第 12.5 节，避免提前公开可模拟解锁的应用。

最终 80 端口配置会保留 ACME 路径，只有其他路径跳转到 HTTPS。不要把跳转写成抢先覆盖 ACME 路径的 server 级 `return`。证书续期时仍然需要验证路径可达。

### 10.4 检查续期，而不仅是首次证书

```bash
sudo certbot renew --cert-name "$PD_DOMAIN" --dry-run
systemctl list-timers --all
```

沿用已存在的 Certbot／ACME 定时机制，确认续期成功后会执行 nginx 配置检查并重新加载证书。`certonly` 并不等于已经安装了适合你环境的 nginx 续期重载钩子。

**下面仅适用于已确认使用宿主机 Certbot、默认 `/etc/letsencrypt` 配置目录和 systemd 管理的 `nginx`，且尚无适用重载 hook 的情况。**如果原站点已经有正确的重载 hook，沿用即可；容器代理或其他 ACME 客户端应使用其原有机制。

先查看现有 hook、证书名称和命令路径：

```bash
sudo ls -l /etc/letsencrypt/renewal-hooks/deploy
sudo certbot certificates
command -v nginx
command -v systemctl
```

`ls` 显示目录不存在时可在下一步创建；如果目录存在，先检查已有脚本的作用。还要检查该证书的 renewal 配置是否已设置 deploy hook。不要删除、覆盖或重复安装原站点的钩子。

如确实需要新增，在以下示例中把证书目录、两个可执行文件路径改成刚才查到的实际值。`lineage` 必须是证书的完整目录，若名称带 `-0001`，也要完整保留。本命令只创建一个新文件；同名文件已存在会报错退出。

```bash
sudo python3 - <<'PY'
from pathlib import Path
import os
import shlex

lineage = Path("/etc/letsencrypt/live/drive.example.com")
nginx = Path("/usr/sbin/nginx")
systemctl = Path("/usr/bin/systemctl")
hook = Path("/etc/letsencrypt/renewal-hooks/deploy/paiddrive-reload-nginx.sh")

if not (lineage / "fullchain.pem").is_file():
    raise SystemExit("请先填写已签发证书的实际目录，未创建 hook。")
for executable in (nginx, systemctl):
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise SystemExit(f"请填写实际可执行文件路径：{executable}")

quote = shlex.quote
script = "\n".join([
    "#!/bin/sh",
    "set -eu",
    '[ "${RENEWED_LINEAGE:-}" = ' + quote(str(lineage)) + ' ] || exit 0',
    quote(str(nginx)) + " -t",
    quote(str(systemctl)) + " reload nginx",
    "",
])
hook.parent.mkdir(parents=True, exist_ok=True)
with hook.open("x", encoding="utf-8") as handle:
    handle.write(script)
hook.chmod(0o750)
print(f"已新增：{hook}")
PY
```

这个 hook 只在 `RENEWED_LINEAGE` 等于 PaidDrive 的实际证书目录时工作；其他证书的续期不会触发它。`nginx -t` 失败时脚本立即退出，不会继续 reload。

确认当前 Certbot 支持 `--run-deploy-hooks` 后，用**实际证书名称**执行一次验证：

```bash
PD_CERT_NAME='drive.example.com'
sudo certbot renew --cert-name "$PD_CERT_NAME" --dry-run --run-deploy-hooks
```

普通 `--dry-run` 默认不执行 deploy hook；加上 `--run-deploy-hooks` 后，验证成功会运行适用 hook，包括此次新增脚本及原有相关脚本，使用当前有效证书，并会真实重载 nginx。选择可以检查原站点状态的时间执行，之后再确认足球站点和 PaidDrive 的 ACME 路径正常。保留已有续期定时任务，不重复新建 cron 或 timer。[Certbot：续期、deploy hook 与 dry-run 参数](https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates)

## 11. 如果现有代理运行在容器里

不要原样使用宿主机模板中的 `proxy_pass http://127.0.0.1:8091`。在代理容器内部，`127.0.0.1` 指向代理容器自己，不是 CVM 宿主机，也不是 PaidDrive。

常见做法是在原有代理和 PaidDrive 之间使用已知的共享 Docker 网络，并通过专属服务别名转发到 PaidDrive 的容器端口 `8000`。但这必须先查清原项目的网络名、代理配置挂载、重载方法以及服务发现策略。[Docker Compose：网络与跨项目网络](https://docs.docker.com/compose/how-tos/networking/)

需要与原指南核对的实际改动如下：

| 项目 | 需要确认的内容 |
| --- | --- |
| 共享网络 | 真实网络名，是否由原项目外部管理，是否允许新服务加入 |
| 新服务别名 | 使用不会与足球项目冲突的名字，例如 `paiddrive-app` |
| upstream | 代理转发到 `paiddrive-app:8000`，不是容器里的 `127.0.0.1:8091` |
| 证书／ACME | 签发进程和代理必须能读到同一套验证文件及证书挂载 |
| 可信代理 IP | 应用信任实际代理容器的来源，不能不加区分地信任所有客户端 |
| 重载及容器重建 | 新容器 IP 改变后，现有 nginx 的 DNS／重载策略是否能正确找到新实例 |
| 公开端口 | 仍由现有入口统一占用 80／443，不额外开放 PaidDrive 原图端口 |

在原配置未提供前，本手册不编造一份可以直接覆盖原代理项目的 Compose 文件。也不要把应用端口临时改成 `0.0.0.0:8091` 来绕过容器网络问题。

## 12. 配置真实 ZPay 收款

### 12.1 先确认现有商户接口与本适配器相符

当前代码位于 `app/payments.py`，使用以下协议形态：

- 向 `ZPAY_BASE_URL` 下的 `submit.php` 以表单 POST 发起支付。
- 付款方式为 `wxpay` 或 `alipay`。
- 金额为人民币，按服务端订单记录生成两位小数。
- 通知按该协议验签，再通过 `api.php?act=order` 从服务端查询确认。

对照你原项目实际的网关文档、商户 ID 和密钥再填入配置。不要因为公开示例中出现某个域名，就自动把它当作你现有商户的网关。[ZPay 官方协议文档](https://z-pay.cn/doc.html)

### 12.2 回调地址与浏览器回跳地址

正式域名为 `https://drive.example.com` 时：

| 用途 | 地址 |
| --- | --- |
| 服务端通知 `notify_url` | `https://drive.example.com/api/payments/zpay/notify` |
| 浏览器回跳 `return_url` | `https://drive.example.com/payment/return` |

代码从 `APP_URL` 自动生成这两个地址。商户后台如要求配置业务域名、支付域名或回调白名单，按该商户通道的实际要求填入同一个站点；这不等于当前代码已经完成微信 JSAPI 授权。

通知路径必须可以被支付平台服务端访问，不能被全站登录、验证码、WAF 人机挑战或 IP 限制错误拦截。它不依赖浏览器 cookie，而是依赖签名和订单查询校验。

### 12.3 检查通知路由可达，但不伪造成功

本检查在第 12.5 节开启最终 HTTPS 代理后执行。无参数访问通知接口应返回失败，而不是成功：

```bash
curl -i https://drive.example.com/api/payments/zpay/notify
```

当前真实模式通常返回 `400` 和 `fail`；演示模式是 `404` 和 `fail`。这只能证明请求到达了拒绝无效通知的路由，不能证明真实验签或到账成功。不要为了让检查“变绿”把此接口改成无条件 `success`。

真正的验收需要从网站创建真实订单、在平台完成付款，再确认服务端已记录 `paid`，网页解锁且对应下载可用。

### 12.4 先准备 SMTP，再切换 live

如果第 6.2 节的真实二维码尚未随源码上传，先补齐。确认文件已在你的 Mac 上保存后，在 CVM 应用目录执行 `mkdir -p content/support`，然后从 Mac 上传选定的 PNG：

```bash
scp -P 22 "$PD_QR_SOURCE" your-user@203.0.113.10:/opt/paiddrive/content/support/wechat.png
```

如果重新打开了 Mac 终端，先重新设置 `PD_QR_SOURCE` 为实际路径；JPEG 文件应使用一致的 `.jpg` 目标和配置。回到 CVM 再执行第 7.2 节的 content 组及权限调整。不要先填一个尚不存在的 `SUPPORT_QR_PATH`，否则应用会拒绝启动。

编辑 `.env`，填入实际值：

```dotenv
APP_MODE=live
APP_URL=https://drive.example.com
PAIDDRIVE_PORT=8091
ZPAY_BASE_URL=https://你的实际网关基础地址
ZPAY_PID=你的商户ID
ZPAY_KEY='你的商户密钥'
MAIL_MODE=smtp
SMTP_HOST=你的SMTP主机
SMTP_PORT=587
SMTP_USER=你的SMTP用户名
SMTP_PASSWORD='你的SMTP密码'
SMTP_FROM=你已配置的发件邮箱
SMTP_STARTTLS=true
SUPPORT_QR_PATH=/app/content/support/wechat.png
```

上面的中文内容都是占位符，不能直接启动。`ZPAY_BASE_URL` 填基础地址，不是完整 `submit.php` 路径。`FORWARDED_ALLOW_IPS` 保留第 9 节核实后的值。

如果暂时没有可用 SMTP，可以设 `MAIL_MODE=disabled`，此时网页关闭邮箱找回能力，靠当前浏览器和微信客服恢复；不能一边关闭邮件一边承诺用户已经拥有邮箱找回。

**live 模式不能保留 `MAIL_MODE=file`。**配置校验会拒绝；缺少 HTTPS、ZPay ID、密钥或正确网关也会阻止启动。这些校验不会替你判断商户配置是否真实有效。

确认真实二维码和合集已配置好，重新完成第 7.3 节的容器文件读取检查。然后启动真实模式；此时公网仍保留 503 准备页：

```bash
docker compose config --quiet
docker compose up -d --force-recreate paid-drive
docker compose ps
curl -fsS http://127.0.0.1:8091/health
```

如端口已调整，修改回环请求中的端口。此时健康检查应显示 `mode: live`。它不需要浏览器 cookie，因此可以通过回环 HTTP 检查；真实买家的业务操作随后必须从 HTTPS 站点完成。

演示订单、演示会话和演示恢复凭证不会自动变成真实购买；这是预期隔离行为，不需要手工转换数据库。

### 12.5 最后启用 HTTPS 代理

前提：证书已签出、最终配置已生成、回环健康检查显示 `live`、真实合集与客服图片可读、ZPay 和邮件配置已填好。

再次确认第 10.3 节生成的配置使用实际域名、证书路径及应用端口。备份当前 PaidDrive 专属站点文件，再安装最终配置：

```bash
sudo cp -a /etc/nginx/conf.d/paiddrive.conf "$PD_AUDIT_DIR/paiddrive-before-https.conf"
sudo install -m 0644 /tmp/paiddrive-https.conf /etc/nginx/conf.d/paiddrive.conf
sudo nginx -t
```

仅测试成功后执行：

```bash
sudo systemctl reload nginx
curl -I http://drive.example.com/
curl -fsS https://drive.example.com/health
```

预期 HTTP 跳转到 HTTPS，证书有效，外部健康检查显示 `ok/live`。再验证 ACME 路径仍正常、足球网站不受影响，以及第 9 节的实际客户端 IP 能正确区分。不要为了测试把 `APP_MODE` 改回 `demo`；若还需要演示，使用单独的私有实例及数据目录。

此后执行第 12.3 节的无效通知拒绝检查，并继续以下真实支付验收。尚未完成验收前，只将链接用于你们自己的测试，不对客户宣传正式上线。

### 12.6 真实支付验收

使用你自己控制的测试买家和允许测试的实际通道，完成一笔小额真实交易；金额由你的真实测试安排决定，不在此固定要求某个金额。

1. 从 HTTPS 子域的合集页下单，确认显示的金额与平台付款金额一致。
2. 完成付款，观察“查询付款结果”和自动解锁。
3. 在 CVM 查看订单：

```bash
docker compose exec paid-drive python -m app.admin list-orders --limit 20
```

4. 对照商户平台交易记录，确认引用同一订单，而不是仅看浏览器回跳文案。
5. 刷新页面、重新打开该合集链接，确认已购浏览器仍能访问。
6. 用另一无购买会话访问原图和 ZIP，确认被拒绝。
7. 核实重复通知不会产生重复购买；支付平台重试通知本身不一定是异常。
8. 如需退还测试款项，先按商户平台真实流程退款，再按第 14 节撤销该购买权限。`revoke` 不会向 ZPay 发起退款。

未完成这些步骤前，只能说代码接入和演示已完成，不能说真实收款已验证。

## 13. SMTP 与移动端恢复验证

### 13.1 当前邮件配置的实际含义

| 配置 | 作用 |
| --- | --- |
| `MAIL_MODE=file` | 仅演示；将邮件写入私有 `/data/outbox`，不会发送 |
| `MAIL_MODE=smtp` | 通过 SMTP 发送真实验证／恢复邮件 |
| `MAIL_MODE=disabled` | 关闭邮箱入口和邮件恢复 |
| `SMTP_PORT=587` + `SMTP_STARTTLS=true` | 使用 STARTTLS；是否支持以邮件服务商配置为准 |
| `SMTP_PORT=465` | 使用隐式 TLS；代码不会在 465 上再执行 STARTTLS |
| `SMTP_USER` 非空 | 执行 SMTP 登录 |
| `SMTP_FROM` | 实际发件地址；按服务商要求完成发件身份配置 |

CVM 需要能向该 SMTP 服务的实际端口建立出站连接，也需要能访问 ZPay HTTPS 及正常解析 DNS。不要为 SMTP 在 CVM 安全组新增入站 587／465；本应用是发信客户端，不是邮件服务器。

当前邮件任务持久化于 SQLite，后台约每三秒检查一次，每个任务最多尝试五次，失败后等待再尝试；链接过期后不会继续发送。SMTP 修复后，用户可能需要重新申请一封新邮件。日志不会打印完整邮件、收件地址或恢复链接。

### 13.2 用自己的邮箱完成端到端检查

1. 在一次真实购买中选填你控制的邮箱，或在已购浏览器中“添加或验证邮箱”。
2. 确认实际收件箱或垃圾箱收到了邮件；仅在队列表里看到任务不等于已投递。
3. 检查链接域名是 `https://drive.你的域名`，没有 `localhost`、IP、旧端口或错误子路径。
4. 打开链接后点击确认，完成邮箱验证。
5. 在另一个浏览器打开合集，选择邮箱恢复，再用新邮件完成恢复。
6. 再次使用同一临时链接应失败；可以重新申请新的恢复邮件。

不要把含 token 的完整链接贴到公开日志或群聊。客服人工链接同样是一次性临时凭证。

### 13.3 手机和微信的实际验收

分别记录微信内浏览器、Safari 和 Chrome 的结果，不把桌面窄视口当作真机支付验证。

- 横向滑动叠卡、纵向滚动、点击切换、前 3 张预览、付费占位卡均正常。
- 付费占位图不包含对应原图像素；付款前网络请求没有暗中下载所有原图。
- 点击微信／支付宝付款后，实际商户通道能在该环境完成支付；当前代码没有自行实现微信 JSAPI 授权。
- 支付后可能回到不同浏览器环境。此时原浏览器查询、已验证邮箱或人工客服可以恢复，而不是把回跳参数当作购买凭证。
- 单张图片下载或打开原图的行为符合该浏览器能力；整套 ZIP 是下载到文件管理位置，不是直接进入相册。
- 在同一手机联系客服时，真实二维码可以长按保存、截图或按微信能力识别；不要只提供“拿另一台设备扫描”的说明。
- 已购用户可下载文件；系统不提供 DRM，也不承诺防止其主动复制、截图或再次分享。

## 14. 上线检查与人工客服

### 14.1 放出第一条真实购买链接前

| 检查项 | 通过标准 |
| --- | --- |
| 足球站点 | 域名、已有接口和原用户访问仍正常 |
| 子域 DNS | A 正确，AAAA 无错误目标 |
| TLS | 浏览器无证书警告，续期验证已检查 |
| 应用状态 | `/health` 为 `ok/live`，容器持续健康 |
| 端口 | PaidDrive 仍绑定宿主机回环；安全组没有开放内部应用端口 |
| 私有文件 | 原图目录不在任何公开静态根目录中；未购请求被服务器拒绝 |
| 合集 | 正确图片、顺序、固定版本、价格、前三张免费范围 |
| 客服 | 真实微信二维码，订单编号可查看并复制 |
| 支付 | 实际商户付款、通知／主动查询、一次性解锁已验证 |
| 邮件 | 实际投递、验证、换浏览器恢复已验证；或明确关闭邮箱能力 |
| 数据 | 重建容器后购买仍在；备份可读取且已另存到 CVM 外 |
| 手机 | 微信、Safari／Chrome 的关键路径分别记录 |

### 14.2 客服命令

先核实付款归属，再处理：

```bash
docker compose exec paid-drive python -m app.admin list-orders --limit 20
docker compose exec paid-drive python -m app.admin restore --reference 实际订单编号
docker compose exec paid-drive python -m app.admin revoke --reference 实际订单编号
```

- `restore` 只接受当前模式下本地已确认 `paid`、未撤销的购买，生成 15 分钟有效、单次使用的人工恢复链接。
- `revoke` 撤销服务器上的托管访问，不会退款，也不能删除买家已经下载的文件。
- 订单号用于查找，不是单独的付款证明。不要仅凭来访者知道订单号就发送恢复链接。
- 如果 ZPay 已付款但本地仍是 `pending`，先让原购买浏览器查询付款结果，并检查通知／平台查询；当前 CLI 没有把任意 `pending` 手工变成 `paid` 的功能。
- 如果原浏览器也丢失且全部通知失败，需要工程人员基于平台交易证据做受控补偿；不能直接改库跳过验证，也不能用 `restore` 掩盖未确认的支付状态。

## 15. 备份、升级和回滚

### 15.1 需要一起保留什么

| 内容 | 用途 |
| --- | --- |
| SQLite 一致性快照 | 订单、购买权限、会话、恢复和邮件任务 |
| 全部 `content/` | 当前及历史已售版本的原图和合集配置 |
| 实际二维码 | 若不在 `content/`，单独纳入备份 |
| 当时的源码／镜像版本 | 让数据库与能运行它的代码对应 |
| 私有 `.env` | 通过你的安全配置备份方式保存，不打入公开源码包 |
| nginx／证书配置 | 保存专属站点配置及原有续期方案；证书私钥保持私密 |

不要把 `data/` 放进公开网站根目录或提交到源码仓库。

### 15.2 使用 SQLite 备份接口

在 CVM 应用目录：

```bash
PD_BACKUP_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
docker compose exec -T paid-drive python scripts/backup.py --output "/data/backups/paiddrive-$PD_BACKUP_STAMP.tar.gz"
```

备份包出现在宿主机 `data/backups/`，由容器用户拥有。脚本使用 SQLite 在线备份接口，包含已提交的 WAL 内容，再打包合集文件；不能用简单复制 `paiddrive.sqlite3` 代替。[Python：SQLite backup](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup)

备份期间暂停导入或改动合集配置。备份完成后，通过安全方式复制一份到 CVM 以外，并保留与之对应的代码版本。不要为了让普通用户能下载备份而把整个 `data/` 改成公开可读。

`data/` 的权限是 `0700`，备份由 UID10001 创建且为 `0600`，普通部署用户通常不能直接 SCP 其中的文件。可以只导出选中的那一个备份，不改变原数据库或原备份的权限。

在同一个 CVM 终端中执行：

```bash
PD_EXPORT_DIR="/tmp/paiddrive-export-$PD_BACKUP_STAMP"
PD_EXPORT_FILE="$PD_EXPORT_DIR/paiddrive-$PD_BACKUP_STAMP.tar.gz"
install -d -m 0700 "$PD_EXPORT_DIR"
sudo install -m 0600 -o "$(id -u)" -g "$(id -g)" "data/backups/paiddrive-$PD_BACKUP_STAMP.tar.gz" "$PD_EXPORT_FILE"
sha256sum "$PD_EXPORT_FILE"
printf '%s\n' "$PD_EXPORT_FILE"
```

记下最后输出的实际路径和校验值。在 Mac 使用自己的私有备份目录，替换具体时间标记和 SSH 参数：

```bash
mkdir -p /Users/mewtwo/Workspace/PaidDrive-backups
chmod 700 /Users/mewtwo/Workspace/PaidDrive-backups
scp -P 22 your-user@203.0.113.10:/tmp/paiddrive-export-实际时间标记/paiddrive-实际时间标记.tar.gz /Users/mewtwo/Workspace/PaidDrive-backups/
chmod 600 /Users/mewtwo/Workspace/PaidDrive-backups/paiddrive-实际时间标记.tar.gz
shasum -a 256 /Users/mewtwo/Workspace/PaidDrive-backups/paiddrive-实际时间标记.tar.gz
```

确认两端校验值一致后，删除 CVM 中这一个临时导出副本及空导出目录即可；保留原来的私有备份。不要递归改变运行数据库的所有者，也不要开放 `/data` 的网页下载入口。

### 15.3 更新前保留旧镜像和数据

1. 完成上一节的数据库＋合集备份。
2. 私密备份当前 `.env`、PaidDrive nginx 配置和当前代码。
3. 记录当前镜像，并给它一个可识别的本地回滚标签：

```bash
PD_OLD_IMAGE="$(docker compose images -q paid-drive)"
test -n "$PD_OLD_IMAGE"
PD_ROLLBACK_TAG="paiddrive:before-$PD_BACKUP_STAMP"
docker image tag "$PD_OLD_IMAGE" "$PD_ROLLBACK_TAG"
```

4. 确认新版本是否改变数据库结构。当前项目没有提供通用迁移／降级框架，不应凭空执行 Alembic 命令，也不能假定未来所有版本的数据库都向后兼容。
5. 如需要在 CVM 外保留镜像，按资源情况使用 `docker image save` 另存；不要删除尚未确认无用的回滚标签。

### 15.4 应用更新流程

将新源码解压到独立的待发布目录，检查差异及版本，而不是直接覆盖正在使用的目录。更新当前项目时明确排除 `data/`、私有 `.env` 及全部历史 `content/`；只同步经过确认的代码和新增合集文件，不使用会删除旧内容的 `rsync --delete`。

合并新代码／合集配置后：

```bash
sudo chgrp -R 10001 content
sudo find content -type d -exec chmod 0750 {} +
sudo find content -type f -exec chmod 0640 {} +
docker compose config --quiet
docker compose build paid-drive
docker compose up -d paid-drive
docker compose ps
```

再次检查健康、一次已购访问、未购原图拒绝、邮件任务及足球站点。单进程重建可能有短暂中断；此 MVP 没有实现自动蓝绿切换，不应把它描述成零停机部署。

新合集版本应使用新的文件目录，保留旧目录。已售图片不能通过覆盖同一路径更新；文件 hash 不匹配时服务端会拒绝交付。

### 15.5 代码回滚与数据库恢复是两件事

如果新代码有问题，但数据库结构仍与旧版兼容，可用先前标记的镜像回滚代码，并保持当前 `data/` 和 `content/`：

在一个新建的临时 Compose 覆盖文件中填入**实际回滚标签**，例如 `compose.rollback.yaml`：

```yaml
services:
  paid-drive:
    image: paiddrive:before-实际备份标记
```

确认该镜像已存在，再执行：

```bash
docker compose -f compose.yaml -f compose.rollback.yaml config --quiet
docker compose -f compose.yaml -f compose.rollback.yaml up -d --no-build paid-drive
```

这个覆盖文件只用于该次回滚。恢复正常升级前明确停止使用它，避免后续仍固定运行旧镜像。

**不要为普通代码回滚直接恢复旧数据库。**备份后可能已有新的真实付款；恢复旧快照会丢掉这些订单和权限。数据库不兼容时，应先暂停新购买，保留最新数据和支付平台交易记录，再制定迁移或补偿方案。

### 15.6 真正需要恢复数据库时

仅在确认目标恢复点以及期间交易处理方案后进行：

1. 暂停对外接受新购买，并停止 **PaidDrive** 服务，不停止整个 Docker 或足球应用。
2. 为当前故障状态再做一份留存，即使它可能损坏；不要直接删除。
3. 将自己的备份解压到空的临时目录，检查目录结构及 SQLite 完整性。
4. 保留旧 `data/` 为隔离目录，再建立新的 `data/`；只恢复快照数据库，不混用旧 `-wal`／`-shm` 文件。
5. 恢复与快照对应的合集文件；同时保护备份后新增的已售版本，不能未经核对就删除。
6. 恢复配套代码、私有环境配置和正确的 UID/GID 权限。
7. 启动应用，先核验历史订单、期间新付款及几个真实文件，再恢复流量。

停止／启动的范围仅为：

```bash
docker compose stop paid-drive
docker compose up -d paid-drive
```

没有核对期间交易前，不提供“一条命令清空数据再恢复”的操作。

## 16. 常见问题排查表

| 现象 | 优先检查 | 处理方向 |
| --- | --- | --- |
| 域名无法访问／连接超时 | A／AAAA、安全组、宿主机防火墙、80／443 实际监听者 | 从外网逐层检查；不要开放所有端口试运气 |
| 新域名打开了足球网站 | DNS 指向、`server_name`、新文件是否被 include、是否 reload 成功 | 修正 PaidDrive 专属站点配置，不改足球默认站点 |
| nginx 报证书文件不存在 | 证书是否签出、实际路径、是否提前安装 HTTPS 模板 | 先恢复可用 HTTP 配置，签出证书再切换 |
| ACME 验证失败 | 外网 80、验证路径、错误 AAAA、CDN 回源、重定向位置 | 用第 8.5 节的测试文件定位，不停止共用 nginx |
| 502 Bad Gateway | 容器状态、真实端口、host nginx 还是容器代理 | `curl` 回环健康检查；容器代理不能直接用自己的 127.0.0.1 |
| 容器反复重启 | `.env` 校验、数据写权限、图片读取权限、合集版本 hash | 查看仅 PaidDrive 的日志，按具体错误修复 |
| `PermissionError` 读取图片 | 导入目录是否是 0700，group 是否为 10001 | 按第 7.2 节设置 content 组及 750／640，再做容器读取测试 |
| SQLite 无法写入／只读数据库 | `/data` 挂载、UID10001、父目录写权限、磁盘 | 修正 data 权限和容量，不把数据库移到 `/assets` |
| 全站很快出现 429 | 所有客户端是否被识别为同一网桥来源 | 核对 `FORWARDED_ALLOW_IPS` 和代理覆盖头，不设通配信任 |
| 正式页面提交报来源无效 | `APP_URL` 与实际 HTTPS 源、域名或端口 | 改正确 APP_URL 并重建容器；不关闭来源检查 |
| live 启动失败 | HTTPS、ZPay 基础地址／ID／密钥、是否仍为 file 邮件 | 修正配置；demo 成功不代表 live 配置完整 |
| 付款页打不开 | 网关是否匹配、merchant 配置、表单提交及通道要求 | 对照原集成及实际 ZPay 文档；不在日志中输出 KEY |
| 平台已付但网页未解锁 | 本地订单、回调 HTTP 状态、查询连接、金额／商户匹配 | 原浏览器查询付款；核对服务端状态，不能相信 URL 参数 |
| 回调一直重试 | 是否返回 `success`、是否验签／查询失败、响应耗时 | 先核实真实交易；重复通知应幂等，不改成无条件成功 |
| 微信付款后换了浏览器 | 原 cookie 不在新环境 | 原浏览器重开合集／查询，或用已验证邮箱、客服恢复 |
| 收不到验证邮件 | MAIL_MODE、SMTP TLS／账号、出站网络、发件身份、垃圾箱 | 修复后重新申请链接；不要用“队列有记录”代替实际收件 |
| 找回链接显示失效 | 是否过期、是否已用过、APP_URL 是否正确、模式是否切换 | 重新申请；演示 token 不用于 live |
| 支付后某张图返回 410 | 已售文件被删除或内容 hash 改变 | 恢复原文件；新内容使用新版本，不伪造同版本 hash |
| ZIP 下载失败／容器内存紧张 | 合集总大小、并发下载、`/tmp` 的 tmpfs、可用内存 | 当前 ZIP 在临时目录生成；大合集需明确调整临时存储与容量策略后再售卖 |
| 保存二维码没有进入相册 | 浏览器 download 行为 | 长按图片或截图后识别；不要声称点击就一定存相册 |
| 升级后历史购买不见了 | 是否换了 data 挂载、误用新目录、切换 APP_MODE | 找回正确持久目录和模式；不要立即创建替代购买记录 |
| 足球站点受影响 | 是否覆盖原 proxy 文件、端口冲突、资源耗尽 | 撤回本次专属改动，保留既有业务与数据，再核对原指南 |

## 17. 本手册与原 CVM 指南的最终对齐清单

取得原指南后，逐项填实，不用重新设计整个项目：

1. 把本文示例操作系统／用户／目录改成原环境实际值。
2. 确认原项目使用宿主机代理还是容器代理，选择对应分支。
3. 确认新子域只新增一个站点，不改旧域名的 DNS 或配置。
4. 核实 8091 或选定端口、Compose 项目名、数据目录均不冲突。
5. 对齐证书获取和自动续期方法，不引入重复管理。
6. 核实代理来源 IP、内容权限、私有目录与共享缓存设置。
7. 用现有 ZPay 实际文档确认网关和支付通道，而非只凭名称匹配。
8. 保留真实验证结果：何时、哪个域名、哪种设备、哪笔测试订单、是否退款及撤权；不要记录密钥或完整恢复 token。

完成这些核对及真实验收后，才能把状态从“可运行的参考部署包”更新为“已按原 CVM 方法部署并验证”。

## 官方参考资料

- [腾讯云：A 记录](https://cloud.tencent.com/document/product/302/3449)
- [腾讯云：主机记录和记录值](https://cloud.tencent.com/document/product/302/3468)
- [腾讯云：添加安全组规则](https://cloud.tencent.com/document/product/213/112614)
- [腾讯云：安全组问题](https://cloud.tencent.com/document/faq/213/43698)
- [腾讯云：ICP 备案接入相关](https://cloud.tencent.com/document/product/243/43878)
- [nginx：server names](https://nginx.org/en/docs/http/server_names.html)
- [nginx：HTTP proxy 模块](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)
- [Docker Engine：安装](https://docs.docker.com/engine/install/)
- [Docker：端口发布](https://docs.docker.com/engine/network/port-publishing/)
- [Docker Compose：网络](https://docs.docker.com/compose/how-tos/networking/)
- [Docker Compose：环境变量插值](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation)
- [Uvicorn：代理来源设置](https://uvicorn.dev/settings/)
- [Certbot：使用指南](https://eff-certbot.readthedocs.io/en/stable/using.html)
- [Let's Encrypt：验证方式](https://letsencrypt.org/docs/challenge-types/)
- [Let's Encrypt：IPv6 验证](https://letsencrypt.org/docs/ipv6-support/)
- [ZPay：开发文档](https://z-pay.cn/doc.html)
- [Python：SQLite backup](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup)
