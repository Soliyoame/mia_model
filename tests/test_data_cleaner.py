from __future__ import annotations

import unittest

from src.data.cleaner import ENRON_CLEANER_VERSION, clean_enron_text, cleaner_version_for_dataset


class EnronCleanerTests(unittest.TestCase):
    def test_forward_separator_is_removed_but_forwarded_body_is_preserved(self) -> None:
        raw = (
            "Content-Transfer-Encoding: quoted-printable\n"
            "X-From: Alice Smith\n"
            "Subject: Payment update\n\n"
            "Please review the note below.\n"
            "---------------- Forwarded by Alice Smith on 01/02/2001 ----------------\n"
            "From: Bob Jones\n"
            "Message-ID: <example@enron.com>\n\n"
            "Delta Logistics paid $48,720 for the service."
        )

        cleaned = clean_enron_text(raw)

        self.assertIn("Please review the note below.", cleaned)
        self.assertIn("Delta Logistics paid $48,720 for the service.", cleaned)
        self.assertNotIn("Forwarded by", cleaned)
        self.assertNotIn("Content-Transfer-Encoding", cleaned)
        self.assertNotIn("X-From", cleaned)
        self.assertNotIn("Message-ID", cleaned)

    def test_original_message_separator_does_not_delete_body(self) -> None:
        cleaned = clean_enron_text(
            "-----Original Message-----\nFrom: Bob Jones\n\nThe contract was signed on March 12, 2022."
        )
        self.assertEqual(cleaned, "The contract was signed on March 12, 2022.")

    def test_enron_cleaner_version_is_dataset_specific(self) -> None:
        self.assertEqual(cleaner_version_for_dataset("enron"), ENRON_CLEANER_VERSION)
        self.assertIsNone(cleaner_version_for_dataset("edgar"))


if __name__ == "__main__":
    unittest.main()
