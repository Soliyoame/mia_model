"""Audit dataset construction for the generative MIA pipeline."""

import difflib
import random
import re


class SpoofedNonMemberGenerator:
    """Generate hard negative spoofed non-members from non-member sources."""

    _STRATEGIES = (
        (
            "template_rewrite",
            "Rewrite it into a smooth, standard, highly polished version with low stylistic variance.",
        ),
        (
            "compression_rewrite",
            "Compress it into a denser and cleaner version that keeps the key meaning and facts.",
        ),
        (
            "syntactic_reorganization",
            "Reorganize sentence structure and clause order while preserving the same meaning.",
        ),
        (
            "domain_style_rewrite",
            "Rewrite it so the wording better matches common training-set style for this domain.",
        ),
    )

    def __init__(self, llm_client):
        self.llm = llm_client

    def _domain_style_hint(self, dataset_name):
        dataset_name = (dataset_name or "").lower()
        if "pubmed" in dataset_name:
            return "Use concise biomedical abstract style with objective wording."
        if "bill" in dataset_name or "congress" in dataset_name:
            return "Use formal legislative summary style with precise policy language."
        if "enron" in dataset_name or "email" in dataset_name:
            return "Use concise professional email style with clean corporate phrasing."
        return "Use plain, fluent, domain-appropriate English."

    @staticmethod
    def _clean_candidate(text):
        text = (text or "").strip()
        if not text:
            return ""

        text = text.replace("```", " ")
        text = re.sub(r"^\s*(rewritten text|rewrite|paraphrase|output|answer)\s*:\s*", "", text, flags=re.I)
        text = re.sub(r"\s+", " ", text).strip()

        if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
            text = text[1:-1].strip()
        return text

    def _build_initial_prompt(self, source_text, dataset_name, strategy_name, strategy_instruction):
        style_hint = self._domain_style_hint(dataset_name)
        return (
            "You are creating a hard negative non-member example for a membership inference audit.\n"
            "Rewrite the source text as a natural paraphrase that stays semantically close to the original, "
            "but reads smoother, more standardized, and more training-data-like.\n\n"
            f"Domain style hint: {style_hint}\n"
            f"Rewrite strategy: {strategy_name}\n"
            f"Strategy detail: {strategy_instruction}\n\n"
            "Constraints:\n"
            "- preserve the core meaning and key facts\n"
            "- keep the same language as the source\n"
            "- avoid copying long spans verbatim\n"
            "- do not add explanations, notes, bullet points, or quotation marks\n"
            "- output only the rewritten text\n\n"
            f"Source text:\n{source_text[:1200]}"
        )

    def _build_refinement_prompt(self, source_text, dataset_name, candidate):
        style_hint = self._domain_style_hint(dataset_name)
        return (
            "You are improving a hard negative non-member example for a membership inference audit.\n"
            "The previous rewrite is not yet good enough. Produce a better rewrite that stays close in meaning "
            "to the source, but is smoother, more canonical, and more likely to resemble a memorized training sample.\n\n"
            f"Domain style hint: {style_hint}\n"
            f"Current strategy: {candidate.get('strategy', 'unknown')}\n"
            f"Current member probability: {float(candidate.get('member_prob', 0.0)):.4f}\n"
            f"Current semantic similarity: {float(candidate.get('semantic_similarity', 0.0)):.4f}\n\n"
            "Constraints:\n"
            "- preserve the source meaning and key facts\n"
            "- improve fluency and smoothness\n"
            "- keep similar length to the source unless compression is clearly beneficial\n"
            "- do not add meta commentary\n"
            "- output only the rewritten text\n\n"
            f"Original source:\n{source_text[:1000]}\n\n"
            f"Current rewrite:\n{candidate.get('text', '')[:1000]}"
        )

    def generate_candidates(
        self,
        source_text,
        dataset_name=None,
        max_calls=4,
        verbose=False,
        source_index=None,
        source_total=None,
    ):
        if self.llm is None:
            raise RuntimeError("Spoof generation requires a configured LLM client.")

        max_calls = max(1, int(max_calls))
        variants_per_call = 2
        candidates = []
        calls_used = 0

        for strategy_name, strategy_instruction in self._STRATEGIES:
            if calls_used >= max_calls:
                break

            prompt = self._build_initial_prompt(
                source_text=source_text,
                dataset_name=dataset_name,
                strategy_name=strategy_name,
                strategy_instruction=strategy_instruction,
            )
            calls_used += 1
            for variant_index in range(1, variants_per_call + 1):
                if verbose:
                    prefix = "[Stage 1] LLM spoof request"
                    if source_index is not None and source_total is not None:
                        prefix += f" source {source_index}/{source_total}"
                    print(
                        f"{prefix}: strategy={strategy_name} "
                        f"variant={variant_index}/{variants_per_call}"
                    )
                replies = self.llm.chat(
                    [{"role": "user", "content": prompt}],
                    temperature=0.55,
                    max_tokens=320,
                    n=1,
                )
                reply = replies[0] if replies else ""
                cleaned = self._clean_candidate(reply)
                if verbose:
                    status = "ok" if cleaned else "empty"
                    print(
                        f"[Stage 1] LLM spoof response: strategy={strategy_name} "
                        f"variant={variant_index}/{variants_per_call} status={status} "
                        f"chars={len(cleaned)}"
                    )
                if not cleaned:
                    continue
                candidates.append(
                    {
                        "text": cleaned,
                        "strategy": strategy_name,
                        "variant": variant_index,
                        "generation_phase": "initial",
                    }
                )
        return candidates, calls_used

    def refine_candidate(
        self,
        source_text,
        dataset_name=None,
        candidate=None,
        verbose=False,
        source_index=None,
        source_total=None,
        refine_index=None,
    ):
        if self.llm is None:
            raise RuntimeError("Spoof generation requires a configured LLM client.")
        if not candidate:
            raise ValueError("candidate must be provided for refinement.")

        prompt = self._build_refinement_prompt(
            source_text=source_text,
            dataset_name=dataset_name,
            candidate=candidate,
        )
        if verbose:
            prefix = "[Stage 1] LLM refine request"
            if source_index is not None and source_total is not None:
                prefix += f" source {source_index}/{source_total}"
            refine_label = f" refine={refine_index}" if refine_index is not None else ""
            print(
                f"{prefix}:{refine_label} strategy={candidate.get('strategy', 'unknown')} "
                f"member_prob={float(candidate.get('member_prob', 0.0)):.4f} "
                f"similarity={float(candidate.get('semantic_similarity', 0.0)):.4f}"
            )
        replies = self.llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.35,
            max_tokens=320,
            n=1,
        )
        cleaned = self._clean_candidate(replies[0] if replies else "")
        if verbose:
            status = "ok" if cleaned else "empty"
            print(
                f"[Stage 1] LLM refine response:{refine_label if refine_index is not None else ''} "
                f"status={status} chars={len(cleaned)}"
            )
        if not cleaned:
            raise RuntimeError("LLM returned an empty refined spoofed sample.")
        return {
            "text": cleaned,
            "strategy": f"refine::{candidate.get('strategy', 'unknown')}",
            "variant": 1,
            "generation_phase": "refine",
        }


