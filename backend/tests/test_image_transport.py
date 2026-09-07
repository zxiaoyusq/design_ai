"""解析覆盖只替换 TCP 目标，保留原始域名及 HTTPS 证书校验边界。"""

import io
import json
import socket
import ssl
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError
from urllib.request import Request

from scripts.image_transport import create_resolved_opener
from scripts.prepare_trend_data import download_image
from scripts.prepare_user_research_data import download_research_image, main
from tests.test_trend_data_preparation import make_png
from tests.test_user_research_preparation import response, snapshot, user


class ResolvedImageTransportTestCase(unittest.TestCase):
    def make_tls_socket(self) -> MagicMock:
        tls_socket = MagicMock()
        tls_socket.makefile.side_effect = lambda *args, **kwargs: io.BytesIO(
            b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok",
        )
        return tls_socket

    def test_mapped_and_unmapped_https_keep_original_host_sni_and_default_validation(self) -> None:
        domain = "images.fixture.test"
        original_create_connection = socket.create_connection
        original_getaddrinfo = socket.getaddrinfo
        for resolutions, expected_tcp_host in (
            ({domain: "192.0.2.44"}, "192.0.2.44"),
            ({"different.fixture.test": "192.0.2.44"}, domain),
            ({domain: "2001:db8::44"}, "2001:db8::44"),
        ):
            with self.subTest(resolutions=resolutions):
                tls_socket = self.make_tls_socket()
                raw_socket = MagicMock()
                request = Request(f"https://{domain}:8443/image.png?size=large")
                with patch("urllib.request.getproxies", return_value={}):
                    opener = create_resolved_opener(resolutions)
                self.assertIs(socket.create_connection, original_create_connection)
                self.assertIs(socket.getaddrinfo, original_getaddrinfo)
                with (
                    patch("socket.create_connection", return_value=raw_socket) as connector,
                    patch.object(ssl.SSLContext, "wrap_socket", autospec=True, return_value=tls_socket) as wrap,
                ):
                    with opener(request, timeout=4) as result:
                        self.assertEqual(result.read(), b"ok")
                        self.assertEqual(result.url, request.full_url)
                    self.assertIs(socket.create_connection, connector)
                    self.assertIs(socket.getaddrinfo, original_getaddrinfo)

                self.assertEqual(connector.call_args.args[0], (expected_tcp_host, 8443))
                self.assertEqual(wrap.call_args.kwargs["server_hostname"], domain)
                ssl_context = wrap.call_args.args[0]
                self.assertEqual(ssl_context.verify_mode, ssl.CERT_REQUIRED)
                self.assertTrue(ssl_context.check_hostname)
                self.assertIs(wrap.call_args.args[1], raw_socket)
                request_bytes = b"".join(call.args[0] for call in tls_socket.sendall.call_args_list)
                self.assertIn(f"Host: {domain}:8443\r\n".encode(), request_bytes)
                self.assertIn(b"GET /image.png?size=large HTTP/1.1\r\n", request_bytes)
                self.assertIs(socket.create_connection, original_create_connection)
                self.assertIs(socket.getaddrinfo, original_getaddrinfo)

    def test_certificate_verification_failure_is_propagated_without_unverified_retry(self) -> None:
        with patch("urllib.request.getproxies", return_value={}):
            opener = create_resolved_opener({"images.fixture.test": "192.0.2.44"})
        with (
            patch("socket.create_connection", return_value=MagicMock()) as connector,
            patch.object(
                ssl.SSLContext, "wrap_socket", autospec=True,
                side_effect=ssl.SSLCertVerificationError("fixture certificate mismatch"),
            ) as wrap,
        ):
            with self.assertRaises(URLError) as raised:
                opener("https://images.fixture.test/image.png", timeout=4)

        self.assertIsInstance(raised.exception.reason, ssl.SSLCertVerificationError)
        connector.assert_called_once()
        wrap.assert_called_once()
        self.assertTrue(wrap.call_args.args[0].check_hostname)
        self.assertEqual(wrap.call_args.args[0].verify_mode, ssl.CERT_REQUIRED)

    def test_invalid_hostnames_and_non_ip_targets_are_rejected_without_network_access(self) -> None:
        cases = (
            {"": "192.0.2.44"}, {" images.fixture.test": "192.0.2.44"},
            {"https://images.fixture.test": "192.0.2.44"},
            {"images.fixture.test:443": "192.0.2.44"},
            {"images.fixture.test/path": "192.0.2.44"},
            {"images..fixture.test": "192.0.2.44"}, {"-invalid.test": "192.0.2.44"},
            {"images.fixture.test": "another.fixture.test"},
            {"images.fixture.test": "999.0.0.1"}, {"images.fixture.test": "192.0.2.44:443"},
            {"images.fixture.test": "fe80::1%en0"}, {"images.fixture.test": None},
            {"Images.Fixture.Test": "192.0.2.44", "images.fixture.test": "192.0.2.45"},
        )
        with patch("socket.create_connection") as connector, patch("socket.getaddrinfo") as resolver:
            for resolutions in cases:
                with self.subTest(resolutions=resolutions), self.assertRaises(ValueError):
                    create_resolved_opener(resolutions)
        connector.assert_not_called()
        resolver.assert_not_called()

    def test_each_opener_copies_its_mapping_without_changing_other_openers(self) -> None:
        resolutions = {"Images.Fixture.Test.": "192.0.2.44"}
        with patch("urllib.request.getproxies", return_value={}):
            first = create_resolved_opener(resolutions)
            second = create_resolved_opener({})
        resolutions["Images.Fixture.Test."] = "192.0.2.45"
        for opener, expected in ((first, "192.0.2.44"), (second, "images.fixture.test")):
            with (
                patch("socket.create_connection", return_value=MagicMock()) as connector,
                patch.object(ssl.SSLContext, "wrap_socket", autospec=True, return_value=self.make_tls_socket()),
            ):
                with opener("https://images.fixture.test/image.png", timeout=4) as result:
                    self.assertEqual(result.read(), b"ok")
            self.assertEqual(connector.call_args.args[0], (expected, 443))


class ImageTransportIntegrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output_dir = Path(directory.name)
        self.png = make_png(2, 3, (100, 120, 140))
        self.url = "https://images.fixture.test/image.png"

    def open_image(self, request: Request, **kwargs: object) -> io.BytesIO:
        result = io.BytesIO(self.png)
        result.url = request.full_url
        return result

    def test_optional_opener_is_used_by_both_downloaders_and_preserves_original_url(self) -> None:
        cases = (
            (download_image, {
                "image_id": "trend-1_001", "trend_id": "trend-1", "index": 1, "url": self.url,
            }),
            (download_research_image, {
                "id": "image_fixture", "url": self.url, "enjoy_count": 1, "responses": [],
            }),
        )
        for downloader, record in cases:
            with self.subTest(downloader=downloader.__name__):
                opener = MagicMock(side_effect=self.open_image)
                with patch("scripts.prepare_trend_data.urlopen") as default_opener:
                    result = downloader(record, self.output_dir, retries=0, opener=opener)
                self.assertEqual(result["status"], "downloaded", result)
                self.assertEqual(result["url"], self.url)
                self.assertEqual(result["resolved_url"], self.url)
                self.assertEqual(opener.call_args.args[0].full_url, self.url)
                self.assertEqual((self.output_dir / result["local_path"]).read_bytes(), self.png)
                default_opener.assert_not_called()

    def test_resolve_arguments_reach_downloader_and_are_saved_as_source_metadata(self) -> None:
        source = snapshot(users=[user(1)], image_responses=[response(301, 1, self.url)])
        source_file = self.output_dir / "snapshot.json"
        source_file.write_text(json.dumps(source), encoding="utf-8")
        destination = self.output_dir / "prepared"
        resolutions = {"images.fixture.test": "192.0.2.44", "second.fixture.test": "2001:db8::44"}
        opener = MagicMock(side_effect=self.open_image)
        with (
            patch("scripts.image_transport.create_resolved_opener", return_value=opener) as factory,
            patch("scripts.prepare_user_research_data.fetch_source") as fetcher,
            patch("scripts.prepare_trend_data.urlopen") as default_opener,
            redirect_stdout(io.StringIO()),
        ):
            exit_code = main([
                "--input-snapshot", str(source_file), "--output", str(destination),
                "--resolve", "images.fixture.test=192.0.2.44",
                "--resolve", "second.fixture.test=2001:db8::44", "--retries", "0",
            ])

        self.assertEqual(exit_code, 0)
        factory.assert_called_once_with(resolutions)
        opener.assert_called_once()
        fetcher.assert_not_called()
        default_opener.assert_not_called()
        for filename in ("users.json", "images.json", "export_report.json"):
            document = json.loads((destination / filename).read_text(encoding="utf-8"))
            self.assertEqual(document["source"]["download_dns_overrides"], resolutions)
            self.assertEqual(document["counts"]["downloaded"], 1)
        images = json.loads((destination / "images.json").read_text(encoding="utf-8"))["images"]
        self.assertEqual(images[0]["url"], self.url)
        self.assertEqual((destination / images[0]["local_path"]).read_bytes(), self.png)


if __name__ == "__main__":
    unittest.main()
