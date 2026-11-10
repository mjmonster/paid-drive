"""Render a separate host-Nginx virtual host without changing a live server."""

import argparse
import ipaddress
from pathlib import Path
import re
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = {"http": "nginx.http.conf.example", "https": "nginx.conf.example"}
LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def checked_domain(value: str) -> str:
    """Allow only a DNS hostname, never nginx directives, URLs, or IPs."""
    if not value or value != value.strip() or any(c in value for c in "/\\:@*?#;{}\r\n\t"):
        raise ValueError("请填写完整域名，例如 drive.example.com；不要带协议、端口、路径或通配符。")
    try:
        domain = value.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("域名格式无效。") from exc
    labels = domain.split(".")
    if len(domain) > 253 or len(labels) < 2 or not all(LABEL.fullmatch(label) for label in labels):
        raise ValueError("域名格式无效，请使用完整的 DNS 域名。")
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        return domain
    raise ValueError("这里需要域名，不能使用 IP 地址。")


def render_config(domain: str, phase: str, port: int = 8091) -> str:
    domain = checked_domain(domain)
    if phase not in TEMPLATES:
        raise ValueError("部署阶段必须为 http 或 https。")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("端口必须是 1 到 65535 之间的整数。")
    source = (PROJECT_ROOT / "deploy" / TEMPLATES[phase]).read_text(encoding="utf-8")
    return source.replace("drive.example.com", domain).replace("127.0.0.1:8091", f"127.0.0.1:{port}")


def write_new_config(path: Path, content: str) -> None:
    # Exclusive creation also rejects symlinks and avoids overwriting a live vhost.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        output.write(content)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="为 PaidDrive 生成独立子域名配置，不修改服务器。")
    parser.add_argument("--domain", required=True, help="完整域名，例如 drive.example.com")
    parser.add_argument("--phase", choices=tuple(TEMPLATES), required=True, help="先 http，取得证书后再 https")
    parser.add_argument("--port", type=int, default=8091, help="与 PAIDDRIVE_PORT 相同的本机端口，默认 8091")
    parser.add_argument("--output", type=Path, required=True, help="新配置文件路径；拒绝覆盖已有文件")
    args = parser.parse_args(argv)
    try:
        text = render_config(args.domain, args.phase, args.port)
        write_new_config(args.output, text)
    except FileExistsError:
        parser.error("输出文件已存在；请检查已有内容并选择一个新的输出文件名。")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(f"已生成：{args.output.absolute()}")
    print("这只是配置文件，尚未修改 DNS、申请证书或加载 nginx。请按部署手册检查后启用。")
    if args.phase == "https":
        print("HTTPS 模板假定证书位于 /etc/letsencrypt/live/域名/；启用前确认文件存在。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