class AuditDatasetBuilder:
    """Split raw texts into audit pools and build the balanced auditor dataset."""

    def __init__(self, llm_client=None, random_seed=123):
        self.random = random.Random(random_seed)
        self.spoof_generator = SpoofedNonMemberGenerator(llm_client) if llm_client else None

    def _shuffle_copy(self, texts):
        items = list(texts)
        self.random.shuffle(items)
        return items

    @staticmethod
    def _normalize_text(text):
        return re.sub(r"\s+", " ", (text or "").strip())

    def _tokenize_for_similarity(self, text):
        return re.findall(r"[a-z0-9_]+", self._normalize_text(text).lower())

    def _semantic_similarity(self, source_text, candidate_text):
        source_norm = self._normalize_text(source_text).lower()
        candidate_norm = self._normalize_text(candidate_text).lower()
        if not source_norm or not candidate_norm:
            return 0.0

        sequence_score = difflib.SequenceMatcher(None, source_norm, candidate_norm).ratio()
        source_tokens = set(self._tokenize_for_similarity(source_norm))
        candidate_tokens = set(self._tokenize_for_similarity(candidate_norm))
        if not source_tokens or not candidate_tokens:
            return float(sequence_score)

        overlap = len(source_tokens & candidate_tokens)
        precision = overlap / max(len(candidate_tokens), 1)
        recall = overlap / max(len(source_tokens), 1)
        token_f1 = 0.0 if precision + recall <= 0 else (2.0 * precision * recall) / (precision + recall)
        return float((0.45 * sequence_score) + (0.55 * token_f1))

    def _length_score(self, source_text, candidate_text):
        source_tokens = self._tokenize_for_similarity(source_text)
        candidate_tokens = self._tokenize_for_similarity(candidate_text)
        if not source_tokens or not candidate_tokens:
            return 0.0
        ratio = len(candidate_tokens) / max(len(source_tokens), 1)
        return float(max(0.0, 1.0 - min(abs(1.0 - ratio), 1.0)))

    def _sanity_check_candidate(self, source_text, candidate_text):
        source_norm = self._normalize_text(source_text)
        candidate_norm = self._normalize_text(candidate_text)
        if not candidate_norm:
            return False, "empty"
        if candidate_norm.lower() == source_norm.lower():
            return False, "identical_to_source"
        if len(candidate_norm) < 24:
            return False, "too_short"

        source_tokens = self._tokenize_for_similarity(source_norm)
        candidate_tokens = self._tokenize_for_similarity(candidate_norm)
        if len(candidate_tokens) < max(8, int(len(source_tokens) * 0.35)):
            return False, "too_short_for_source"
        if len(candidate_tokens) > max(32, int(len(source_tokens) * 2.5)):
            return False, "too_long_for_source"

        lower = candidate_norm.lower()
        meta_prefixes = (
            "here is",
            "rewritten text",
            "rewrite:",
            "paraphrase:",
            "output:",
            "answer:",
        )
        if any(lower.startswith(prefix) for prefix in meta_prefixes):
            return False, "meta_response"
        return True, "ok"

    def _dedupe_candidates(self, candidates):
        unique = []
        seen = set()
        for candidate in candidates:
            normalized = self._normalize_text(candidate.get("text", "")).lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique.append(candidate)
        return unique

    def _evaluate_candidates(self, source_text, candidates, membership_scorer, spoof_threshold):
        if not candidates:
            return []

        scored = membership_scorer.score_texts([candidate["text"] for candidate in candidates])
        min_member_prob = max(0.70, float(spoof_threshold) - 0.10)
        min_similarity = 0.58

        evaluated = []
        for candidate, score in zip(candidates, scored):
            sanity_ok, sanity_reason = self._sanity_check_candidate(source_text, candidate["text"])
            similarity = self._semantic_similarity(source_text, candidate["text"])
            length_score = self._length_score(source_text, candidate["text"])
            hard_filter_passed = (
                sanity_ok
                and similarity >= min_similarity
                and float(score["member_prob"]) >= min_member_prob
            )
            composite_score = (
                0.60 * float(score["member_prob"])
                + 0.25 * float(similarity)
                + 0.15 * float(length_score)
            )
            if not sanity_ok:
                composite_score -= 0.25

            evaluated.append(
                {
                    **candidate,
                    "member_prob": float(score["member_prob"]),
                    "victim_loss": float(score["loss"]),
                    "semantic_similarity": float(similarity),
                    "length_score": float(length_score),
                    "sanity_ok": bool(sanity_ok),
                    "sanity_reason": sanity_reason,
                    "hard_filter_passed": bool(hard_filter_passed),
                    "passed_threshold": float(score["member_prob"]) >= float(spoof_threshold),
                    "composite_score": float(composite_score),
                }
            )

        evaluated.sort(
            key=lambda item: (
                item["passed_threshold"],
                item["hard_filter_passed"],
                item["composite_score"],
                item["member_prob"],
                item["semantic_similarity"],
            ),
            reverse=True,
        )
        return evaluated

    @staticmethod
    def _select_best_candidate(evaluated_candidates):
        if not evaluated_candidates:
            return None

        for predicate in (
            lambda item: item["passed_threshold"] and item["hard_filter_passed"],
            lambda item: item["hard_filter_passed"],
            lambda item: item["sanity_ok"],
            lambda item: True,
        ):
            filtered = [item for item in evaluated_candidates if predicate(item)]
            if filtered:
                return filtered[0]
        return None

    def build(
        self,
        store,
        dataset_names=None,
        max_samples_per_dataset=60,
        victim_ratio=0.5,
        spoof_ratio=0.5,
        max_spoof_per_dataset=10,
        min_text_length=40,
    ):
        dataset_names = dataset_names or list(store.keys())
        dataset_plans = []
        victim_train = []
        true_members = []
        true_non_members = []
        spoof_source_pool = []
        summary = {}

        for dataset_name in dataset_names:
            info = store.get(dataset_name)
            if not info:
                continue

            texts = [text for text in info["texts"] if len(text.strip()) >= min_text_length]
            texts = self._shuffle_copy(texts)
            if max_samples_per_dataset:
                texts = texts[:max_samples_per_dataset]
            if len(texts) < 6:
                continue

            victim_count = max(1, int(len(texts) * victim_ratio))
            victim_slice = texts[:victim_count]
            remainder = texts[victim_count:]
            if len(victim_slice) < 1 or len(remainder) < 2:
                continue

            desired_spoof_count = min(max_spoof_per_dataset, int(len(remainder) * spoof_ratio))
            desired_spoof_count = max(1, desired_spoof_count)
            desired_spoof_count = min(desired_spoof_count, len(remainder) - 1)

            current_spoof_source_pool = remainder[:desired_spoof_count]
            current_true_non_members = remainder[desired_spoof_count:]
            if not current_spoof_source_pool or not current_true_non_members:
                midpoint = max(1, len(remainder) // 2)
                current_spoof_source_pool = remainder[:midpoint]
                current_true_non_members = remainder[midpoint:]

            if not current_spoof_source_pool or not current_true_non_members:
                continue

            victim_train.extend(victim_slice)
            true_members.extend(victim_slice)
            true_non_members.extend(current_true_non_members)
            spoof_source_pool.extend(current_spoof_source_pool)

            dataset_plans.append({
                "dataset": dataset_name,
                "victim_train": list(victim_slice),
                "true_members": list(victim_slice),
                "true_non_members": list(current_true_non_members),
                "spoof_source_pool": list(current_spoof_source_pool),
            })
            summary[dataset_name] = {
                "victim_train": len(victim_slice),
                "true_members_raw": len(victim_slice),
                "true_non_members_raw": len(current_true_non_members),
                "candidate_spoof_total": len(current_spoof_source_pool),
            }

        return {
            "dataset_plans": dataset_plans,
            "victim_train": victim_train,
            "true_members": true_members,
            "true_non_members": true_non_members,
            "spoof_source_pool": spoof_source_pool,
            "summary": summary,
        }

    def build_balanced_auditor_dataset(
        self,
        build_result,
        membership_scorer,
        spoof_threshold,
        max_spoof_attempts=4,
        max_spoof_rounds=20,
        verbose=False,
    ):
        if spoof_threshold is None:
            raise ValueError("spoof_threshold must be provided explicitly.")

        auditor_records = []
        spoof_audit_log = []
        summary = {}

        global_spoof_rounds_used = 0
        overall_final_balanced_count = 0
        overall_candidate_spoof_total = 0
        overall_qualified_spoof_total = 0
        overall_regen_source_total = 0
        overall_true_member_total = 0
        overall_true_non_member_total = 0
        overall_target_count_before_spoof = 0
        overall_hard_filter_pass_total = 0

        for plan in build_result["dataset_plans"]:
            dataset_name = plan["dataset"]
            dataset_true_members = list(plan["true_members"])
            dataset_true_non_members = list(plan["true_non_members"])
            dataset_spoof_sources = list(plan["spoof_source_pool"])

            successful_spoofs = []
            candidate_spoof_total = len(dataset_spoof_sources)
            qualified_spoof_total = 0
            regen_source_total = 0
            dataset_regen_rounds_used = 0
            target_count_before_spoof = min(len(dataset_true_members), len(dataset_true_non_members))
            hard_filter_pass_total = 0

            if verbose:
                print(
                    f"[Stage 1] Spoof generation for {dataset_name}: "
                    f"{candidate_spoof_total} candidates, target {target_count_before_spoof}"
                )

            for index, source_text in enumerate(dataset_spoof_sources, start=1):
                if len(successful_spoofs) >= target_count_before_spoof:
                    break

                if verbose and (index == 1 or index % 10 == 0 or index == candidate_spoof_total):
                    print(
                        f"[Stage 1] {dataset_name} spoof {index}/{candidate_spoof_total} "
                        f"(qualified={len(successful_spoofs)})"
                    )

                initial_call_budget = min(4, max(1, int(max_spoof_attempts)))
                if self.spoof_generator:
                    candidate_pool, attempt_count = self.spoof_generator.generate_candidates(
                        source_text,
                        dataset_name=dataset_name,
                        max_calls=initial_call_budget,
                        verbose=verbose,
                        source_index=index,
                        source_total=candidate_spoof_total,
                    )
                else:
                    candidate_pool = [
                        {
                            "text": source_text,
                            "strategy": "identity",
                            "variant": 1,
                            "generation_phase": "initial",
                        }
                    ]
                    attempt_count = 1

                candidate_pool = self._dedupe_candidates(candidate_pool)
                evaluated_candidates = self._evaluate_candidates(
                    source_text,
                    candidate_pool,
                    membership_scorer=membership_scorer,
                    spoof_threshold=spoof_threshold,
                )
                current_best = self._select_best_candidate(evaluated_candidates)
                sample_regen_count = 0

                while (
                    current_best is not None
                    and not (current_best["passed_threshold"] and current_best["hard_filter_passed"])
                    and self.spoof_generator is not None
                    and attempt_count < max_spoof_attempts
                    and global_spoof_rounds_used < max_spoof_rounds
                ):
                    sample_regen_count += 1
                    dataset_regen_rounds_used += 1
                    global_spoof_rounds_used += 1
                    refined_candidate = self.spoof_generator.refine_candidate(
                        source_text=source_text,
                        dataset_name=dataset_name,
                        candidate=current_best,
                        verbose=verbose,
                        source_index=index,
                        source_total=candidate_spoof_total,
                        refine_index=sample_regen_count,
                    )
                    attempt_count += 1
                    candidate_pool.append(refined_candidate)
                    candidate_pool = self._dedupe_candidates(candidate_pool)
                    evaluated_candidates = self._evaluate_candidates(
                        source_text,
                        candidate_pool,
                        membership_scorer=membership_scorer,
                        spoof_threshold=spoof_threshold,
                    )
                    current_best = self._select_best_candidate(evaluated_candidates)

                if sample_regen_count > 0:
                    regen_source_total += 1

                if current_best is None:
                    continue

                if current_best["hard_filter_passed"]:
                    hard_filter_pass_total += 1

                passed_threshold = bool(
                    current_best["passed_threshold"] and current_best["hard_filter_passed"]
                )
                spoof_record = {
                    "dataset": dataset_name,
                    "source_text": source_text,
                    "text": current_best["text"],
                    "label": 0,
                    "source_type": "spoofed_non_member",
                    "passed_threshold": passed_threshold,
                    "hard_filter_passed": bool(current_best["hard_filter_passed"]),
                    "member_prob": float(current_best["member_prob"]),
                    "victim_loss": float(current_best["victim_loss"]),
                    "semantic_similarity": float(current_best["semantic_similarity"]),
                    "length_score": float(current_best["length_score"]),
                    "composite_score": float(current_best["composite_score"]),
                    "strategy": current_best["strategy"],
                    "generation_phase": current_best.get("generation_phase", "initial"),
                    "candidate_pool_size": len(candidate_pool),
                    "hard_filter_candidate_count": sum(
                        1 for item in evaluated_candidates if item["hard_filter_passed"]
                    ),
                    "near_threshold_candidate_count": sum(
                        1 for item in evaluated_candidates if item["member_prob"] >= max(0.70, float(spoof_threshold) - 0.10)
                    ),
                    "attempt_count": attempt_count,
                    "regen_count": sample_regen_count,
                    "sanity_reason": current_best["sanity_reason"],
                }
                spoof_audit_log.append(spoof_record)
                if passed_threshold:
                    successful_spoofs.append(spoof_record)
                    qualified_spoof_total += 1

            final_balanced_count = min(
                len(dataset_true_members),
                len(dataset_true_non_members),
                len(successful_spoofs),
            )

            overall_final_balanced_count += final_balanced_count
            overall_candidate_spoof_total += candidate_spoof_total
            overall_qualified_spoof_total += qualified_spoof_total
            overall_regen_source_total += regen_source_total
            overall_true_member_total += len(dataset_true_members)
            overall_true_non_member_total += len(dataset_true_non_members)
            overall_target_count_before_spoof += target_count_before_spoof
            overall_hard_filter_pass_total += hard_filter_pass_total

            for text in dataset_true_members[:final_balanced_count]:
                auditor_records.append({
                    "text": text,
                    "label": 1,
                    "source_type": "true_member",
                    "dataset": dataset_name,
                })

            for text in dataset_true_non_members[:final_balanced_count]:
                auditor_records.append({
                    "text": text,
                    "label": 0,
                    "source_type": "true_non_member",
                    "dataset": dataset_name,
                })

            for record in successful_spoofs[:final_balanced_count]:
                auditor_records.append({
                    "text": record["text"],
                    "label": 0,
                    "source_type": "spoofed_non_member",
                    "dataset": dataset_name,
                    "source_text": record["source_text"],
                    "passed_threshold": record["passed_threshold"],
                    "hard_filter_passed": record["hard_filter_passed"],
                    "candidate_member_prob": record["member_prob"],
                    "candidate_loss": record["victim_loss"],
                    "candidate_similarity": record["semantic_similarity"],
                    "candidate_strategy": record["strategy"],
                    "attempt_count": record["attempt_count"],
                    "regen_count": record["regen_count"],
                })

            summary[dataset_name] = {
                "true_members_raw": len(dataset_true_members),
                "true_non_members_raw": len(dataset_true_non_members),
                "target_count_before_spoof": target_count_before_spoof,
                "candidate_spoof_total": candidate_spoof_total,
                "hard_filter_pass_total": hard_filter_pass_total,
                "qualified_spoof_total": qualified_spoof_total,
                "threshold_fail_and_regen_count": regen_source_total,
                "regen_rounds_used": dataset_regen_rounds_used,
                "final_balanced_count": final_balanced_count,
                "spoof_threshold": float(spoof_threshold),
            }
            if verbose:
                print(
                    f"[Stage 1] {dataset_name} spoof complete: "
                    f"qualified={qualified_spoof_total}, final_balanced_count={final_balanced_count}"
                )

        overall_stats = {
            "true_members_raw": overall_true_member_total,
            "true_non_members_raw": overall_true_non_member_total,
            "target_count_before_spoof_total": overall_target_count_before_spoof,
            "candidate_spoof_total": overall_candidate_spoof_total,
            "hard_filter_pass_total": overall_hard_filter_pass_total,
            "qualified_spoof_total": overall_qualified_spoof_total,
            "threshold_fail_and_regen_count": overall_regen_source_total,
            "regen_rounds_used_global": global_spoof_rounds_used,
            "final_balanced_count_per_class": overall_final_balanced_count,
            "spoof_threshold": float(spoof_threshold),
        }

        return {
            "auditor_records": auditor_records,
            "summary": summary,
            "overall_stats": overall_stats,
            "spoof_audit_log": spoof_audit_log,
        }
