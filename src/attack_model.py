"""基于 loss 特征的鲁棒审计器。"""
import os
import pickle

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)


class AuditorFeatureExtractor:
    """提取生成式 MIA 所需的 3 维核心特征。"""

    def __init__(self, victim_model, reference_model, neighborhood_probe, neighbor_count=5, epsilon=1e-8):
        self.victim_model = victim_model
        self.reference_model = reference_model
        self.neighborhood_probe = neighborhood_probe
        self.neighbor_count = neighbor_count
        self.epsilon = epsilon

    def extract_one(self, text):
        loss_vic = float(self.victim_model.compute_loss([text])[0])
        loss_base = float(self.reference_model.compute_loss([text])[0])

        neighbors = self.neighborhood_probe.generate(text, k=self.neighbor_count)
        neighbor_losses = self.victim_model.compute_loss(neighbors)
        mean_neighbor_loss_vic = float(np.mean(neighbor_losses)) if neighbor_losses else loss_vic

        features = np.array([
            loss_vic,
            loss_vic / max(loss_base, self.epsilon),
            loss_vic / max(mean_neighbor_loss_vic, self.epsilon),
        ], dtype=np.float32)

        return {
            "features": features,
            "loss_vic": loss_vic,
            "loss_base": loss_base,
            "mean_neighbor_loss_vic": mean_neighbor_loss_vic,
            "neighbors": neighbors,
        }

    def extract_dataset(self, records, verbose=False):
        features = []
        enriched_records = []
        total = len(records)
        for index, record in enumerate(records, start=1):
            if verbose and (index == 1 or index % 10 == 0 or index == total):
                print(f"[Stage 2] Feature extraction {index}/{total}")
            feature_record = self.extract_one(record["text"])
            features.append(feature_record["features"])
            enriched_records.append({**record, **feature_record})
        return np.asarray(features, dtype=np.float32), enriched_records


class AttackModel:
    """GBDT 元分类器，用于成员推理审计。"""

    def __init__(self):
        self.model = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.8,
            random_state=123,
        )
        self._fitted = False

    def fit(self, X, y):
        self.model.fit(X, y)
        self._fitted = True

    def predict(self, X):
        return self.model.predict(X)

    def predict_proba(self, X):
        return self.model.predict_proba(X)

    def predict_with_confidence(self, features_list):
        X = np.asarray(features_list, dtype=np.float32)
        preds = self.predict(X)
        probas = self.predict_proba(X)
        results = []
        for i, pred in enumerate(preds):
            member_prob = float(probas[i][1]) if probas.shape[1] > 1 else float(probas[i][0])
            confidence = float(abs((2.0 * member_prob) - 1.0))
            results.append({
                "prediction": int(pred),
                "member_prob": member_prob,
                "confidence": confidence,
            })
        return results

    def evaluate(self, X_test, y_test):
        y_pred = self.predict(X_test)
        y_score = self.predict_proba(X_test)[:, 1]

        auc = roc_auc_score(y_test, y_score) if len(set(y_test)) > 1 else float("nan")
        fpr_arr, tpr_arr, _ = roc_curve(y_test, y_score)
        metrics = {
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "precision": float(precision_score(y_test, y_pred, zero_division=0)),
            "recall": float(recall_score(y_test, y_pred, zero_division=0)),
            "f1": float(f1_score(y_test, y_pred, zero_division=0)),
            "roc_auc": float(auc),
            "tpr_at_1pct_fpr": float(np.interp(0.01, fpr_arr, tpr_arr)),
            "tpr_at_01pct_fpr": float(np.interp(0.001, fpr_arr, tpr_arr)),
        }
        return metrics

    def save(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self.model, f)

    def load(self, path):
        with open(path, "rb") as f:
            self.model = pickle.load(f)
        self._fitted = True
