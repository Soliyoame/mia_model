from __future__ import annotations

import unittest

from src.prepare.enron_capacity_role import (
    ENRON_CAPACITY_ROLE_SHA256,
    enron_capacity_role_metadata,
    enron_capacity_role_payload,
    validate_bound_enron_pilot_report,
    validate_enron_capacity_role_metadata,
    validate_enron_capacity_role_payload,
)
from src.utils.hash import sha256_obj


class EnronCapacityRoleTests(unittest.TestCase):
    def test_frozen_role_keeps_prior_failure_and_boundary_only_effect(self) -> None:
        payload = enron_capacity_role_payload()
        self.assertEqual(payload["role"]["formal_role"], "boundary_stress_test")
        self.assertFalse(payload["role"]["primary_canonical"])
        self.assertEqual(payload["prior_applicability"]["status"], "failed")
        self.assertEqual(
            payload["role"]["capacity_pass_effect"],
            "permits_boundary_evaluation_only",
        )
        self.assertFalse(payload["execution"]["enabled"])
        self.assertEqual(payload["execution"]["long_task_owner"], "user")
        self.assertEqual(ENRON_CAPACITY_ROLE_SHA256, sha256_obj(payload))

    def test_old_30000_pool_is_rejected_by_conservative_capacity(self) -> None:
        payload = enron_capacity_role_payload()
        payload["capacity_study"]["candidate_pool_target_sources"] = 30000
        with self.assertRaisesRegex(RuntimeError, "capacity study decision drift"):
            validate_enron_capacity_role_payload(payload)

    def test_prior_failure_cannot_be_rewritten(self) -> None:
        payload = enron_capacity_role_payload()
        payload["prior_applicability"]["status"] = "passed"
        with self.assertRaisesRegex(RuntimeError, "applicability conclusion drift"):
            validate_enron_capacity_role_payload(payload)

    def test_metadata_validation_fails_closed(self) -> None:
        metadata = enron_capacity_role_metadata()
        validate_enron_capacity_role_metadata(metadata)
        metadata["primary_canonical"] = True
        with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
            validate_enron_capacity_role_metadata(metadata)

    def test_bound_pilot_report_is_still_failed_and_zero_call(self) -> None:
        report = validate_bound_enron_pilot_report()
        self.assertEqual(report["source_gate"]["eligible_sources"], 49)
        self.assertFalse(report["source_gate"]["gate_passed"])
        self.assertEqual(report["api_calls_performed"], 0)
        self.assertEqual(report["retriever_runs"], 0)


if __name__ == "__main__":
    unittest.main()
