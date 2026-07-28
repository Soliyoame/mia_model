from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from src.data.reader import MAX_CSV_FIELD_CHARS, read_local_records


class CsvReaderTests(unittest.TestCase):
    def test_large_email_field_does_not_abort_following_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "emails.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["id", "message"])
                writer.writeheader()
                writer.writerow({"id": "long", "message": "A" * 150_000})
                writer.writerow({"id": "after", "message": "The second complete email remains readable."})

            previous_limit = csv.field_size_limit()
            rows = list(read_local_records("enron", path))

            self.assertGreater(MAX_CSV_FIELD_CHARS, 150_000)
            self.assertEqual([row.source_id for row in rows], ["long", "after"])
            self.assertEqual(rows[1].text, "The second complete email remains readable.")
            self.assertEqual(csv.field_size_limit(), previous_limit)


if __name__ == "__main__":
    unittest.main()
