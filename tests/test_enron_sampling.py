from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.data.enron_sampling import freeze_enron_sampling_frame, mailbox_user
from src.utils.io import read_jsonl


class EnronSamplingTests(unittest.TestCase):
    def test_mailbox_user_normalizes_separators(self) -> None:
        self.assertEqual(mailbox_user("allen-p/_sent_mail/1."), "allen-p")
        self.assertEqual(mailbox_user("lay-k\\inbox\\2."), "lay-k")

    def test_hash_sample_deduplicates_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_csv = root / "emails.csv"
            with raw_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["file", "message"])
                writer.writerows(
                    [
                        ["a/inbox/1", "message one"],
                        ["b/inbox/2", "message two"],
                        ["c/inbox/3", "message three"],
                        ["a/sent/4", "message four"],
                        ["b/sent/5", "message one"],
                        ["c/sent/6", "message six"],
                    ]
                )
            kwargs = {
                "raw_csv_path": raw_csv,
                "selected_jsonl_path": root / "selected.jsonl",
                "selection_index_path": root / "selection.jsonl",
                "pass_manifest_path": root / "pass1.json",
                "final_manifest_path": root / "manifest.json",
                "selection_seed": 42,
                "expected_raw_records": 6,
                "expected_mailbox_users": 3,
                "raw_screening_target_sources": 3,
                "resume": True,
            }
            with patch(
                "src.data.enron_sampling.MIN_RAW_SCREENING_TARGET", 3
            ):
                result = freeze_enron_sampling_frame(**kwargs)
                resumed = freeze_enron_sampling_frame(**kwargs)
            rows = list(read_jsonl(root / "selected.jsonl"))
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["raw_record_count"], 6)
            self.assertEqual(result["exact_duplicate_messages"], 1)
            self.assertEqual(len(rows), 3)
            self.assertEqual(len({row["raw_message_sha256"] for row in rows}), 3)
            self.assertTrue(resumed["skipped_existing"])


if __name__ == "__main__":
    unittest.main()
