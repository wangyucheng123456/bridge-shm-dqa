"""
Downstream Task: Bridge Damage Detection Models.

Key design: model is ALWAYS trained on the same quality data as test data.
This simulates real-world SHM: you only have the data you've collected,
quality issues and all. Poor data → poor model → poor detection.
"""
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.svm import OneClassSVM
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    f1_score, accuracy_score, roc_auc_score, roc_curve,
    confusion_matrix, precision_score, recall_score
)
from typing import Dict, Tuple
import warnings
warnings.filterwarnings('ignore')

from src.config import PCA_N_COMPONENTS


def make_window_labels(labels: np.ndarray, window_size: int = 500,
                       damaged_frac_threshold: float = 0.3) -> np.ndarray:
    """Aggregate per-sample labels into per-window labels.

    A window is labelled damaged when the fraction of its samples that fall
    in the damaged period exceeds ``damaged_frac_threshold``.  This helper is
    detector-independent so that the labelling threshold can be swept
    (e.g. 0.2 / 0.3 / 0.4) without touching any model.
    """
    n_windows = len(labels) // window_size
    if n_windows == 0:
        return np.array([int(np.mean(labels) > 0.5)])
    return np.array([
        int(np.mean(labels[i * window_size:(i + 1) * window_size])
            > damaged_frac_threshold)
        for i in range(n_windows)
    ])


def _extract_window_features(window: np.ndarray) -> list:
    """
    Extract statistical features from one data window.
    Uses forward-fill then zero-fill for NaN so that features are always
    computable, but missing data degrades the signal representation.
    """
    feat = []
    for col_idx in range(window.shape[1]):
        col = window[:, col_idx].astype(float)

        # Forward fill then zero-fill
        mask = np.isnan(col)
        if np.any(mask):
            # Forward fill
            for j in range(1, len(col)):
                if np.isnan(col[j]) and not np.isnan(col[j-1]):
                    col[j] = col[j-1]
            # Backward fill remainder
            for j in range(len(col)-2, -1, -1):
                if np.isnan(col[j]) and not np.isnan(col[j+1]):
                    col[j] = col[j+1]
            col = np.nan_to_num(col, nan=0.0)

        mu = np.mean(col)
        sigma = np.std(col)
        rms = np.sqrt(np.mean(col ** 2))
        pk2pk = np.max(col) - np.min(col)
        if len(col) > 1:
            mad1 = np.mean(np.abs(np.diff(col)))
        else:
            mad1 = 0.0
        feat.extend([mu, sigma, pk2pk, rms, mad1])
    return feat


class PCADamageDetector:
    """PCA-based damage detection using reconstruction error."""

    def __init__(self, n_components: int = PCA_N_COMPONENTS):
        self.n_components = n_components
        self.pca = None
        self.scaler = StandardScaler()
        self.threshold = None

    def _prepare_features(self, data: pd.DataFrame,
                          window_size: int = 500) -> np.ndarray:
        n_windows = len(data) // window_size
        if n_windows == 0:
            n_windows = 1
            window_size = len(data)

        raw = data.values.copy()
        features = []
        for i in range(n_windows):
            s = i * window_size
            e = s + window_size
            feat = _extract_window_features(raw[s:e].copy())
            features.append(feat)
        return np.nan_to_num(np.array(features), nan=0.0, posinf=0.0, neginf=0.0)

    def fit(self, healthy_data: pd.DataFrame, window_size: int = 500,
            percentile: float = 95.0):
        features = self._prepare_features(healthy_data, window_size)
        if features.shape[0] < 2:
            raise ValueError("Not enough data windows for training")
        scaled = self.scaler.fit_transform(features)
        n_comp = min(self.n_components, scaled.shape[1], scaled.shape[0])
        self.pca = PCA(n_components=n_comp)
        self.pca.fit(scaled)
        reconstructed = self.pca.inverse_transform(self.pca.transform(scaled))
        errors = np.mean((scaled - reconstructed) ** 2, axis=1)
        self.threshold = np.percentile(errors, percentile)
        return self

    def predict(self, data: pd.DataFrame,
                window_size: int = 500) -> Tuple[np.ndarray, np.ndarray]:
        features = self._prepare_features(data, window_size)
        scaled = self.scaler.transform(features)
        reconstructed = self.pca.inverse_transform(self.pca.transform(scaled))
        errors = np.mean((scaled - reconstructed) ** 2, axis=1)
        predictions = (errors > self.threshold).astype(int)
        return errors, predictions

    def get_window_labels(self, labels: np.ndarray,
                          window_size: int = 500,
                          damaged_frac_threshold: float = 0.3) -> np.ndarray:
        return make_window_labels(labels, window_size, damaged_frac_threshold)


