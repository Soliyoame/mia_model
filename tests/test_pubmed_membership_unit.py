from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.data.preprocess import preprocess_dataset
from src.data.reader import read_local_records
from src.prepare.splitter import GROUP_FILENAMES, split_dataset_pcv_mia
from src.utils.hash import sha256_text
from src.utils.io import read_jsonl, write_json, write_jsonl
from src.utils.dataset_paths import resolve_dataset_dir


def _jats(pmcid: str, body: str) -> str:
    return (
        '<article><front><article-meta><article-id pub-id-type="pmc">'
        f"{pmcid}</article-id><abstract><p>Abstract for {pmcid}.</p></abstract>"
        f"</article-meta></front><body><sec><p>{body}</p></sec></body></article>"
    )


class PubmedMembershipUnitTests(unittest.TestCase):
    def test_pubmed_split_override_does_not_change_other_datasets(self) -> None:
        config = {
            "paths": {"splits_dir": "datasets/splits"},
            "dataset_paths": {"pubmed": {"splits_dir": "artifacts/v19/splits/pubmed"}},
        }
        self.assertTrue(str(resolve_dataset_dir(config, "splits_dir", "pubmed")).endswith("artifacts\\v19\\splits\\pubmed"))
        self.assertTrue(str(resolve_dataset_dir(config, "splits_dir", "enron")).endswith("datasets\\splits\\enron"))

    def test_reader_extracts_pmcid_and_body_from_local_jats_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "raw.jsonl"
            raw.write_text(
                json.dumps({"data": [_jats("PMC123456", "TP53 was measured in 2024 patients.")]}) + "\n",
                encoding="utf-8",
            )
            records = list(read_local_records("pubmed", raw))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].source_id, "PMC123456")
        self.assertEqual(records[0].metadata["membership_unit"], "pmcid_article")
        self.assertIn("TP53 was measured", records[0].text)
        self.assertNotIn("<article>", records[0].text)

    def test_preprocess_refuses_to_resume_old_pubmed_membership_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "raw.jsonl"
            output = root / "pubmed.jsonl"
            raw.write_text(json.dumps({"data": [_jats("PMC1", "A sufficiently long body.")]}) + "\n", encoding="utf-8")
            output.write_text("{}\n", encoding="utf-8")
            write_json({"dataset": "pubmed"}, output.with_suffix(".manifest.json"))

            with self.assertRaisesRegex(RuntimeError, "Rebuild Step 01 with --force"):
                preprocess_dataset(
                    "pubmed",
                    raw,
                    output,
                    membership_unit="pmcid_article",
                    resume=True,
                )

    def test_source_level_split_keeps_complete_pmcid_articles_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            processed = root / "pubmed.jsonl"
            rows = []
            for source_idx in range(4):
                source_id = f"PMC{1000 + source_idx}"
                for chunk_idx in range(2):
                    text = f"{source_id} chunk {chunk_idx}"
                    rows.append(
                        {
                            "doc_id": f"d-{source_idx}-{chunk_idx}",
                            "source_id": source_id,
                            "source_path": str(processed),
                            "text": text,
                            "text_hash": sha256_text(text),
                            "metadata": {},
                        }
                    )
            write_jsonl(rows, processed)
            output_dir = root / "splits"
            manifest = split_dataset_pcv_mia(
                dataset="pubmed",
                processed_path=processed,
                output_dir=output_dir,
                kb_member=1,
                true_non_member=1,
                spoof_seed=0,
                reserve=1,
                source_exclusive=True,
                target_unit="sources",
                membership_unit="pmcid_article",
                force=True,
            )

            self.assertEqual(manifest["membership_unit"], "pmcid_article")
            self.assertEqual(manifest["source_counts"]["KB_Member"], 1)
            self.assertEqual(manifest["counts"]["KB_Member"], 2)
            source_sets = {}
            for group, filename in GROUP_FILENAMES.items():
                source_sets[group] = {row["source_id"] for row in read_jsonl(output_dir / filename)}
            names = list(source_sets)
            for index, left in enumerate(names):
                for right in names[index + 1 :]:
                    self.assertFalse(source_sets[left] & source_sets[right])


if __name__ == "__main__":
    unittest.main()
