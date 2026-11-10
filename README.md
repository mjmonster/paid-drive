# PaidDrive

一个轻量的付费图片集 MVP：在手机上左右滑动一叠图片卡片，先预览三张图片，一次购买固定合集，之后可反复查看和下载。后端使用 Python/FastAPI，数据库使用 SQLite；前端为原生 HTML、CSS 和 JavaScript，不需要 Node 构建流程。

**当前交付状态：**项目可在明确标注的演示模式下运行，内含九幅原创矢量风景占位插画，以及不可扫码的微信客服占位图。插画用于展示，不是实拍照片。目前尚未部署到腾讯云 CVM。部署手册已核对相邻足球项目的权威 `docs/DEPLOYMENT-TENCENT.md`：复用已有腾讯云服务器的宿主机 Nginx、Certbot 和 Docker，为 PaidDrive 增加独立 Compose 项目及回环端口 8091。服务器当前状态仍需上线前复查；真实图片尚未导入。

## 项目位置与部署手册

当前 Mac 工作目录为 **`/Users/mewtwo/Workspace/PaidDrive`**，与 `soccer-match-analyzer` 并列，源码已存入私有仓库 [mjmonster/paid-drive](https://github.com/mjmonster/paid-drive)。现有目录无需再次安装。仅当从源码包安装到一个尚不存在的 Mac 目录时，才使用下面的安装器：

```bash
python3 scripts/install_macos_workspace.py --dry-run
python3 scripts/install_macos_workspace.py
```

安装脚本要求 `/Users/mewtwo/Workspace` 已存在，拒绝覆盖任何已有目标目录；不会修改足球项目或原始图片。实际复制只允许在 macOS 上运行。

- [Mac 工作区安装说明](docs/MAC_WORKSPACE_SETUP.md)：落盘位置、安装范围、本地启动。
- [腾讯云 CVM 与子域名详细部署手册](docs/TENCENT_CVM_DEPLOYMENT.md)：已有服务器检查、域名解析、Docker、目录权限、Nginx、HTTPS、ZPay、邮箱、验证、备份、更新与回滚。
- [验证记录](VALIDATION.md)：已经完成的检查，以及仍需在真实服务器和手机上验证的部分。

**现有 CVM 拓扑已按足球项目文档核对。**足球应用本身使用原生 systemd 和端口 8090，另一站点已经使用 Docker。PaidDrive 使用现成的 Python 3.12 容器，复用宿主机代理。详细手册采用 `/opt/paiddrive` 保存源码、`/var/lib/paiddrive` 保存运行数据和真实内容；其服务器专用 Compose override 会替换下文便携模板的相对目录挂载。

## 已包含的功能

- 每个合集有独立公开链接，以叠卡形式展示图片，支持左右滑动浏览。
- 前三张展示真实的免费预览图片；后续卡片展示合成的剪影／模糊占位画面和解锁提示。
- 一次购买后可反复查看、下载单张图片，或下载整个合集的 ZIP 文件。
- 邮箱为选填项，也可以在仍有购买权限的浏览器里稍后添加。
- 邮箱验证与临时、单次使用的访问恢复链接；无需设置密码或注册账号。
- 当前浏览器记住访问状态；丢失访问时可通过微信客服人工处理。
- 展示订单编号，方便客服查找交易；订单编号本身不能解锁内容。
- 演示模式提供明确标注的模拟支付；真实支付通过单独配置的 ZPay 接口接入。

本版本不包含创作者注册、网页上传、分账提现、周期订阅或永久兑换码。

## 叠卡画廊与解锁方式

页面围绕一叠可横向滑动的图片卡片展开，购买入口与当前合集放在一起，不使用长图片网格或购买侧栏。买家可以先逐张看完前三张免费图片，再继续滑动查看尚未解锁的卡片位置。

未解锁卡片中的剪影、色块和模糊效果由独立的占位图形合成，**不包含对应付费原图的像素**。网页不会先下载付费原图，再用 CSS 模糊或遮罩隐藏。后端对每次付费图片和合集 ZIP 请求检查购买权限；单纯更改页面样式、猜测文件地址或修改回跳参数都不能代替购买。

一次付款解锁整个固定合集，不需要逐张付费。确认付款后，原来的占位卡片替换为真实图片，仍可在同一叠卡画廊中继续浏览，并使用单张或整套下载入口。购买权限记录在服务器，邮箱恢复和微信人工客服流程保持不变。

这里提供的是付费访问控制，不是 DRM。已购买的用户可以下载图片，因此不承诺阻止其截图、复制或再次分享已取得的文件。

## 手机端使用说明

网站以手机浏览为主要使用场景，桌面端也使用同一套叠卡浏览方式。浏览、预览、购买、恢复访问和联系客服均通过网页完成。横向手势用于切换卡片，纵向滚动用于正常浏览页面；具体设备上的手势和布局检查结果见 `VALIDATION.md`。

- **微信内打开与系统浏览器的会话可能不同。**在微信里购买后，改用 Safari 或 Chrome 打开链接，不一定会直接带上原先的解锁状态。已验证邮箱的买家可以通过邮箱恢复；没有绑定邮箱的买家可以联系微信客服核实订单。
- **ZIP 下载得到的是压缩文件。**它不会直接把整套图片保存到手机相册。买家需要在手机的文件管理应用中打开、解压，再按需保存图片；也可以单独打开和下载图片。
- **真实微信 H5 支付和支付后回跳尚未完成验证。**没有商户配置和真实移动设备验证，不能保证微信内浏览器、Safari、Chrome 的支付跳转行为完全一致。上线前需要用实际域名和支付通道分别检查。
- 同一部手机无法直接用相机扫描自己屏幕上的客服二维码。支持面板显示真实二维码后，用户可以尝试长按图片或保存二维码；如果浏览器只下载到文件目录，可以截图，再在微信扫一扫中从相册选择。当前二维码只是清楚标注的占位图。

## 在 Mac 上本地运行

使用已安装的 Python 3.12，在项目目录中执行；先用 `python3.12 --version` 确认解释器：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 [http://localhost:8000/c/slow-days](http://localhost:8000/c/slow-days)。默认配置为 `APP_MODE=demo`、`APP_URL=http://localhost:8000`，邮件写入本地文件。点击页面中的**模拟支付**可以验证解锁流程，不会向任何人收款；真实支付模式下不能调用模拟支付接口。

本地 `uvicorn` 不会自动读取 `.env`，而是使用默认值和已导出的环境变量。例如需要换一个本地端口：

```bash
APP_URL=http://localhost:8010 python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

数据库和演示邮件目录位于 `data/`。测试邮箱验证或恢复访问时，可填写测试邮箱，再打开 `data/outbox/` 中生成的 `.eml` 文件，使用其中的链接。演示邮件只保存在本地，不会真的发送到邮箱；该目录没有公开的网页访问入口。打开链接后仍需点击确认，链接预览请求不会直接消耗恢复凭证。

## 导入你的图片集

在存有图片的 Mac 上，进入本项目目录后执行：

```bash
python scripts/import_collection.py /Users/mewtwo/Images --slug my-collection --title "我的图片集" --price-cents 1900
```

脚本会复制支持的图片文件到带版本号的合集目录，并更新 `content/collections.json`。修改目录配置或导入图片后，重启应用，再打开 `/c/my-collection` 查看。

如果手动配置，请参照已有的 `content/collections.json`。每个合集包含 `id`、`slug`、`version`、`title`、`subtitle`、`description`、`creator`、`price_cents`、`currency`、`preview_count` 和有序的 `items` 列表。每张图片包含 `id`、相对于 `content/` 的 `file` 路径、`title`、`width` 和 `height`。价格以整数分表示，例如 `1900` 表示人民币 19.00 元；当前 ZPay 适配器使用人民币。

`items` 的顺序决定哪三张图片可以免费预览。预览数量之外至少要保留一张付费图片。文件路径只能位于 `CONTENT_ROOT` 内；不要通过 nginx 的 `root`/`alias`、静态目录挂载或公开对象存储，把整个原图目录直接暴露出去。

### 固定合集与版本更新

应用首次加载一个合集版本后，该版本的图片文件、排列顺序和预览范围就会固定。直接修改图片字节或图片集合而不更换版本号，应用会拒绝加载。价格和说明文案可以为后续订单调整，已创建的订单保留当时确认的价格。

如果要出售另一套图片，应创建新的版本及独立文件目录。保留旧文件，方便之前的买家继续访问自己购买的版本。不要通过覆盖或删除已售出图片的方式更新合集。

### 替换微信客服占位图

例如，将真实二维码放到 `content/support/wechat.png`。本地运行时，将 `SUPPORT_QR_PATH` 设置为该文件的绝对路径；Docker 内使用 `/app/content/support/wechat.png`。支持面板会显示对应图片。留空时显示明确标注的占位图，该图不能扫码联系客服。

## 使用 Docker 部署到 CVM

完整操作顺序见 [腾讯云 CVM 与子域名详细部署手册](docs/TENCENT_CVM_DEPLOYMENT.md)。下文只概述本项目配置。使用前需要与足球分析器实际使用的 Docker/Compose、反向代理、域名和 TLS 配置核对。PaidDrive 使用独立的应用目录和代理站点配置。

默认服务只监听宿主机的 **127.0.0.1:8091**，由 nginx 或已有反向代理将公开子域名转发到该端口。SQLite 数据库持久化在 `./data`，合集文件从 `./content` 以只读方式挂载。此 MVP 使用一个应用工作进程。

**原图目录必须位于所有公开静态根目录之外。**附带的 nginx 模板只将请求转发到 FastAPI，没有把合集目录配置为 `root` 或 `alias`；应用的公开 `/assets` 也只服务 `app/static/`。应用启动时会检查解析符号链接后的路径：如果 `CONTENT_ROOT` 与公开静态目录重合或互相包含，就会拒绝启动。`./content:/app/content:ro` 只是供 Python 读取文件的只读挂载，本身不等于访问控制。适配现有 CVM 配置时，保留这一区分，让付费原图和 ZIP 始终经过后端购买权限检查，并关闭这类响应的共享缓存。

```bash
cp .env.example .env
chmod 600 .env
mkdir -p data
sudo chown -R 10001:10001 data
sudo chmod 700 data
sudo chgrp -R 10001 content
sudo find content -type d -exec chmod 750 {} +
sudo find content -type f -exec chmod 640 {} +
docker compose up -d --build
```

上述文件所有权命令用于 Linux CVM 的首次部署，`.env` 已存在时不要覆盖。容器以 UID/GID `10001` 运行，该身份需要读写数据目录、读取合集目录。导入脚本创建的合集目录默认较私密，因此每次导入或同步后都需重新检查内容组权限；保留运营账号为内容文件所有者。在 Mac 上快速预览时，建议直接使用前面的 Python 启动方式。

示例 `.env` 使用 `APP_URL=http://localhost:8091`，对应 Docker 演示端口。Compose 会读取 `.env`，并将数据库、合集和邮件目录覆盖为容器内路径。可以查看服务状态和启动错误：

```bash
docker compose ps
docker compose logs --tail=100 paid-drive
```

如果演示服务运行在远程 CVM，可使用 SSH 隧道从本机访问，不需要把 8091 端口直接开放到公网：

```bash
ssh -L 8091:127.0.0.1:8091 your-user@your-cvm-host
```

随后打开 [http://localhost:8091](http://localhost:8091)。随包提供的演示配置不用于真实收款，也不应通过公开反向代理暴露；模拟支付能够解锁合集。初始 HTTP 模板仅开放证书验证文件，其余请求返回准备中的 503 页面。

`PAIDDRIVE_PORT` 默认 `8091`；若端口被占用，需要同时调整该变量和 Nginx 上游。`FORWARDED_ALLOW_IPS` 应包含实际连接应用的可信代理地址。宿主机 Nginx 通过 Docker 映射端口访问时，该地址可能是 Docker 网桥网关；必须在该服务器上核实。配置方法见详细手册。修改环境变量后需重建容器配置，单独执行 `docker compose restart` 不会读取新的环境变量。

### 配置真实支付与邮件

在私有 `.env` 中设置：

| 配置项 | 真实运行环境中的值 |
| --- | --- |
| `APP_MODE` | `live` |
| `APP_URL` | 实际 HTTPS 站点源地址，例如 `https://drive.example.com`；不要包含路径或查询参数。 |
| `ZPAY_BASE_URL` | 现有 ZPay 接入实际使用的 HTTPS API 基础地址；代码会追加 `submit.php` 和 `api.php`，不要填写商户后台或完整接口路径。 |
| `ZPAY_PID`、`ZPAY_KEY` | 商户 ID 和商户密钥。 |
| `MAIL_MODE` | `smtp` 开启邮件恢复；`disabled` 关闭邮箱收集和邮件恢复。 |
| `SMTP_HOST`、`SMTP_PORT`、`SMTP_FROM` | 邮件服务配置。 |
| `SMTP_USER`、`SMTP_PASSWORD` | 邮件服务需要的认证信息。 |
| `SMTP_STARTTLS` | STARTTLS 通常使用端口 587，值为 `true`；隐式 TLS 使用端口 465。 |
| `SUPPORT_QR_PATH` | 容器内真实客服二维码图片的路径。 |

真实支付模式要求 HTTPS 和完整的 ZPay 配置。文件邮件仅用于演示模式。SMTP 邮件任务持久化保存在 SQLite 中，由应用后台任务发送。如果 `MAIL_MODE=disabled`，当前浏览器仍可保留购买权限；需要恢复时使用微信客服人工处理。

ZPay 接入地址如下：

- 服务端通知：`https://your-domain/api/payments/zpay/notify`
- 浏览器回跳：`https://your-domain/payment/return`

支付确认由后端完成，检查通知签名、订单、商户、金额和支付平台查询结果。浏览器回跳参数本身不能授予访问权限。重复通知不能重复发放购买权限。

提供两个分阶段的宿主机 Nginx 模板：`deploy/nginx.http.conf.example` 只服务 ACME 验证和准备中页面；`deploy/nginx.conf.example` 在证书已存在后提供正式 HTTPS 反向代理。使用 `scripts/render_deploy_config.py` 替换实际子域名和端口；脚本仅生成新文件，不修改 DNS、不申请证书、不覆盖现有配置。先申请证书、配置正式模式和真实客服二维码，再开放正式代理，具体顺序见详细手册。

重新加载现有代理前先检查配置；修改 `.env` 后重新创建 PaidDrive 容器：

```bash
sudo nginx -t
sudo systemctl reload nginx
docker compose up -d --build --force-recreate
```

由于尚未提供商户和邮件服务配置，真实 ZPay 支付、SMTP 投递以及微信内支付回跳尚未验证。接待真实买家前，应替换图片和二维码占位内容，并在实际域名和支付通道上完成支付、再次访问、下载和邮箱恢复的完整检查。退款后还应撤销相应访问权限；退款操作本身仍由人工处理。

## 人工客服恢复

恢复访问前，先对照商户交易记录核实付款归属。仅知道订单编号，或仅提供未经核实的截图，都不足以自动解锁。

```bash
python -m app.admin list-orders
python -m app.admin restore --reference ORDER_REFERENCE
python -m app.admin revoke --reference ORDER_REFERENCE
```

在 Docker 中执行时，在命令前加 `docker compose exec paid-drive`：

```bash
docker compose exec paid-drive python -m app.admin list-orders
```

`restore` 仅能为本地状态已确认为 `paid` 的订单生成临时访问链接，应作为私有凭证，通过客服对话人工发给本人。若商户平台显示已付、但应用仍待确认，应先由原购买浏览器查询订单，完成服务端查单；不要手工把待付订单改成已付。`revoke` 撤销访问权限，不会通过 ZPay 发起退款。管理操作仅提供本地命令行入口，没有公开的管理接口。

## 备份

订单数据库和合集原图需要一起备份。SQLite 使用 WAL 时，直接复制数据库主文件可能漏掉已经提交的数据；附带脚本使用 Python 的 SQLite 备份接口生成一致的数据库快照，再与 `content/` 一起打包。

```bash
python scripts/backup.py --output backups/paiddrive-before-update.tar.gz
```

也可以在运行中的容器内执行：

```bash
docker compose exec -T paid-drive python scripts/backup.py --output /data/backups/paiddrive-before-update.tar.gz
```

每次备份使用新的文件名。如果真实二维码位于 `content/` 外，可增加 `--support-qr /absolute/path/to/qr.png`。备份包含客户、订单和会话数据，应私密保管，并另外保存一份到 CVM 之外。脚本不会单独打包 `.env`、日志或邮件目录；商户和 SMTP 配置请通过自己的安全方式另外备份。

容器生成的备份归 UID `10001` 所有且使用私有权限，普通 SSH 账号可能无法直接下载；详细手册提供导出到运营账号专属目录再传出的命令。不要为了下载备份而将数据目录或归档改成公开可读。

备份期间暂停修改合集配置，让图片、配置和数据库保持对应。恢复时，先停止 PaidDrive，将备份解压到空的临时目录，再将数据库及对应的合集文件恢复到空的数据和内容目录，补齐私有配置并修正文件所有权。不要让恢复后的数据库与旧的 `-wal` 或 `-shm` 文件混用。启动后先检查一笔已有购买，再恢复对外服务。

## 检查与项目结构

```bash
python -m unittest discover -s tests -v
```

应用测试主要覆盖支付、访问控制和恢复流程，不依赖真实商户账号。自动化测试不能代替真实支付或 SMTP 投递检查。已完成的检查和剩余限制见 `VALIDATION.md`。

| 路径 | 用途 |
| --- | --- |
| `app/` | FastAPI 接口、SQLite 记录、支付、会话、恢复和客服命令行工具。 |
| `app/static/` | HTML/CSS/JS 和默认客服占位图。 |
| `content/collections.json` | 由运营方维护的合集配置。 |
| `content/images/` | 私有合集原图和随包提供的占位插画。 |
| `scripts/import_collection.py` | 将本地图片导入到带版本号的合集。 |
| `scripts/backup.py` | 一致的 SQLite 和合集文件备份。 |
| `scripts/install_macos_workspace.py` | 在 Mac 上创建全新的 `/Users/mewtwo/Workspace/PaidDrive`。 |
| `scripts/render_deploy_config.py` | 校验子域名并生成新 Nginx 配置，不直接改动服务器。 |
| `data/` | 运行时数据库及演示邮件，不提交到代码仓库，也不打入镜像。 |
| `deploy/nginx.http.conf.example` | 证书申请阶段，仅开放 ACME 文件。 |
| `deploy/nginx.conf.example` | 证书就绪后的独立子域名 HTTPS 反向代理模板。 |
| `docs/TENCENT_CVM_DEPLOYMENT.md` | 腾讯云 CVM 与子域名详细部署步骤。 |

主要路径包括 `/c/{slug}`、`/api/bootstrap`、`/api/orders`、`/api/email/attach`、`/api/access/request`、`/api/access/redeem` 和 `/health`。付费图片及 ZIP 下载均经过后端权限检查。

### 部署参考资料

- [FastAPI：容器与 Docker](https://fastapi.tiangolo.com/deployment/docker/)
- [Python 3.12：SQLite 数据库备份接口](https://docs.python.org/3.12/library/sqlite3.html#sqlite3.Connection.backup)
- [Docker Compose：环境变量优先级](https://docs.docker.com/compose/how-tos/environment-variables/envvars-precedence/)
