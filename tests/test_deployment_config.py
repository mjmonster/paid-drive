"""Deployment helper checks; no Nginx, DNS, certificate or server is changed."""

from pathlib import Path
import tempfile
import unittest

from scripts.render_deploy_config import checked_domain, render_config, write_new_config


class NginxConfigurationTests(unittest.TestCase):
    def test_rejects_directives_urls_wildcards_and_ip_addresses(self):
        for candidate in ("site.example.com; root /tmp", "example.com\nserver", "https://site.example.com", "*.example.com", "192.0.2.1", "localhost", "site.example.com:8091", "site_example.com"):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                checked_domain(candidate)

    def test_accepts_and_normalizes_hostname_without_inserting_directives(self):
        self.assertEqual(checked_domain("Drive.Example.COM."), "drive.example.com")
        self.assertTrue(checked_domain("图片.example.com").startswith("xn--"))

    def test_http_bootstrap_does_not_publish_demo_or_require_a_certificate(self):
        result = render_config("photos.example.org", "http", 8092)
        self.assertIn("server_name photos.example.org;", result)
        self.assertNotIn("proxy_pass", result)
        self.assertIn("return 503", result)
        self.assertIn("location ^~ /.well-known/acme-challenge/", result)
        self.assertNotIn("ssl_certificate ", result)
        self.assertNotIn("listen 443", result)
        self.assertIn("try_files $uri =404;", result)

    def test_https_preserves_acme_and_routes_originals_through_application(self):
        result = render_config("photos.example.org", "https", 8092)
        self.assertIn("proxy_pass http://127.0.0.1:8092;", result)
        self.assertIn("location / {\n        return 301 https://photos.example.org$request_uri;", result)
        self.assertIn("location ^~ /.well-known/acme-challenge/", result)
        self.assertIn("/etc/letsencrypt/live/photos.example.org/fullchain.pem", result)
        self.assertIn("proxy_set_header X-Forwarded-For $remote_addr;", result)
        self.assertNotIn("root /app/content", result)
        self.assertNotIn("alias /", result)
        self.assertIn("proxy_cache off;", result)

    def test_never_overwrites_existing_file_or_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "site.conf"
            write_new_config(path, "original")
            with self.assertRaises(FileExistsError):
                write_new_config(path, "replacement")
            self.assertEqual(path.read_text(), "original")
            link = Path(directory) / "link.conf"
            link.symlink_to(path)
            with self.assertRaises(FileExistsError):
                write_new_config(link, "replacement")
            self.assertEqual(path.read_text(), "original")

    def test_rejects_invalid_phase_and_port(self):
        for phase, port in (("tls", 8091), ("http", 0), ("https", 65536)):
            with self.subTest(phase=phase, port=port), self.assertRaises(ValueError):
                render_config("drive.example.com", phase, port)


if __name__ == "__main__":
    unittest.main()