class AutoencoderDamageDetector:
    """Autoencoder-based anomaly detection using PyTorch."""

    def __init__(self, latent_dim: int = 16, epochs: int = 50,
                 batch_size: int = 64, lr: float = 1e-3):
        self.latent_dim = latent_dim
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.scaler = StandardScaler()
        self.model = None
        self.threshold = None
        self.input_dim = None

    def _prepare_features(self, data: pd.DataFrame,
                          window_size: int = 500) -> np.ndarray:
        n_windows = len(data) // window_size
        if n_windows == 0:
            n_windows = 1
            window_size = len(data)
        raw = data.values.copy()
        features = []
        for i in range(n_windows):
            s = i * window_size
            e = s + window_size
            feat = _extract_window_features(raw[s:e].copy())
            features.append(feat)
        return np.nan_to_num(np.array(features), nan=0.0, posinf=0.0, neginf=0.0)

    def fit(self, healthy_data: pd.DataFrame, window_size: int = 500,
            percentile: float = 95.0):
        try:
            import torch
            import torch.nn as nn
            from torch.utils.data import DataLoader, TensorDataset
        except ImportError:
            self._fallback = PCADamageDetector()
            self._fallback.fit(healthy_data, window_size, percentile)
            self._use_fallback = True
            return self

        self._use_fallback = False
        features = self._prepare_features(healthy_data, window_size)
        scaled = self.scaler.fit_transform(features)
        self.input_dim = scaled.shape[1]

        class DeepAE(nn.Module):
            """3-layer deep autoencoder with BatchNorm and residual-like skip."""
            def __init__(ae_self, in_dim, lat_dim):
                super().__init__()
                h1 = max(in_dim // 2, lat_dim * 4)
                h2 = max(in_dim // 4, lat_dim * 2)

                ae_self.encoder = nn.Sequential(
                    nn.Linear(in_dim, h1),
                    nn.BatchNorm1d(h1),
                    nn.LeakyReLU(0.1),
                    nn.Dropout(0.15),
                    nn.Linear(h1, h2),
                    nn.BatchNorm1d(h2),
                    nn.LeakyReLU(0.1),
                    nn.Dropout(0.1),
                    nn.Linear(h2, lat_dim),
                )
                ae_self.decoder = nn.Sequential(
                    nn.Linear(lat_dim, h2),
                    nn.BatchNorm1d(h2),
                    nn.LeakyReLU(0.1),
                    nn.Dropout(0.1),
                    nn.Linear(h2, h1),
                    nn.BatchNorm1d(h1),
                    nn.LeakyReLU(0.1),
                    nn.Dropout(0.15),
                    nn.Linear(h1, in_dim),
                )
                ae_self.skip_proj = nn.Linear(in_dim, in_dim) if in_dim > lat_dim else None

            def forward(ae_self, x):
                z = ae_self.encoder(x)
                recon = ae_self.decoder(z)
                if ae_self.skip_proj is not None:
                    recon = recon + 0.1 * ae_self.skip_proj(x)
                return recon

        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.model = DeepAE(self.input_dim, self.latent_dim).to(device)
        optimizer = torch.optim.AdamW(self.model.parameters(), lr=self.lr,
                                       weight_decay=1e-5)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            optimizer, T_max=self.epochs, eta_min=self.lr * 0.01
        )
        criterion = nn.MSELoss()

        tensor_data = torch.FloatTensor(scaled).to(device)
        dataset = TensorDataset(tensor_data, tensor_data)
        loader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True)

        best_loss = float('inf')
        patience_counter = 0
        patience = 10

        self.model.train()
        for epoch in range(self.epochs):
            epoch_loss = 0.0
            n_batches = 0
            for batch_x, _ in loader:
                optimizer.zero_grad()
                loss = criterion(self.model(batch_x), batch_x)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()
                epoch_loss += loss.item()
                n_batches += 1
            scheduler.step()
            avg_loss = epoch_loss / max(n_batches, 1)
            if avg_loss < best_loss - 1e-6:
                best_loss = avg_loss
                patience_counter = 0
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    break

        self.model.eval()
        with torch.no_grad():
            recon = self.model(tensor_data).cpu().numpy()
        errors = np.mean((scaled - recon) ** 2, axis=1)
        self.threshold = np.percentile(errors, percentile)
        self._device = device
        return self

    def predict(self, data: pd.DataFrame,
                window_size: int = 500) -> Tuple[np.ndarray, np.ndarray]:
        if hasattr(self, '_use_fallback') and self._use_fallback:
            return self._fallback.predict(data, window_size)
        import torch
        features = self._prepare_features(data, window_size)
        scaled = self.scaler.transform(features)
        self.model.eval()
        with torch.no_grad():
            recon = self.model(torch.FloatTensor(scaled).to(self._device)).cpu().numpy()
        errors = np.mean((scaled - recon) ** 2, axis=1)
        return errors, (errors > self.threshold).astype(int)

    def get_window_labels(self, labels: np.ndarray,
                          window_size: int = 500,
                          damaged_frac_threshold: float = 0.3) -> np.ndarray:
        return make_window_labels(labels, window_size, damaged_frac_threshold)


