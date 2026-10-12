"""主线来源评分：复用固定判分，正确 +1、拒答 -1、其他有效回答 0。"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.shared_g.artifacts import read_json, read_rows as read_jsonl, write_once
from src.utils.hash import sha256_file

ROOT = Path(__file__).resolve().parents[2]
SIGNED_ARMS = ('correct_anchor', 'remote_only')
SIGNED_GROUPS = ('KB_Member', 'True_Non_Member')
SIGNED_FORMAL_REFUSAL_REASONS = frozenset(('abstention_without_answer', 'explicit_abstention_outside_answer'))
SCORING_VERSION = 'signed_correct_refused_v1'
SIGNED_FORMULA = '(C - U) + lambda * (R - V)'


def unique_records(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    result = {}
    for row in rows:
        identity = row.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise ValueError(f'duplicate_or_missing_identity:{key}')
        result[identity] = row
    return result


def signed_outcome(judgment: dict[str, Any]) -> int:
    """只复用已保存的判定；拒答与其他未答对分开，故障不计零分。"""
    correct = judgment.get('label') == 'correct'
    if (judgment.get('status') != 'resolved'
            or judgment.get('label') not in ('correct', 'not_correct')
            or judgment.get('score') != int(correct)
            or (correct and judgment.get('reason') == 'refused')):
        raise ValueError('invalid_or_inconsistent_saved_judgment')
    return 1 if correct else (-1 if judgment.get('reason') == 'refused' else 0)


def validate_signed_lambdas(values: list[float]) -> list[float]:
    if not values or any(isinstance(v, bool) or not isinstance(v, (int, float))
                         or not math.isfinite(v) or v < 0 for v in values):
        raise ValueError('lambda_must_be_finite_and_nonnegative')
    if len(set(values)) != len(values):
        raise ValueError('duplicate_lambda')
    return sorted(values)


def signed_value(correct: int, refused: int, followup_correct: int,
                 followup_refused: int, weight: float) -> float:
    """直接累加两阶段证据；权重允许为 0、小于 1 或大于 1。"""
    validate_signed_lambdas([weight])
    counts = (correct, refused, followup_correct, followup_refused)
    if any(type(value) is not int or value < 0 for value in counts):
        raise ValueError('nonnegative_integer_counts_required')
    value = (correct - refused) + weight * (followup_correct - followup_refused)
    if not math.isfinite(value):
        raise ValueError('nonfinite_source_score')
    return float(value)


def signed_score_bounds(row: dict[str, Any], arm: str, weight: float, method: str) -> tuple[float, float]:
    validate_signed_lambdas([weight])
    followup = row['arms'][arm]
    base = row['initial_correct'] + weight * followup['correct']
    if method == 'old':
        return float(base), float(base + weight * followup['missing'])
    if method != 'new':
        raise ValueError('unknown_score_method')
    base = signed_value(row['initial_correct'], row['initial_refused'],
                        followup['correct'], followup['refused'], weight)
    return float(base - weight * followup['missing']), float(base + weight * followup['missing'])


def signed_formal_outcome(judgment: dict[str, Any], automatic_reason: str) -> int:
    """保持正式正确性判定，仅从原匹配器理由提取拒答；争议与否定冲突不等于拒答。"""
    if (judgment.get('label') not in ('correct', 'incorrect', 'ambiguous')
            or judgment.get('review_status') == 'uncertain' and judgment['label'] != 'ambiguous'):
        raise ValueError('invalid_formal_judgment')
    if judgment['label'] == 'correct':
        return 1
    if judgment.get('review_status') != 'uncertain' and automatic_reason in SIGNED_FORMAL_REFUSAL_REASONS:
        return -1
    return 0


def signed_formal_features(
    sources: list[dict[str, Any]], plans: list[dict[str, Any]],
    initial: list[dict[str, Any]], followups: list[dict[str, Any]],
    adjudications: dict[str, dict[str, Any]], saved_scores: list[dict[str, Any]],
    matcher: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    from src.shared_g.scoring import REPAIRED_MATCHER, answer_judgment, repaired_judgment, source_scores

    if matcher != REPAIRED_MATCHER:
        raise ValueError('signed_formal_requires_original_repaired_matcher')
    sby, pby, rby = (unique_records(rows, key) for rows, key in (
        (sources, 'source_key'), (plans, 'query_id'), (initial + followups, 'query_id')))
    coordinates: dict[str, dict[tuple[str, int], dict[str, Any]]] = defaultdict(dict)
    owners: dict[str, str] = {}
    for source in sources:
        if source['group'] not in SIGNED_GROUPS:
            raise ValueError('unsupported_membership_group')
        for field in ('source_hash', 'normalized_text_hash'):
            value = source.get(field)
            if not isinstance(value, str) or not value or owners.get(value, source['source_key']) != source['source_key']:
                raise ValueError('missing_or_duplicate_source_identity')
            owners[value] = source['source_key']
    for query in plans:
        source = sby.get(query['source_key'])
        if source is None or query['dataset'] != source['dataset']:
            raise ValueError('formal_source_plan_identity_drift')
        position = (query['arm'], query['slot_index'])
        if position in coordinates[query['source_key']]:
            raise ValueError('duplicate_source_slots')
        coordinates[query['source_key']][position] = query
    expected = {(arm, slot) for arm in ('initial', *SIGNED_ARMS) for slot in range(3)}
    if any(set(coordinates[key]) != expected for key in sby):
        raise ValueError('incomplete_source_slots')
    for response in rby.values():
        query = pby.get(response['query_id'])
        if query is None or any(response.get(field) != query[field] for field in ('source_key', 'arm', 'slot_index')):
            raise ValueError('formal_response_query_identity_drift')
    # 原评分函数同时检查门控缺失、多余响应与无效回答；不改其正确性语义。
    original = source_scores(sources, plans, initial, followups, 1.0, matcher=matcher, adjudications=adjudications)
    if unique_records(original, 'source_key') != unique_records(saved_scores, 'source_key'):
        raise ValueError('recomputed_original_scores_differ_from_saved_scores')
    outcomes, counts = {}, Counter()
    for query_id, response in rby.items():
        query = pby[query_id]
        judgment = answer_judgment(response, query, matcher=matcher, adjudications=adjudications)
        automatic = repaired_judgment(response['response'], query['answer'], response['status'],
                                      query.get('answer_aliases'), question=query.get('question', ''))
        outcome = signed_formal_outcome(judgment, str(automatic['reason']))
        outcomes[query_id] = outcome
        counts[(query['arm'], sby[query['source_key']]['group'], judgment['label'],
                str(automatic['reason']), judgment['label_source'], judgment['review_status'], outcome)] += 1
    features = []
    for key, source in sorted(sby.items()):
        initial_ids = [coordinates[key]['initial', slot]['query_id'] for slot in range(3)]
        values = [outcomes[query_id] for query_id in initial_ids]
        row = {field: source[field] for field in ('source_key', 'dataset', 'group', 'source_hash', 'normalized_text_hash')}
        row.update(initial_correct=values.count(1), initial_refused=values.count(-1), initial_wrong=values.count(0),
                   initial_outcomes=values, initial_query_ids=initial_ids, arms={}, complete=True)
        for arm in SIGNED_ARMS:
            ids = [coordinates[key][arm, slot]['query_id'] for slot in range(3) if values[slot] == 1]
            observed = [outcomes[query_id] for query_id in ids]
            row['arms'][arm] = {'correct': observed.count(1), 'refused': observed.count(-1), 'wrong': observed.count(0),
                                'missing': 0, 'missing_queries': [], 'gated_query_ids': ids, 'historical_outside_gate': []}
        features.append(row)
    fields = ('arm', 'group', 'label', 'automatic_reason', 'label_source', 'review_status', 'signed_outcome')
    return features, [dict(zip(fields, key), count=count) for key, count in counts.items()]


def load_signed_formal(root: Path, dataset: str, *, project_root: Path | None = None
                       ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    """只读已完成正式 cell；此入口不允许开发校准或发起模型请求。"""
    from src.shared_g.artifacts import request_records
    from src.utils.hash import sha256_file, sha256_obj, sha256_text

    root = root.resolve()
    project = (project_root or ROOT).resolve()
    run = read_json(root / 'run_config.json')
    if run.get('version') == 'binary_target_rules_nli_v3':
        return load_signed_nli_formal(root, dataset, project_root=project)
    config = run['config']
    prior = read_json(root / dataset / 'report.json')
    protocol = config['query_protocol']
    if (run['run_role'] != 'formal' or prior['run_role'] != 'formal' or prior['dataset'] != dataset
            or prior['status'] not in ('formal_cell_complete', 'scoring_corrected_cell_complete')
            or prior['statistical_unit'] != 'source_document'
            or protocol['local_slots'] != 3 or set(protocol['arms']) != set(SIGNED_ARMS)
            or protocol['followup_gate'] != 'initial_response_correct_per_slot'
            or config['scoring']['lambda'] != 1.0):
        raise ValueError('unsupported_or_incomplete_formal_cell')
    names = ['run_config.json', 'source_manifest.jsonl', 'index_manifest.jsonl', 'query_plan.jsonl',
             'response_adjudications.json', f'{dataset}/scores.jsonl', f'{dataset}/report.json',
             *(f'{dataset}/{name}' for name in prior['artifact_hashes'])]
    hashes = {str(root / name): sha256_file(root / name) for name in names}
    bound = {**run['artifacts'], **run['frozen_artifacts'],
             **{f'{dataset}/{name}': digest for name, digest in prior['artifact_hashes'].items()}}
    for name in names:
        if name not in ('run_config.json', f'{dataset}/scores.jsonl', f'{dataset}/report.json'):
            if bound.get(name) != hashes[str(root / name)]:
                raise ValueError(f'formal_artifact_identity_drift:{name}')
    if hashes[str(root / 'run_config.json')] != prior['run_config_sha256']:
        raise ValueError('formal_report_run_config_drift')
    for name in ('src/shared_g/scoring.py', 'src/shared_g/artifacts.py', 'src/utils/hash.py'):
        path = project / name
        hashes[str(path)] = sha256_file(path)
        if hashes[str(path)] != run['code_hashes'][name]:
            raise ValueError(f'formal_label_code_drift:{name}')
    sources = [row for row in read_jsonl(root / 'source_manifest.jsonl') if row['dataset'] == dataset]
    if dict(Counter(row['group'] for row in sources)) != config['source_selection']['counts'][dataset]:
        raise ValueError('formal_source_counts_differ_from_config')
    sby = unique_records(sources, 'source_key')
    index_sources = [row for row in read_jsonl(root / 'index_manifest.jsonl') if row['dataset'] == dataset]
    iby = unique_records(index_sources, 'source_key')
    if (set(iby) != {key for key, row in sby.items() if row['group'] == 'KB_Member'}
            or any(row['source_hash'] != sby[key]['source_hash'] for key, row in iby.items())):
        raise ValueError('formal_index_is_not_designated_members_only')
    plans = [row for row in read_jsonl(root / 'query_plan.jsonl') if row['dataset'] == dataset]
    initial, followups = (request_records(root / dataset / f'{phase}_responses.jsonl') for phase in ('initial', 'followup'))
    responses = unique_records(initial + followups, 'query_id')
    for response in responses.values():
        if (response['status'] != 'completed'
                or response.get('response_sha256') != sha256_text(response.get('response', ''))
                or response.get('record_sha256') != sha256_obj({k: v for k, v in response.items() if k != 'record_sha256'})
                or response['profile_identity'] != run['model_profiles']['victim']
                or response['provider_model_id'] != config['runtime']['concrete_model']
                or response['retrieval_sha256'] != prior['artifact_hashes']['retrieval.jsonl']):
            raise ValueError('formal_response_or_model_identity_drift')
    packet = read_json(root / 'response_adjudications.json')
    if (config['answer_policy'].get('response_adjudications') != 'response_adjudications.json'
            or packet['reviewer_type'] != 'assistant_post_response'
            or packet['independent_human_annotation'] is not False or packet['scope'] != 'reviewed_responses_only'):
        raise ValueError('unsupported_formal_adjudication_provenance')
    adjudications = unique_records([row for row in packet['decisions'] if row['source_key'] in sby], 'query_id')
    if any(key not in responses or row['source_hash'] != sby[row['source_key']]['source_hash']
           for key, row in adjudications.items()):
        raise ValueError('formal_adjudication_source_drift')
    features, label_counts = signed_formal_features(
        sources, plans, initial, followups, adjudications, read_jsonl(root / dataset / 'scores.jsonl'), config['answer_policy']['matcher'])
    metadata = {
        'input_directory': str(root), 'dataset': dataset, 'original_seed': config['seed'],
        'original_run_role': 'formal', 'original_status': prior['status'], 'original_code_commit': run['code_commit'],
        'original_config_sha256': run['config_sha256'], 'original_runtime': config['runtime'],
        'correctness_matcher': config['answer_policy']['matcher'], 'refusal_reasons': sorted(SIGNED_FORMAL_REFUSAL_REASONS),
        'uncertain_review_outcome': 0, 'correctness_and_gate_preserved': True,
        'original_scores_reproduced_exactly': True, 'source_counts': dict(Counter(row['group'] for row in sources)),
        'initial_responses': len(initial), 'followup_responses': len(followups), 'label_counts': label_counts,
        'provider_model_ids': dict(Counter(row['provider_model_id'] for row in responses.values())),
        'system_fingerprints': dict(Counter(str(row.get('system_fingerprint')) for row in responses.values())),
        'original_metrics': prior['metrics'], 'original_scoring_correction': prior.get('scoring_correction'),
    }
    return features, metadata, hashes


def source_scores(features: list[dict[str, Any]], weight: float) -> list[dict[str, Any]]:
    """每篇来源一行；未触发的追问不计分，缺失的应答不能补零。"""
    validate_signed_lambdas([weight])
    by_source = unique_records(features, 'source_key')
    if not by_source:
        raise ValueError('empty_source_cohort')
    scores = []
    for key, feature in sorted(by_source.items()):
        if feature.get('complete') is not True or feature.get('group') not in SIGNED_GROUPS:
            raise ValueError('incomplete_or_invalid_source')
        outcomes = feature['initial_outcomes']
        if len(outcomes) != 3 or any(type(value) is not int or value not in (-1, 0, 1) for value in outcomes):
            raise ValueError('three_valid_initial_outcomes_required')
        counts = (feature['initial_correct'], feature['initial_refused'], feature['initial_wrong'])
        if any(type(value) is not int for value in counts) or counts != tuple(outcomes.count(v) for v in (1, -1, 0)):
            raise ValueError('initial_count_mismatch')
        if set(feature['arms']) != set(SIGNED_ARMS):
            raise ValueError('both_followup_arms_required')
        row = dict(feature)
        row.update(initial_bits=[int(value == 1) for value in outcomes],
                   local_only=feature['initial_correct'], signed_initial=sum(outcomes))
        for arm in SIGNED_ARMS:
            followup = feature['arms'][arm]
            if followup.get('missing') != 0 or followup.get('missing_queries'):
                raise ValueError('missing_followup_has_no_point_score')
            values = tuple(followup[name] for name in ('correct', 'refused', 'wrong'))
            if (any(type(value) is not int or value < 0 for value in values)
                    or sum(values) != feature['initial_correct']
                    or len(followup['gated_query_ids']) != feature['initial_correct']
                    or len(set(followup['gated_query_ids'])) != len(followup['gated_query_ids'])):
                raise ValueError('followup_count_or_gate_mismatch')
            row[arm] = signed_value(feature['initial_correct'], feature['initial_refused'],
                                    followup['correct'], followup['refused'], weight)
        scores.append(row)
    return scores


def load_scoring_config(path: str | Path, *, project_root: Path | None = None) -> dict[str, Any]:
    from src.utils.io import load_yaml

    project = (project_root or ROOT).resolve()
    config = load_yaml((project / path).resolve())
    scoring, evaluation = config['scoring'], config['evaluation']
    if (config.get('version') != SCORING_VERSION or scoring.get('formula') != SIGNED_FORMULA
            or scoring.get('primary') != 'S_lambda' or scoring.get('normalized') is not False
            or scoring.get('statistical_unit') != 'source_document'):
        raise ValueError('unsupported_mainline_scoring_configuration')
    validate_signed_lambdas([scoring.get('lambda')])
    cutoff = scoring.get('operational_cutoff')
    if isinstance(cutoff, bool) or not isinstance(cutoff, (int, float)) or not math.isfinite(cutoff):
        raise ValueError('finite_operational_cutoff_required')
    if not scoring.get('parameter_source') or not scoring.get('parameter_validation'):
        raise ValueError('parameter_provenance_required')
    inputs = config.get('inputs')
    if not isinstance(inputs, dict) or not inputs or set(inputs) - {'nfcorpus', 'scidocs', 'trec-covid'}:
        raise ValueError('explicit_dataset_inputs_required')
    if (type(config.get('seed')) is not int or type(evaluation.get('bootstrap_samples')) is not int
            or evaluation['bootstrap_samples'] < 1 or evaluation.get('confidence') != 0.95):
        raise ValueError('invalid_evaluation_configuration')
    targets = evaluation.get('low_fpr_targets')
    if (not isinstance(targets, list) or not targets or len(set(targets)) != len(targets)
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) or not 0 <= value <= 1 for value in targets)):
        raise ValueError('invalid_low_fpr_targets')
    output = (project / config['output_dir']).resolve()
    allowed = project / 'artifacts/v25'
    if not output.is_relative_to(allowed) or output == allowed:
        raise ValueError('independent_scoring_output_required')
    for value in inputs.values():
        if not isinstance(value, str) or not value:
            raise ValueError('explicit_dataset_inputs_required')
        source = (project / value).resolve()
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError('scoring_output_overlaps_input')
    return config


def score_metrics(config: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score
    from scipy.stats import beta
    from src.shared_g.config import ExperimentConfig
    from src.shared_g.evaluation import metrics

    result = metrics(ExperimentConfig(ROOT, Path(__file__), config), rows)
    labels = [row['group'] == 'KB_Member' for row in rows]
    for arm, value in result.items():
        fixed = value['fixed_cutoff']
        tp, fp = fixed['true_positive_count'], fixed['false_positive_count']
        positives, negatives = fixed['positive_count'], fixed['negative_count']
        fn, tn = positives - tp, negatives - fp
        total, correct = positives + negatives, tp + tn
        denominator = (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)
        fixed.update(false_negative_count=fn, true_negative_count=tn, accuracy=correct / total,
                     precision=tp / (tp + fp) if tp + fp else 0.0, recall=tp / positives,
                     f1=2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0,
                     balanced_accuracy=(tp / positives + tn / negatives) / 2,
                     mcc=(tp * tn - fp * fn) / math.sqrt(denominator) if denominator else 0.0,
                     accuracy_ci95=[0.0 if correct == 0 else float(beta.ppf(0.025, correct, total - correct + 1)),
                                    1.0 if correct == total else float(beta.ppf(0.975, correct + 1, total - correct))])
        value['average_precision'] = float(average_precision_score(labels, [row[arm] for row in rows]))
    return result


def evaluate(config_path: str | Path, dataset: str, *, project_root: Path | None = None,
             dry_run: bool = False) -> dict[str, Any]:
    """离线重算主线分数；新配置和旧响应分别绑定，绝不覆盖历史报告。"""
    project = (project_root or ROOT).resolve()
    path = (project / config_path).resolve()
    config = load_scoring_config(path, project_root=project)
    if dataset not in config['inputs']:
        raise ValueError('dataset_not_configured_for_mainline_scoring')
    output = (project / config['output_dir'] / dataset).resolve()
    source = (project / config['inputs'][dataset]).resolve()
    code_hash = sha256_file(Path(__file__))
    config_hash = sha256_file(path)
    report_path, scores_path = output / 'report.json', output / 'scores.jsonl'
    previous = read_json(report_path) if report_path.exists() else None
    if previous is not None:
        if (previous.get('scoring_config_sha256') != config_hash
                or previous.get('code_sha256') != code_hash):
            raise RuntimeError('scoring_code_or_config_drift_use_new_output')
        if not scores_path.is_file() or sha256_file(scores_path) != previous.get('scores_sha256'):
            raise RuntimeError('saved_source_scores_drift')
    elif output.exists() and any(output.iterdir()):
        raise RuntimeError('partial_scoring_output_preserved_use_new_output')
    features, metadata, hashes = load_signed_formal(source, dataset, project_root=project)
    if len(metadata['provider_model_ids']) != 1 or len(metadata['system_fingerprints']) != 1:
        raise ValueError('mixed_victim_identity_not_allowed')
    hashes.update({str(path): config_hash, str(Path(__file__).resolve()): code_hash,
                   str(ROOT / 'src/evaluation/metrics.py'): sha256_file(ROOT / 'src/evaluation/metrics.py'),
                   str(ROOT / 'src/shared_g/evaluation.py'): sha256_file(ROOT / 'src/shared_g/evaluation.py')})
    if previous is not None and previous.get('input_hashes') != hashes:
        raise RuntimeError('scoring_input_drift_use_new_output')
    rows = source_scores(features, config['scoring']['lambda'])
    counts = dict(Counter(row['group'] for row in rows))
    if set(counts) != set(SIGNED_GROUPS) or {row['dataset'] for row in rows} != {dataset}:
        raise ValueError('complete_single_dataset_with_both_groups_required')
    if any(not Path(name).is_file() or sha256_file(Path(name)) != digest for name, digest in hashes.items()):
        raise RuntimeError('scoring_input_changed_during_run')
    if previous is not None and not dry_run:
        return previous
    result = {
        'status': 'mainline_scoring_preflight_passed' if dry_run else 'mainline_scoring_complete',
        'version': SCORING_VERSION, 'dataset': dataset, 'statistical_unit': 'source_document',
        'evaluation_role': ('prospective_generator_on_existing_cohort'
                            if metadata.get('post_response_correction') is False
                            else 'posthoc_rescore_of_existing_responses'), 'formal_release_allowed': False,
        'scoring': config['scoring'], 'evaluation': config['evaluation'], 'seed': config['seed'],
        'source_count': len(rows), 'source_counts': counts,
        'score_definitions': {'local_only': 'C (unchanged correctness-only baseline)',
                              'signed_initial': 'C - U (stored lambda-zero ablation score)',
                              **{arm: SIGNED_FORMULA for arm in SIGNED_ARMS}},
        'primary_arm': 'correct_anchor', 'metadata': metadata, 'input_hashes': hashes,
        'scoring_config_sha256': config_hash, 'code_sha256': code_hash,
        'used_for_parameter_selection': False, 'macro_auc': None,
        'macro_unavailable_reason': 'single_dataset_report_no_mixed_judgment_versions',
        'query_counts': {'initial': 3 * len(rows), 'each_arm_including_initial': sum(3 + r['initial_correct'] for r in rows),
                         'both_arms_including_initial': sum(3 + 2 * r['initial_correct'] for r in rows),
                         'observed_responses': metadata['initial_responses'] + metadata['followup_responses']},
        'new_calls': {'api': 0, 'victim': 0, 'retriever': 0, 'nli': 0},
        'metrics': None,
    }
    if dry_run:
        return result
    result['metrics'] = score_metrics(config, rows)
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=project, text=True, capture_output=True, check=False)
    result['code_commit'] = revision.stdout.strip() if revision.returncode == 0 else None
    result['uncommitted_code_bound_by_sha256'] = True
    if any(sha256_file(Path(name)) != digest for name, digest in hashes.items()):
        raise RuntimeError('scoring_input_changed_during_run')
    write_once(scores_path, rows)
    result['scores_sha256'] = sha256_file(scores_path)
    write_once(report_path, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('configs/v25_signed_scoring.yaml'))
    parser.add_argument('--dataset', required=True, choices=('nfcorpus', 'scidocs', 'trec-covid'))
    parser.add_argument('--dry-run', action='store_true', help='核验来源、判分和新公式；不写产物、不计算指标')
    args = parser.parse_args()
    result = evaluate(args.config, args.dataset, dry_run=args.dry_run)
    summary = {name: result[name] for name in ('status', 'version', 'dataset', 'scoring', 'source_count', 'new_calls')}
    if result['metrics'] is not None:
        summary['auc'] = {arm: value['auc']['estimate'] for arm, value in result['metrics'].items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), flush=True)


def signed_nli_formal_features(
    sources: list[dict[str, Any]], plans: list[dict[str, Any]],
    items: dict[str, dict[str, Any]], entries: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """从正式 v3 已存标签提取三值计数，不重判回答，不使用开发加载器。"""
    from src.evaluation.answer_judgment import TARGETED_JUDGMENT_VERSION, automatic_target, paired_targets
    from src.utils.hash import sha256_obj, sha256_text

    sby, pby = unique_records(sources, 'source_key'), unique_records(plans, 'query_id')
    if not sources or set(items) != set(entries) or set(items) - set(pby):
        raise ValueError('missing_or_unexpected_saved_nli_judgment')
    owners: dict[str, str] = {}
    coordinates: dict[str, dict[tuple[str, int], dict[str, Any]]] = defaultdict(dict)
    for source in sources:
        if source['group'] not in SIGNED_GROUPS:
            raise ValueError('unsupported_membership_group')
        for field in ('source_hash', 'normalized_text_hash'):
            value = source.get(field)
            if not isinstance(value, str) or not value or owners.get(value, source['source_key']) != source['source_key']:
                raise ValueError('missing_or_duplicate_source_identity')
            owners[value] = source['source_key']
    for query in plans:
        source = sby.get(query['source_key'])
        if (source is None or query['dataset'] != source['dataset']
                or query.get('group', source['group']) != source['group']):
            raise ValueError('formal_source_plan_identity_drift')
        position = (query['arm'], query['slot_index'])
        if position in coordinates[query['source_key']]:
            raise ValueError('duplicate_source_slots')
        coordinates[query['source_key']][position] = query
    expected = {(arm, slot) for arm in ('initial', *SIGNED_ARMS) for slot in range(3)}
    if any(set(coordinates[key]) != expected for key in sby):
        raise ValueError('incomplete_source_slots')
    paired = paired_targets(plans)
    outcomes, counts = {}, Counter()
    for query_id, item in items.items():
        query, response = pby[query_id], item['response']
        source, entry = sby[query['source_key']], entries[query_id]
        judgment = entry['judgment']
        if (item['query'] != query or item.get('paired_query') != paired.get(query_id)
                or item['source_hash'] != source['source_hash']
                or any(response.get(field) != query[field] for field in ('query_id', 'source_key', 'arm', 'slot_index'))
                or response.get('status') != 'completed' or not str(response.get('response', '')).strip()
                or entry['query_id'] != query_id or entry['input_sha256'] != sha256_obj(item)
                or entry['record_sha256'] != sha256_obj({k: v for k, v in entry.items() if k != 'record_sha256'})
                or judgment.get('version') != TARGETED_JUDGMENT_VERSION):
            raise ValueError('saved_nli_input_or_version_drift')
        _, binding = automatic_target(query, paired.get(query_id))
        binding.update(query_id=query_id, source_key=query['source_key'], source_hash=source['source_hash'],
                       response_sha256=sha256_text(response['response']))
        if judgment.get('binding') != binding:
            raise ValueError('saved_nli_target_binding_drift')
        outcome = signed_outcome(judgment)
        outcomes[query_id] = outcome
        counts[(query['arm'], source['group'], judgment['label'], judgment['reason'],
                judgment['label_source'], outcome)] += 1
    features = []
    for key, source in sorted(sby.items()):
        ids = [coordinates[key]['initial', slot]['query_id'] for slot in range(3)]
        if any(query_id not in outcomes for query_id in ids):
            raise ValueError('incomplete_saved_nli_initial')
        values = [outcomes[query_id] for query_id in ids]
        row = {field: source[field] for field in ('source_key', 'dataset', 'group', 'source_hash', 'normalized_text_hash')}
        row.update(initial_correct=values.count(1), initial_refused=values.count(-1), initial_wrong=values.count(0),
                   initial_outcomes=values, initial_query_ids=ids, arms={}, complete=True)
        for arm in SIGNED_ARMS:
            gated = [coordinates[key][arm, slot]['query_id'] for slot in range(3) if values[slot] == 1]
            if any(query_id not in outcomes for query_id in gated):
                raise ValueError('incomplete_saved_nli_followup')
            observed = [outcomes[query_id] for query_id in gated]
            ignored = [coordinates[key][arm, slot]['query_id'] for slot in range(3)
                       if values[slot] != 1 and coordinates[key][arm, slot]['query_id'] in outcomes]
            row['arms'][arm] = {'correct': observed.count(1), 'refused': observed.count(-1), 'wrong': observed.count(0),
                                'missing': 0, 'missing_queries': [], 'gated_query_ids': gated, 'historical_outside_gate': ignored}
        features.append(row)
    fields = ('arm', 'group', 'label', 'automatic_reason', 'label_source', 'signed_outcome')
    return features, [dict(zip(fields, key), count=count) for key, count in counts.items()]


def load_signed_nli_formal(root: Path, dataset: str, *, project_root: Path | None = None
                           ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, str]]:
    from src.evaluation.answer_judgment import FormalJudgmentRun
    from src.evaluation.metrics import roc_auc
    from src.utils.hash import sha256_file

    project = (project_root or ROOT).resolve()
    saved = read_json(root / 'run_config.json')
    specs = [project / name for name, digest in saved['input_hashes'].items() if digest == saved['config_sha256']]
    if len(specs) != 1 or saved['run_role'] != 'formal' or saved['source_unit'] != 'source_document':
        raise ValueError('unsupported_formal_nli_identity')
    run = FormalJudgmentRun(specs[0], project)
    if run.config.output != root:
        raise ValueError('formal_nli_output_identity_drift')
    # 复用正式入口的只读身份/响应校验，不调用 score、report 或任何模型入口。
    run.validate(frozen=True)
    plans, items, entries = run._data(dataset)
    state = run._state(dataset, plans, items, entries)
    status = read_json(root / dataset / 'status.json')
    if not state['complete'] or any(status.get(key) != value for key, value in state.items()):
        raise ValueError('incomplete_or_changed_formal_nli_state')
    config = run.config.data
    protocol = config['query_protocol']
    if (protocol['local_slots'] != 3 or set(protocol['arms']) != set(SIGNED_ARMS)
            or protocol['followup_gate'] != 'initial_response_correct_per_slot' or config['scoring']['lambda'] != 1.0):
        raise ValueError('unsupported_formal_nli_scoring')
    sources = [row for row in read_jsonl(run.path('source_manifest.jsonl')) if row['dataset'] == dataset]
    if dict(Counter(row['group'] for row in sources)) != config['source_selection']['counts'][dataset]:
        raise ValueError('formal_source_counts_differ_from_config')
    sby = unique_records(sources, 'source_key')
    index = unique_records([row for row in read_jsonl(run.path('index_manifest.jsonl')) if row['dataset'] == dataset], 'source_key')
    if (set(index) != {key for key, row in sby.items() if row['group'] == 'KB_Member'}
            or any(row['source_hash'] != sby[key]['source_hash'] for key, row in index.items())):
        raise ValueError('formal_index_is_not_designated_members_only')
    features, label_counts = signed_nli_formal_features(sources, plans, items, entries)
    lookup = {(q['source_key'], q['arm'], q['slot_index']): entries.get(q['query_id']) for q in plans}
    baseline = []
    for source in sources:
        key = source['source_key']
        bits = [lookup[key, 'initial', slot]['judgment']['score'] for slot in range(3)]
        row = {field: source[field] for field in ('source_key', 'dataset', 'group')}
        row.update(initial_bits=bits, local_only=sum(bits))
        for arm in SIGNED_ARMS:
            remote = [lookup[key, arm, slot]['judgment']['score'] if bits[slot] == 1 else 0 for slot in range(3)]
            row.update({f'{arm}_bits': remote, arm: float(sum(bits) + sum(remote))})
        baseline.append(row)
    score_path, report_path = (root / dataset / name for name in ('scores.jsonl', 'report.json'))
    if score_path.exists() and unique_records(read_jsonl(score_path), 'source_key') != unique_records(baseline, 'source_key'):
        raise ValueError('recomputed_original_scores_differ_from_saved_scores')
    original_metrics = {method: {'auc': {'estimate': roc_auc(baseline, method)}} for method in ('local_only', *SIGNED_ARMS)}
    if report_path.exists():
        prior = read_json(report_path)
        if (not prior.get('complete') or prior.get('version') != saved['version']
                or prior.get('dataset') != dataset or prior.get('run_config_sha256') != sha256_file(root / 'run_config.json')):
            raise ValueError('formal_nli_report_identity_drift')
        if any(prior['metrics'][method]['auc']['estimate'] != value['auc']['estimate'] for method, value in original_metrics.items()):
            raise ValueError('original_report_auc_not_reproduced')
    hashes = {str(project / name): digest for name, digest in {**saved['input_hashes'], **saved['inherited_files']}.items()}
    files = [root / 'run_config.json', project / 'src/evaluation/answer_judgment.py',
             *(root / dataset / name for name in ('status.json', 'initial_judgments.jsonl', 'followup_judgments.jsonl', 'followup_gate.json')),
             *(root / dataset / name for name in ('initial_responses.jsonl', 'followup_responses.jsonl', 'retrieval.jsonl', 'scores.jsonl', 'report.json')
               if (root / dataset / name).exists())]
    hashes.update({str(path): sha256_file(path) for path in files})
    metadata = {
        'input_directory': str(root), 'dataset': dataset, 'original_seed': config['seed'],
        'original_run_role': 'formal', 'original_status': state['status'], 'original_code_commit': saved['code_commit'],
        'original_config_sha256': saved['config_sha256'], 'original_runtime': config['runtime'],
        'correctness_matcher': saved['version'], 'refusal_reasons': ['refused'], 'correctness_and_gate_preserved': True,
        'original_scores_reproduced_exactly': True if score_path.exists() else None,
        'baseline_origin': 'saved_v3_scores' if score_path.exists() else 'reconstructed_from_saved_v3_judgments',
        'original_complete_report_available': report_path.exists(), 'original_metrics': original_metrics,
        'source_counts': dict(Counter(row['group'] for row in sources)), 'label_counts': label_counts,
        'initial_responses': state['initial']['observed_responses'], 'followup_responses': state['followup']['observed_responses'],
        'historical_followups_outside_gate': state['followup']['historical_outside_gate'],
        'provider_model_ids': dict(Counter(item['response']['provider_model_id'] for item in items.values())),
        'system_fingerprints': dict(Counter(str(item['response'].get('system_fingerprint')) for item in items.values())),
        'nli_config': saved['nli_config'], 'independent_validation_performed': saved['independent_validation_performed'],
        'one_percent_acceptance_passed': saved['one_percent_acceptance_passed'],
        'assistant_response_adjudications_used': saved['assistant_response_adjudications_used'],
        'post_response_correction': saved['post_response_correction'],
    }
    return features, metadata, hashes


if __name__ == '__main__':
    main()
