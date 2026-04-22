"""Pipeline for the generative robust auditor."""

import json
import os

import numpy as np
import torch
from sklearn.model_selection import train_test_split

from .attack_model import AttackModel, AuditorFeatureExtractor
from .audit_data import AuditDatasetBuilder
from .data_prep import prepare_datasets
from .llm_client import LLMClient
from .model_config import get_model_config_defaults
from .neighborhood_probe import NeighborhoodProbe
from .reference_model import ReferenceModel
from .utils import choose_reference_device, get_device
from .victim_model import LossBasedMemberScorer, VictimModel


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL_DEFAULTS = get_model_config_defaults()


class Pipeline:
    """Three-stage pipeline: sample construction, feature extraction, auditor training."""

    def __init__(
        self,
        device=None,
        retrain_victim=False,
        llm_api_key=None,
        llm_base_url=None,
        llm_model=None,
        victim_model_name=None,
        reference_model_name=None,
        neighbor_count=8,
        victim_ratio=1.0 / 3.0,
        spoof_ratio=0.5,
        max_samples_per_dataset=300,
        max_spoof_per_dataset=100,
        max_spoof_attempts=6,
        max_spoof_rounds=600,
        spoof_threshold=None,
        victim_epochs=2,
        victim_train_max_length=None,
        victim_min_train_max_length=64,
        victim_device_map=None,
        reference_device=None,
        victim_path=None,
        auditor_path=None,
        preload_dataset_name=None,
    ):
        self.device = get_device(device)
        self.retrain_victim = retrain_victim
        self.victim_model_name = victim_model_name or _MODEL_DEFAULTS["victim_model_name"]
        self.reference_model_name = reference_model_name or _MODEL_DEFAULTS["reference_model_name"]
        self.neighbor_count = neighbor_count
        self.victim_ratio = victim_ratio
        self.spoof_ratio = spoof_ratio
        self.max_samples_per_dataset = max_samples_per_dataset
        self.max_spoof_per_dataset = max_spoof_per_dataset
        self.max_spoof_attempts = max_spoof_attempts
        self.max_spoof_rounds = max_spoof_rounds
        self.spoof_threshold = spoof_threshold
        self.victim_epochs = victim_epochs
        self.victim_train_max_length = victim_train_max_length
        self.victim_min_train_max_length = victim_min_train_max_length
        self.victim_device_map = victim_device_map
        self.victim_uses_sharding = bool(victim_device_map) or (
            str(self.device).startswith("cuda")
            and torch.cuda.is_available()
            and torch.cuda.device_count() > 1
        )
        self.reference_device = reference_device or choose_reference_device(
            primary_device=self.device,
            victim_uses_sharding=self.victim_uses_sharding,
        )
        self.victim_path = victim_path or os.path.join(_PROJECT_ROOT, "models", "victim_lm")
        self.auditor_path = auditor_path or os.path.join(_PROJECT_ROOT, "models", "auditor", "auditor.pkl")
        self.auditor_meta_path = os.path.join(os.path.dirname(self.auditor_path), "metadata.json")
        self.spoof_log_path = os.path.join(os.path.dirname(self.auditor_path), "spoof_audit_log.json")
        self._llm_ready = False

        self.llm = LLMClient(
            api_key=llm_api_key,
            base_url=llm_base_url,
            model=llm_model,
        )
        dataset_names = [preload_dataset_name] if preload_dataset_name else None
        self.store = prepare_datasets(dataset_names=dataset_names, build_embeddings=False)
        self.data_builder = AuditDatasetBuilder(self.llm)
        self.neighborhood_probe = NeighborhoodProbe(self.llm, default_neighbors=neighbor_count)

        self.victim = VictimModel(
            model_name=self.victim_model_name,
            device=self.device,
            lazy_load=True,
            device_map=self.victim_device_map,
        )
        self.reference = ReferenceModel(
            model_name=self.reference_model_name,
            device=self.reference_device,
            lazy_load=True,
        )
        self.attack = AttackModel()
        self._victim_ready = False
        self.feature_extractor = AuditorFeatureExtractor(
            victim_model=self.victim,
            reference_model=self.reference,
            neighborhood_probe=self.neighborhood_probe,
            neighbor_count=neighbor_count,
        )

    @staticmethod
    def _victim_weights_exist(path):
        if not os.path.isdir(path):
            return False
        adapter_config = os.path.join(path, "adapter_config.json")
        adapter_model = os.path.join(path, "adapter_model.bin")
        full_config = os.path.join(path, "config.json")
        return (
            (os.path.isfile(adapter_config) and os.path.isfile(adapter_model))
            or os.path.isfile(full_config)
        )

    def _resolve_dataset_names(self, dataset_name=None):
        if dataset_name:
            if dataset_name not in self.store:
                raise ValueError(f"Unknown dataset: {dataset_name}")
            return [dataset_name]
        return list(self.store.keys())

    def _ensure_victim_ready(self, victim_train_texts, verbose=False):
        if self._victim_weights_exist(self.victim_path) and not self.retrain_victim:
            if verbose:
                print(f"[Victim] Loading existing weights from {self.victim_path}")
            self.victim.load(self.victim_path)
            self._victim_ready = True
            return

        if verbose:
            print(f"[Victim] Fine-tuning on {len(victim_train_texts)} samples")
        self.victim.fine_tune(
            victim_train_texts,
            output_dir=self.victim_path,
            epochs=self.victim_epochs,
            batch_size=1,
            train_max_length=self.victim_train_max_length,
            min_train_max_length=self.victim_min_train_max_length,
        )
        self._victim_ready = True
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _ensure_victim_loaded_for_infer(self, verbose=False):
        if self._victim_ready:
            return
        if not self._victim_weights_exist(self.victim_path):
            raise FileNotFoundError(
                f"Victim weights not found for inference: {self.victim_path}"
            )
        if verbose:
            print(f"[Victim] Loading trained weights for inference from {self.victim_path}")
        self.victim.load(self.victim_path)
        self._victim_ready = True

    def _save_json(self, path, payload):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _ensure_llm_ready(self, verbose=False):
        if self._llm_ready:
            return
        if verbose:
            print("[LLM] Running health check before execution")
        self.llm.ensure_healthy()
        self._llm_ready = True
        if verbose:
            print("[LLM] Health check passed")

    def _print_runtime_plan(self):
        print("[Runtime] Device plan:")
        print(f"  - victim device: {self.device}")
        print(f"  - victim sharding: {self.victim_uses_sharding}")
        print(f"  - reference device: {self.reference_device}")
        print(f"  - victim device_map request: {self.victim_device_map or 'auto-if-multi-gpu'}")

    def _load_auditor_if_needed(self):
        if getattr(self.attack, "_fitted", False):
            return
        if not os.path.isfile(self.auditor_path):
            raise FileNotFoundError(f"Auditor weights not found: {self.auditor_path}")
        self.attack.load(self.auditor_path)

    def train(self, dataset_name=None, verbose=False):
        if self.spoof_threshold is None:
            raise ValueError("Training requires an explicit spoof_threshold.")
        self._ensure_llm_ready(verbose=verbose)
        if verbose:
            self._print_runtime_plan()

        dataset_names = self._resolve_dataset_names(dataset_name)
        build_result = self.data_builder.build(
            self.store,
            dataset_names=dataset_names,
            max_samples_per_dataset=self.max_samples_per_dataset,
            victim_ratio=self.victim_ratio,
            spoof_ratio=self.spoof_ratio,
            max_spoof_per_dataset=self.max_spoof_per_dataset,
        )

        victim_train_texts = build_result["victim_train"]
        if not victim_train_texts:
            raise RuntimeError("No victim training samples were constructed.")

        if verbose:
            print("[Stage 1] Initial pool summary:")
            for ds_name, info in build_result["summary"].items():
                print(f"  - {ds_name}: {info}")

        self._ensure_victim_ready(victim_train_texts, verbose=verbose)

        membership_scorer = LossBasedMemberScorer(
            victim_model=self.victim,
            member_texts=build_result["true_members"],
            non_member_texts=build_result["true_non_members"],
            verbose=verbose,
        )
        if verbose:
            print("[Stage 1] Starting spoof generation and threshold filtering")
        balanced_result = self.data_builder.build_balanced_auditor_dataset(
            build_result=build_result,
            membership_scorer=membership_scorer,
            spoof_threshold=self.spoof_threshold,
            max_spoof_attempts=self.max_spoof_attempts,
            max_spoof_rounds=self.max_spoof_rounds,
            verbose=verbose,
        )
        self._save_json(self.spoof_log_path, balanced_result["spoof_audit_log"])

        auditor_records = balanced_result["auditor_records"]
        if len(auditor_records) < 6:
            raise RuntimeError("Not enough auditor records to train the GBDT auditor.")

        if verbose:
            print("[Stage 1] Balanced audit dataset summary:")
            for ds_name, info in balanced_result["summary"].items():
                print(f"  - {ds_name}: {info}")
            print(f"[Stage 1] Overall: {balanced_result['overall_stats']}")

        if verbose:
            print(f"[Stage 2] Extracting features for {len(auditor_records)} auditor records")
        X, enriched_records = self.feature_extractor.extract_dataset(auditor_records, verbose=verbose)
        y = np.asarray([record["label"] for record in enriched_records], dtype=np.int64)
        if len(set(y.tolist())) < 2:
            raise RuntimeError("Auditor training data contains only one class.")

        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=0.25,
            random_state=123,
            stratify=y,
        )
        if verbose:
            print(
                f"[Stage 3] Training auditor with {len(X_train)} train samples "
                f"and {len(X_test)} test samples"
            )
        self.attack.fit(X_train, y_train)
        metrics = self.attack.evaluate(X_test, y_test)
        self.attack.save(self.auditor_path)

        metadata = {
            "victim_model_name": self.victim_model_name,
            "reference_model_name": self.reference_model_name,
            "neighbor_count": self.neighbor_count,
            "dataset_names": dataset_names,
            "spoof_threshold": self.spoof_threshold,
            "pool_summary": build_result["summary"],
            "build_summary": balanced_result["summary"],
            "overall_stats": balanced_result["overall_stats"],
            "calibration": membership_scorer.calibration,
            "metrics": metrics,
            "victim_path": self.victim_path,
            "auditor_path": self.auditor_path,
            "spoof_log_path": self.spoof_log_path,
        }
        self._save_json(self.auditor_meta_path, metadata)

        return {
            "mode": "train",
            "dataset_names": dataset_names,
            "metrics": metrics,
            "pool_summary": build_result["summary"],
            "build_summary": balanced_result["summary"],
            "overall_stats": balanced_result["overall_stats"],
            "victim_train_samples": len(victim_train_texts),
            "auditor_samples": len(auditor_records),
            "spoof_threshold": self.spoof_threshold,
            "calibration": membership_scorer.calibration,
            "victim_path": self.victim_path,
            "auditor_path": self.auditor_path,
            "spoof_log_path": self.spoof_log_path,
        }

    def infer(self, text, verbose=False):
        self._ensure_llm_ready(verbose=verbose)
        self._load_auditor_if_needed()
        self._ensure_victim_loaded_for_infer(verbose=verbose)
        feature_record = self.feature_extractor.extract_one(text)
        pred = self.attack.predict_with_confidence([feature_record["features"]])[0]

        result = {
            "mode": "infer",
            "input_text": text,
            "prediction": pred["prediction"],
            "member_prob": pred["member_prob"],
            "confidence": pred["confidence"],
            "loss_vic": feature_record["loss_vic"],
            "loss_base": feature_record["loss_base"],
            "mean_neighbor_loss_vic": feature_record["mean_neighbor_loss_vic"],
            "feature_vector": feature_record["features"].tolist(),
        }
        if verbose:
            result["neighbors"] = feature_record["neighbors"]
        return result
