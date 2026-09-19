from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.verify_v19_offline_artifacts import _audit_annotation_templates, audit_fixed_queries
from src.utils.hash import sha256_file, sha256_obj
from src.utils.io import write_json, write_jsonl


class VerifyV19OfflineArtifactsTests(unittest.TestCase):
    def _rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for pair_index in range(3):
            pair_id = f"pair_{pair_index}"
            for claim_type, entity in (("true", "Alice"), ("counterfactual", "Bob")):
                rows.append({
                    "query_id": f"q_{pair_index}_{claim_type}",
                    "pair_id": pair_id,
                    "source_key": "source_1",
                    "group": "KB_Member",
                    "claim_type": claim_type,
                    "query": f"Is {entity} the entity in claim {pair_index}?",
                    "original_entity": "Alice",
                    "counterfactual_entity": "Bob",
                    "accepted": True,
                    "fixed_budget_pairs_per_source": 3,
                    "logical_victim_calls_per_source": 6,
                })
        return rows

    def test_accepts_complete_three_pair_budget(self) -> None:
        report = audit_fixed_queries(
            "demo",
            self._rows(),
            {"KB_Member": {"source_1"}, "True_Non_Member": set(), "Reserve": set()},
        )
        self.assertEqual(report["query_count"], 6)
        self.assertEqual(report["pair_count"], 3)
        self.assertEqual(report["source_count"], 1)

    def test_rejects_pair_that_differs_outside_entity_slot(self) -> None:
        rows = self._rows()
        rows[1]["query"] = "Is Bob a different claim?"
        with self.assertRaisesRegex(RuntimeError, "outside the entity slot"):
            audit_fixed_queries(
                "demo",
                rows,
                {"KB_Member": {"source_1"}, "True_Non_Member": set(), "Reserve": set()},
            )

    def test_accepts_counterfactual_entity_already_present_elsewhere(self) -> None:
        rows = self._rows()
        rows[0]["query"] = "Is Alice the entity while Bob remains elsewhere?"
        rows[1]["query"] = "Is Bob the entity while Bob remains elsewhere?"
        report = audit_fixed_queries(
            "demo",
            rows,
            {"KB_Member": {"source_1"}, "True_Non_Member": set(), "Reserve": set()},
        )
        self.assertEqual(report["pair_count"], 3)

    def _write_annotation_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        audit_dir = root / "audits" / "claim_pair_audit"
        rows_a: list[dict[str, object]] = []
        for index in range(200):
            rows_a.append({
                "audit_id": f"pair_{index:03d}",
                "audit_order": index + 1,
                "annotator_role": "A",
                "dataset": "demo",
                "source_key": f"source_{index:03d}",
                "entity_type": "PERSON",
                "original_entity": "Alice",
                "counterfactual_entity": "Bob",
                "true_claim": f"Alice appears in claim {index}.",
                "counterfactual_claim": f"Bob appears in claim {index}.",
                "human_pair_valid": "",
                "human_failure_reason": "",
                "audit_notes": "",
            })
        rows_b = []
        for order, row in enumerate(reversed(rows_a), 1):
            copied = dict(row)
            copied["audit_order"] = order
            copied["annotator_role"] = "B"
            rows_b.append(copied)

        path_a = audit_dir / "demo_claim_pair_audit_annotator_a.jsonl"
        path_b = audit_dir / "demo_claim_pair_audit_annotator_b.jsonl"
        manifest_path = audit_dir / "demo_claim_pair_audit_manifest.json"
        write_jsonl(rows_a, path_a)
        write_jsonl(rows_b, path_b)
        write_json({
            "annotation_labels": ["pass", "fail"],
            "annotator_a_hash": sha256_file(path_a),
            "annotator_b_hash": sha256_file(path_b),
            "sample_whitelist_hash": sha256_obj(sorted(row["audit_id"] for row in rows_a)),
        }, manifest_path)
        return path_a, path_b, manifest_path

    def test_accepts_human_labels_when_blank_template_hash_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path_a, _, _ = self._write_annotation_fixture(root)
            rows_a = [json.loads(line) for line in path_a.read_text(encoding="utf-8").splitlines()]
            rows_a[0]["human_pair_valid"] = "pass"
            write_jsonl(rows_a, path_a)

            report = _audit_annotation_templates("demo", root)

            self.assertEqual(report["filled_labels"], {"A": 1, "B": 0})
            self.assertEqual(report["annotation_status"], "annotations_present")
            self.assertTrue(report["template_hashes_verified"])

    def test_rejects_non_annotation_content_drift_after_manifest_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path_a, path_b, _ = self._write_annotation_fixture(root)
            for path in (path_a, path_b):
                rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
                target = next(row for row in rows if row["audit_id"] == "pair_000")
                target["true_claim"] = "Tampered claim."
                write_jsonl(rows, path)

            with self.assertRaisesRegex(RuntimeError, "template hash drift"):
                _audit_annotation_templates("demo", root)


if __name__ == "__main__":
    unittest.main()
