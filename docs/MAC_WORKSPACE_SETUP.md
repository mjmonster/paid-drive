# 在 Mac 上创建 PaidDrive 工作目录

目标目录是 `/Users/mewtwo/Workspace/PaidDrive`。

**此安装脚本尚未在你的 Mac 上运行；当前构建环境未替你创建目标目录。**当前构建环境无法访问你的 Mac 文件系统。下面的步骤需要在 Mac 终端中执行。

## 1. 解压并检查

将交付的源代码压缩包解压，在终端进入解压后的项目根目录。该目录应直接包含 `Dockerfile`、`compose.yaml`、`app/` 和 `scripts/`。

```bash
python3 scripts/install_macos_workspace.py --dry-run
```

检查输出中的源项目和目标目录。`--dry-run` 不创建目录，可跨平台运行；如果当前环境不存在 Mac 工作区，也会说明实际安装前需要存在的父目录。

## 2. 创建新工作目录

确认 `/Users/mewtwo/Workspace` 已存在后，在同一源项目目录执行：

```bash
python3 scripts/install_macos_workspace.py
```

脚本只会创建一个**全新的** `/Users/mewtwo/Workspace/PaidDrive`。如果该目录已经存在，即使为空，也会停止，不会覆盖或合并。不要通过删除现有项目来绕过这个检查；如需另建副本，可明确指定其他尚不存在的目标：

```bash
python3 scripts/install_macos_workspace.py --destination /Users/mewtwo/Workspace/PaidDrive-test
```

实际安装仅支持 macOS，没有其他平台的强制安装选项。脚本只读取解压后的源项目，不修改 `soccer-match-analyzer` 或 `/Users/mewtwo/Images`，也不执行云服务器部署。

复制范围是应用代码、合集内容、部署模板、脚本、测试和文档。运行数据库、演示邮件、真实 `.env`、常见密钥文件、缓存、`node_modules`、`.git`、`.openai` 和截图目录不会复制。`.env.example` 作为配置模板保留；文件的可执行权限也会保留。脚本会拒绝要复制的符号链接；复制失败时清理本次创建的不完整目标目录。

## 3. 本地启动

先确认 Mac 已安装 Python 3.12：

```bash
python3.12 --version
```

如果找不到命令，先安装 Python 3.12；不要假定系统自带的 `python3` 就是这个版本。然后在新项目目录执行：

```bash
cd /Users/mewtwo/Workspace/PaidDrive
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 <http://localhost:8000/>。默认是演示模式，不会真实扣款；演示邮件保存在新项目的 `data/outbox/`。脚本不会自动安装依赖、启动服务或导入原始图片。

图片导入见项目根目录的 [README.md](../README.md)，完整腾讯云与子域名配置见 [TENCENT_CVM_DEPLOYMENT.md](TENCENT_CVM_DEPLOYMENT.md)。如需对齐原项目的部署方法，只提供相关部署脚本、Docker/Compose/nginx 配置模板或脱敏说明；不要将真实商户密钥、SMTP 密码、私钥或生产 `.env` 放入待分享的源代码包。
