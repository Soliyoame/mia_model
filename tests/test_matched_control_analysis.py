from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.evaluation.matched_control import build_matched_control_analysis
from src.utils.hash import sha256_obj
from src.utils.io import read_jsonl, write_jsonl


def _query(
    query_id: str,
    *,
    pair_id: str,
    audit_id: str,
    source_key: str,
    group: str,
    claim_type: str,
) -> dict:
    return {
        "query_id": query_id,
        "pair_id": pair_id,
        "fact_id": f"fact-{pair_id}",
        "audit_id": audit_id,
        "doc_id": audit_id,
        "source_id": source_key,
        "source_key": source_key,
        "dataset": "toy",
        "group": group,
        "claim_type": claim_type,
        "query_type": "default",
        "expected_entity": "Alice" if source_key == "member" else "Carol",
        "counterfactual_entity": "Bob" if source_key == "member" else "Dave",
        "accepted": True,
    }


def _response(query: dict, text: str) -> dict:
    return {
        **query,
        "request_id": f"req-{query['query_id']}",
        "mode": "llm_only",
        "response": text,
        "error": None,
    }


class MatchedControlAnalysisTests(unittest.TestCase):
    def _inputs(self, root: Path) -> tuple[Path, Path, Path]:
        queries = [
            _query(
                "m-plus",
                pair_id="m-pair",
                audit_id="m-audit",
                source_key="member",
                group="KB_Member",
                claim_type="true",
            ),
            _query(
                "m-minus",
                pair_id="m-pair",
                audit_id="m-audit",
                source_key="member",
                group="KB_Member",
                claim_type="counterfactual",
            ),
            _query(
                "n-plus",
                pair_id="n-pair",
                audit_id="n-audit",
                source_key="nonmember",
                group="True_Non_Member",
                claim_type="true",
            ),
            _query(
                "n-minus",
                pair_id="n-pair",
                audit_id="n-audit",
                source_key="nonmember",
                group="True_Non_Member",
                claim_type="counterfactual",
            ),
        ]
        responses = [
            _response(queries[0], "Consistent."),
            _response(queries[1], "Inconsistent. The correct value is Alice."),
            _response(queries[2], "I don't know."),
            _response(queries[3], "I don't know."),
        ]
        main = [
            {"source_key": "member", "group": "KB_Member", "pcv_score": 2.0},
            {"source_key": "nonmember", "group": "True_Non_Member", "pcv_score": 0.0},
        ]
        query_path = root / "queries.jsonl"
        response_path = root / "responses.jsonl"
        main_path = root / "main.jsonl"
        write_jsonl(queries, query_path)
        write_jsonl(responses, response_path)
        write_jsonl(main, main_path)
        return query_path, response_path, main_path

    def test_aggregates_llm_only_on_the_main_source_whitelist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query_path, response_path, main_path = self._inputs(root)
            result = build_matched_control_analysis(
                dataset="toy",
                queries_path=query_path,
                llm_responses_path=response_path,
                main_source_scores_path=main_path,
                output_dir=root / "release",
                n_bootstrap=20,
                seed=42,
            )
            report = result["report"]
            self.assertEqual(report["planned_queries"], 4)
            self.assertEqual(report["complete_pairs"], 2)
            self.assertEqual(report["source_count"], 2)
            self.assertEqual(
                report["source_whitelist_hash"],
                sha256_obj(["member", "nonmember"]),
            )
            merged = {
                row["source_key"]: row
                for row in read_jsonl(result["paths"]["canonical_source_scores"])
            }
            self.assertEqual(merged["member"]["pcv_score"], 2.0)
            self.assertGreater(merged["member"]["pvs_llm"], merged["nonmember"]["pvs_llm"])
            self.assertEqual(
                merged["member"]["cg_cvg"],
                merged["member"]["pcv_score"] - merged["member"]["pvs_llm"],
            )

    def test_rejects_missing_llm_only_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query_path, response_path, main_path = self._inputs(root)
            responses = list(read_jsonl(response_path))[:-1]
            write_jsonl(responses, response_path)
            with self.assertRaisesRegex(RuntimeError, "response/query ids differ"):
                build_matched_control_analysis(
                    dataset="toy",
                    queries_path=query_path,
                    llm_responses_path=response_path,
                    main_source_scores_path=main_path,
                    output_dir=root / "release",
                    n_bootstrap=0,
                )

    def test_rejects_response_metadata_from_another_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            query_path, response_path, main_path = self._inputs(root)
            responses = list(read_jsonl(response_path))
            responses[0]["group"] = "True_Non_Member"
            write_jsonl(responses, response_path)
            with self.assertRaisesRegex(RuntimeError, "metadata differ"):
                build_matched_control_analysis(
                    dataset="toy",
                    queries_path=query_path,
                    llm_responses_path=response_path,
                    main_source_scores_path=main_path,
                    output_dir=root / "release",
                    n_bootstrap=0,
                )


if __name__ == "__main__":
    unittest.main()
