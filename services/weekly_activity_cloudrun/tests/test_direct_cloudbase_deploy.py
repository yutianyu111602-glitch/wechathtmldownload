import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "direct_cloudbase_deploy.py"
SPEC = importlib.util.spec_from_file_location("direct_cloudbase_deploy", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class UploadPackageTest(unittest.TestCase):
    def test_upload_bypasses_proxy_and_retries_reset(self) -> None:
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        opener = mock.MagicMock()
        opener.open.side_effect = [ConnectionResetError("reset"), response]

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            MODULE.urllib.request, "build_opener", return_value=opener
        ) as build_opener, mock.patch.object(MODULE.time, "sleep") as sleep:
            package = Path(tmp) / "context.zip"
            package.write_bytes(b"package")

            MODULE.upload_package("https://upload.example.invalid/signed", package)

        proxy_handler = build_opener.call_args.args[0]
        self.assertEqual(proxy_handler.proxies, {})
        self.assertEqual(opener.open.call_count, 2)
        sleep.assert_called_once_with(2)


if __name__ == "__main__":
    unittest.main()
