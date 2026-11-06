import os
from pathlib import Path
import smtplib
import tempfile
import unittest
from unittest.mock import patch

import requests

import pabrai_monitor as monitor


OLD = b"StockTicker,SecurityName,Shares,MarketValue,Price,NetAssets\nABC,Example,10,100,10,1000\n"
NEW = b"StockTicker,SecurityName,Shares,MarketValue,Price,NetAssets\nABC,Example,20,200,10,1000\n"


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        old_cwd = os.getcwd()
        os.chdir(self.directory.name)
        self.addCleanup(os.chdir, old_cwd)
        Path(monitor.PREVIOUS_FILE).write_bytes(OLD)
        for name, value in [("GMAIL_USER", "sender@example.com"),
                            ("GMAIL_APP_PASSWORD", "test-password"),
                            ("RECIPIENT_EMAIL", "recipient@example.com")]:
            patcher = patch.object(monitor, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        response = requests.Response()
        response.status_code = 200
        response._content = NEW
        response.url = monitor.CSV_URL
        self.response = response
        request = patch.object(monitor.requests, "get", return_value=response)
        self.request = request.start()
        self.addCleanup(request.stop)
        smtp = patch.object(monitor.smtplib, "SMTP_SSL")
        self.smtp = smtp.start()
        self.addCleanup(smtp.stop)
        self.server = self.smtp.return_value.__enter__.return_value
        self.server.send_message.return_value = {}

    def test_smtp_failure_preserves_baseline_and_surfaces_error(self):
        # Swallowing SMTP errors must not consume the changed holdings.
        failure = smtplib.SMTPException("delivery rejected")
        self.smtp.side_effect = failure
        with self.assertRaises(smtplib.SMTPException):
            monitor.main()
        self.assertEqual(Path(monitor.PREVIOUS_FILE).read_bytes(), OLD)

    def test_missing_email_configuration_preserves_baseline(self):
        for name in ["GMAIL_USER", "GMAIL_APP_PASSWORD", "RECIPIENT_EMAIL"]:
            with self.subTest(name=name), patch.object(monitor, name, ""):
                with self.assertRaises(RuntimeError):
                    monitor.main()
                self.assertEqual(Path(monitor.PREVIOUS_FILE).read_bytes(), OLD)

    def test_refused_recipient_preserves_baseline(self):
        # send_message can report refused recipients without raising.
        self.server.send_message.return_value = {"recipient@example.com": (550, b"rejected")}
        with self.assertRaises(smtplib.SMTPRecipientsRefused):
            monitor.main()
        self.assertEqual(Path(monitor.PREVIOUS_FILE).read_bytes(), OLD)

    def test_successful_delivery_advances_baseline(self):
        monitor.main()
        self.assertEqual(Path(monitor.PREVIOUS_FILE).read_bytes(), NEW)
        self.assertFalse(Path(monitor.CURRENT_FILE).exists())

    def test_http_failure_surfaces_error_and_preserves_baseline(self):
        self.response.status_code = 503
        with self.assertRaises(requests.HTTPError):
            monitor.main()
        self.assertEqual(Path(monitor.PREVIOUS_FILE).read_bytes(), OLD)

    def test_download_has_a_bounded_network_timeout(self):
        monitor.download_csv(monitor.CSV_URL, monitor.CURRENT_FILE)
        self.assertGreater(self.request.call_args.kwargs.get("timeout", 0), 0)


if __name__ == "__main__":
    unittest.main()
