from __future__ import annotations

import unittest

from src.utils.dataset_paths import resolve_processed_path
from src.utils.io import resolve_path


class DatasetPathTests(unittest.TestCase):
    def test_processed_path_defaults_to_dataset_jsonl(self) -> None:
        config = {"paths": {"processed_dir": "datasets/processed"}, "datasets": {}}

        actual = resolve_processed_path(config, "edgar")

        self.assertEqual(actual, resolve_path("datasets/processed/edgar.jsonl"))

    def test_processed_path_accepts_dataset_specific_override(self) -> None:
        config = {
            "paths": {"processed_dir": "datasets/processed"},
            "datasets": {
                "enron": {
                    "processed_path": "artifacts/v19/processed_validator_v2/enron.jsonl"
                }
            },
        }

        actual = resolve_processed_path(config, "enron")

        self.assertEqual(
            actual,
            resolve_path("artifacts/v19/processed_validator_v2/enron.jsonl"),
        )


if __name__ == "__main__":
    unittest.main()
