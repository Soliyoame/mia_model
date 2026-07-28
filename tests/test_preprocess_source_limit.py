from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.data.preprocess import preprocess_dataset
from src.data.reader import RawRecord
from src.utils.io import read_jsonl


class PreprocessSourceLimitTest(unittest.TestCase):
    @staticmethod
    def _records() -> list[RawRecord]:
        return [
            RawRecord(
                source_id=f"source-{index}",
                source_path=f"source-{index}.txt",
                text=f"Document {index} contains enough ordinary text for preprocessing.",
                metadata={},
            )
            for index in range(3)
        ]

    def test_source_limit_stops_before_next_membership_unit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "processed.jsonl"
            with (
                patch("src.data.preprocess.read_local_records", return_value=iter(self._records())),
                patch(
                    "src.data.preprocess.chunk_text",
                    side_effect=lambda text, **_: [f"{text} first", f"{text} second"],
                ),
            ):
                stats = preprocess_dataset(
                    "edgar",
                    Path(directory),
                    output,
                    source_limit=2,
                    require_entity=False,
                    min_entities=0,
                    membership_unit="filing",
                    force=True,
                )

            rows = list(read_jsonl(output))
            self.assertEqual({row["source_id"] for row in rows}, {"source-0", "source-1"})
            self.assertEqual(len(rows), 4)
            self.assertEqual(stats["source_limit"], 2)
            self.assertEqual(stats["unique_source_count"], 2)

    def test_chunk_limit_finishes_current_membership_unit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "processed.jsonl"
            with (
                patch("src.data.preprocess.read_local_records", return_value=iter(self._records())),
                patch(
                    "src.data.preprocess.chunk_text",
                    side_effect=lambda text, **_: [f"{text} first", f"{text} second"],
                ),
            ):
                preprocess_dataset(
                    "edgar",
                    Path(directory),
                    output,
                    limit=1,
                    require_entity=False,
                    min_entities=0,
                    membership_unit="filing",
                    force=True,
                )

            rows = list(read_jsonl(output))
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["source_id"] for row in rows}, {"source-0"})


if __name__ == "__main__":
    unittest.main()