class _WindowAnomalyDetector:
    """Shared base for window-feature anomaly detectors that expose a
    training-derived (leakage-free) decision threshold.

    Sub-classes implement :meth:`_build_model` and :meth:`_anomaly_score`.
    The decision threshold is the ``percentile`` of the anomaly-score
    distribution computed *on the healthy training set only* — no test
    labels are ever consulted, so no information leaks into the operating
    point.
    """

    def __init__(self):
        self.scaler = StandardScaler()
        self.model = None
        self.threshold = None

    def _prepare_features(self, data: pd.DataFrame,
                          window_size: int = 500) -> np.ndarray:
        n_windows = len(data) // window_size
        if n_windows == 0:
            n_windows = 1
            window_size = len(data)
        raw = data.values.copy()
        features = []
        for i in range(n_windows):
            s = i * window_size
            e = s + window_size
            features.append(_extract_window_features(raw[s:e].copy()))
        return np.nan_to_num(np.array(features), nan=0.0, posinf=0.0, neginf=0.0)

    def _build_model(self):
        raise NotImplementedError

    def _anomaly_score(self, scaled: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def fit(self, healthy_data: pd.DataFrame, window_size: int = 500,
            percentile: float = 95.0):
        features = self._prepare_features(healthy_data, window_size)
        if features.shape[0] < 2:
            raise ValueError("Not enough data windows for training")
        scaled = self.scaler.fit_transform(features)
        self.model = self._build_model()
        self.model.fit(scaled)
        train_scores = self._anomaly_score(scaled)
        self.threshold = np.percentile(train_scores, percentile)
        return self

    def predict(self, data: pd.DataFrame,
                window_size: int = 500) -> Tuple[np.ndarray, np.ndarray]:
        features = self._prepare_features(data, window_size)
        scaled = self.scaler.transform(features)
        scores = self._anomaly_score(scaled)
        predictions = (scores > self.threshold).astype(int)
        return scores, predictions

    def get_window_labels(self, labels: np.ndarray,
                          window_size: int = 500,
                          damaged_frac_threshold: float = 0.3) -> np.ndarray:
        return make_window_labels(labels, window_size, damaged_frac_threshold)


class IsolationForestDetector(_WindowAnomalyDetector):
    """Isolation Forest anomaly detector on window features (reviewer baseline)."""

    def __init__(self, n_estimators: int = 200, contamination: str = "auto",
                 random_state: int = 42):
        super().__init__()
        self.n_estimators = n_estimators
        self.contamination = contamination
        self.random_state = random_state

    def _build_model(self):
        return IsolationForest(
            n_estimators=self.n_estimators,
            contamination=self.contamination,
            random_state=self.random_state,
            n_jobs=-1,
        )

    def _anomaly_score(self, scaled: np.ndarray) -> np.ndarray:
        # Higher score => more anomalous (score_samples is the opposite).
        return -self.model.score_samples(scaled)


class OneClassSVMDetector(_WindowAnomalyDetector):
    """One-Class SVM (RBF kernel) anomaly detector (reviewer baseline)."""

    def __init__(self, nu: float = 0.05, gamma: str = "scale"):
        super().__init__()
        self.nu = nu
        self.gamma = gamma

    def _build_model(self):
        return OneClassSVM(kernel="rbf", nu=self.nu, gamma=self.gamma)

    def _anomaly_score(self, scaled: np.ndarray) -> np.ndarray:
        # decision_function > 0 for inliers; negate so higher => anomalous.
        return -self.model.decision_function(scaled)


class LSTMAutoencoderDetector:
    """Sequence (LSTM) autoencoder anomaly detector (reviewer baseline).

    Each window is treated as a short multivariate sequence (sub-sampled to
    ``seq_len`` time steps).  The reconstruction MSE is the anomaly score and
    the operating threshold is the 95th percentile on the healthy training
    set, so the decision point never sees test labels.
    """

    def __init__(self, seq_len: int = 32, hidden_dim: int = 16,
                 epochs: int = 30, batch_size: int = 64, lr: float = 1e-3,
                 seed: int = 42):
        self.seq_len = seq_len
        self.hidden_dim = hidden_dim
        self.epochs = epochs
        self.batch_size = batch_size
        self.lr = lr
        self.seed = seed
        self.scaler = StandardScaler()
        self.model = None
        self.threshold = None
        self.n_features = None

    def _prepare_sequences(self, data: pd.DataFrame,
                           window_size: int = 500) -> np.ndarray:
        n_windows = len(data) // window_size
        if n_windows == 0:
            n_windows = 1
            window_size = len(data)
        raw = data.values.astype(float)
        # Forward/backward fill NaNs so sequences are always defined.
        raw = pd.DataFrame(raw).ffill().bfill().fillna(0.0).values
        seqs = []
        stride = max(1, window_size // self.seq_len)
        for i in range(n_windows):
            w = raw[i * window_size:(i + 1) * window_size]
            sub = w[::stride][:self.seq_len]
            if sub.shape[0] < self.seq_len:
                pad = np.repeat(sub[-1:], self.seq_len - sub.shape[0], axis=0)
                sub = np.vstack([sub, pad])
            seqs.append(sub)
        return np.nan_to_num(np.array(seqs), nan=0.0, posinf=0.0, neginf=0.0)

    def fit(self, healthy_data: pd.DataFrame, window_size: int = 500,
            percentile: float = 95.0):
        import torch
        import torch.nn as nn
        torch.manual_seed(self.seed)
        seqs = self._prepare_sequences(healthy_data, window_size)
        n, t, f = seqs.shape
        self.n_features = f
        flat = seqs.reshape(-1, f)
        flat_scaled = self.scaler.fit_transform(flat)
        seqs_scaled = flat_scaled.reshape(n, t, f)

        class LSTMAE(nn.Module):
            def __init__(ae, n_feat, hid):
                super().__init__()
                ae.enc = nn.LSTM(n_feat, hid, batch_first=True)
                ae.dec = nn.LSTM(hid, hid, batch_first=True)
                ae.out = nn.Linear(hid, n_feat)

            def forward(ae, x):
                _, (h, _) = ae.enc(x)
                rep = h[-1].unsqueeze(1).repeat(1, x.size(1), 1)
                d, _ = ae.dec(rep)
                return ae.out(d)

        device = torch.device("cpu")
        self.model = LSTMAE(f, self.hidden_dim).to(device)
        opt = torch.optim.Adam(self.model.parameters(), lr=self.lr)
        crit = nn.MSELoss()
        x = torch.FloatTensor(seqs_scaled).to(device)

        self.model.train()
        for _ in range(self.epochs):
            perm = torch.randperm(n)
            for b in range(0, n, self.batch_size):
                idx = perm[b:b + self.batch_size]
                xb = x[idx]
                opt.zero_grad()
                loss = crit(self.model(xb), xb)
                loss.backward()
                opt.step()

        self.model.eval()
        with torch.no_grad():
            recon = self.model(x).cpu().numpy()
        errors = np.mean((seqs_scaled - recon) ** 2, axis=(1, 2))
        self.threshold = np.percentile(errors, percentile)
        self._device = device
        return self

    def predict(self, data: pd.DataFrame,
                window_size: int = 500) -> Tuple[np.ndarray, np.ndarray]:
        import torch
        seqs = self._prepare_sequences(data, window_size)
        n, t, f = seqs.shape
        flat_scaled = self.scaler.transform(seqs.reshape(-1, f))
        seqs_scaled = flat_scaled.reshape(n, t, f)
        self.model.eval()
        with torch.no_grad():
            recon = self.model(
                torch.FloatTensor(seqs_scaled).to(self._device)
            ).cpu().numpy()
        errors = np.mean((seqs_scaled - recon) ** 2, axis=(1, 2))
        return errors, (errors > self.threshold).astype(int)

    def get_window_labels(self, labels: np.ndarray,
                          window_size: int = 500,
                          damaged_frac_threshold: float = 0.3) -> np.ndarray:
        return make_window_labels(labels, window_size, damaged_frac_threshold)


def evaluate_detection(true_labels: np.ndarray,
                       predictions: np.ndarray,
                       scores: np.ndarray) -> Dict:
    results = {}
    if len(np.unique(true_labels)) < 2:
        results["note"] = "Only one class present"
        results["accuracy"] = accuracy_score(true_labels, predictions)
        results["f1_score"] = 0.0
        results["roc_auc"] = 0.0
        return results

    # Fixed-threshold metrics
    results["accuracy"] = accuracy_score(true_labels, predictions)
    results["precision"] = precision_score(true_labels, predictions, zero_division=0)
    results["recall"] = recall_score(true_labels, predictions, zero_division=0)
    results["f1_fixed"] = f1_score(true_labels, predictions, zero_division=0)

    try:
        results["roc_auc"] = roc_auc_score(true_labels, scores)
        fpr, tpr, thresholds = roc_curve(true_labels, scores)
        results["fpr"] = fpr
        results["tpr"] = tpr

        # Optimal F1: sweep thresholds to find best F1
        best_f1 = 0.0
        best_cm = None
        for t in thresholds:
            preds_t = (scores >= t).astype(int)
            f1_t = f1_score(true_labels, preds_t, zero_division=0)
            if f1_t > best_f1:
                best_f1 = f1_t
                best_cm = confusion_matrix(true_labels, preds_t)
                best_acc = accuracy_score(true_labels, preds_t)
                best_prec = precision_score(true_labels, preds_t, zero_division=0)
                best_rec = recall_score(true_labels, preds_t, zero_division=0)

        results["f1_score"] = best_f1
        results["opt_accuracy"] = best_acc
        results["opt_precision"] = best_prec
        results["opt_recall"] = best_rec
        results["confusion_matrix"] = best_cm if best_cm is not None else confusion_matrix(true_labels, predictions)
    except Exception:
        results["roc_auc"] = 0.0
        results["f1_score"] = results["f1_fixed"]
        results["confusion_matrix"] = confusion_matrix(true_labels, predictions)

    return results
