"""
Data Quality Assessment (DQA) Metrics for Bridge SHM.

Implements four quality dimensions:
1. Completeness - Missing data ratio
2. Accuracy - Outlier/spike detection rate
3. Consistency - Drift and trend anomaly detection
4. Signal-to-Noise Ratio (SNR)
"""
import numpy as np
import pandas as pd
from scipy import stats, signal as sig_proc
from typing import Dict, Tuple


def compute_completeness(data: pd.DataFrame) -> pd.Series:
    """
    Completeness score per sensor channel.
    Score = 1 - (missing_count / total_count), range [0, 1].
    """
    missing_rate = data.isnull().mean()
    return 1.0 - missing_rate


def detect_outliers_mad(series: np.ndarray, threshold: float = 3.5) -> np.ndarray:
    """Detect outliers using Median Absolute Deviation (MAD)."""
    valid = series[~np.isnan(series)]
    if len(valid) == 0:
        return np.zeros(len(series), dtype=bool)
    median = np.nanmedian(series)
    mad = np.nanmedian(np.abs(series - median))
    if mad == 0:
        mad = 1e-10
    modified_z = 0.6745 * (series - median) / mad
    return np.abs(modified_z) > threshold


def detect_outliers_sigma(series: np.ndarray, n_sigma: float = 3.0) -> np.ndarray:
    """Detect outliers using n-sigma rule."""
    mean = np.nanmean(series)
    std = np.nanstd(series)
    if std == 0:
        std = 1e-10
    return np.abs(series - mean) > n_sigma * std


def compute_accuracy(data: pd.DataFrame, method: str = "mad") -> pd.Series:
    """
    Accuracy score per channel.
    Score = 1 - outlier_rate, range [0, 1].
    """
    outlier_rates = {}
    detect_fn = detect_outliers_mad if method == "mad" else detect_outliers_sigma
    for col in data.columns:
        vals = data[col].values.astype(float)
        outliers = detect_fn(vals)
        outlier_rates[col] = np.nanmean(outliers)
    return 1.0 - pd.Series(outlier_rates)


def compute_drift_score(data: pd.DataFrame, window_hours: int = 24,
                        fs: float = 1.0) -> pd.Series:
    """
    Consistency score based on drift detection.

    Uses a rolling mean comparison against the global mean.
    High drift => low consistency score.
    """
    window_size = max(int(window_hours * 3600 * fs), 100)
    drift_scores = {}
    for col in data.columns:
        vals = data[col].dropna().values
        if len(vals) < window_size:
            drift_scores[col] = 1.0
            continue
        global_mean = np.mean(vals)
        global_std = np.std(vals)
        if global_std == 0:
            drift_scores[col] = 1.0
            continue
        rolling_mean = pd.Series(vals).rolling(window=window_size, center=True).mean().dropna().values
        max_deviation = np.max(np.abs(rolling_mean - global_mean)) / global_std
        score = max(0.0, 1.0 - max_deviation / 5.0)
        drift_scores[col] = score
    return pd.Series(drift_scores)


def compute_snr(data: pd.DataFrame, fs: float = 1.0,
                cutoff_ratio: float = 0.3) -> pd.Series:
    """
    Signal-to-Noise Ratio in dB per channel.
    SNR = 10 * log10(P_signal / P_noise).

    Uses a low-pass filter to separate signal from noise.
    """
    snr_values = {}
    nyq = fs / 2.0
    cutoff = cutoff_ratio * nyq
    if cutoff <= 0 or cutoff >= nyq:
        cutoff = 0.3 * nyq

    for col in data.columns:
        vals = data[col].dropna().values.astype(float)
        if len(vals) < 50:
            snr_values[col] = 0.0
            continue
        try:
            b, a = sig_proc.butter(4, cutoff / nyq, btype='low')
            filtered = sig_proc.filtfilt(b, a, vals)
            noise = vals - filtered
            p_signal = np.mean(filtered ** 2)
            p_noise = np.mean(noise ** 2)
            if p_noise < 1e-20:
                p_noise = 1e-20
            snr_values[col] = 10 * np.log10(p_signal / p_noise)
        except Exception:
            snr_values[col] = 0.0
    return pd.Series(snr_values)


def compute_snr_score(snr_series: pd.Series, max_snr: float = 40.0) -> pd.Series:
    """Normalize SNR to [0, 1] score."""
    return (snr_series.clip(0, max_snr) / max_snr)


def compute_entropy_weights(
    completeness: pd.Series,
    accuracy: pd.Series,
    consistency: pd.Series,
    snr_score: pd.Series,
) -> Tuple[Tuple[float, ...], pd.DataFrame]:
    """
    Compute objective weights using the Entropy Weight Method (EWM).

    Based on Shannon entropy: dimensions with higher variation across sensors
    carry more information and receive higher weights. This provides a
    data-driven, theoretically grounded alternative to expert-assigned weights.

    Reference: Shannon, C.E. (1948). A mathematical theory of communication.
    """
    all_cols = completeness.index
    matrix = pd.DataFrame({
        'completeness': completeness,
        'accuracy': accuracy,
        'consistency': consistency,
        'snr_score': snr_score,
    }, index=all_cols)

    n, m = matrix.shape
    if n <= 1:
        return (0.25, 0.25, 0.25, 0.25), matrix

    normed = matrix.copy()
    for col in normed.columns:
        col_sum = normed[col].sum()
        if col_sum > 0:
            normed[col] = normed[col] / col_sum
        else:
            normed[col] = 1.0 / n

    eps = 1e-12
    k = 1.0 / np.log(n)
    entropies = {}
    for col in normed.columns:
        p = normed[col].values.clip(eps)
        entropies[col] = -k * np.sum(p * np.log(p))

    divergences = {col: 1.0 - e for col, e in entropies.items()}
    total_div = sum(divergences.values())

    if total_div < eps:
        weights = tuple([0.25] * 4)
    else:
        weights = tuple(divergences[col] / total_div for col in matrix.columns)

    return weights, matrix


def compute_composite_quality_score(
    completeness: pd.Series,
    accuracy: pd.Series,
    consistency: pd.Series,
    snr_score: pd.Series,
    weights: Tuple[float, ...] = (0.3, 0.3, 0.2, 0.2)
) -> pd.Series:
    """
    Weighted composite Data Quality Score (0-100) per sensor.
    """
    all_cols = completeness.index
    scores = {}
    for col in all_cols:
        c = completeness.get(col, 0.0)
        a = accuracy.get(col, 0.0)
        d = consistency.get(col, 0.0)
        s = snr_score.get(col, 0.0)
        composite = (weights[0] * c + weights[1] * a +
                     weights[2] * d + weights[3] * s) * 100
        scores[col] = round(composite, 2)
    return pd.Series(scores)


def full_quality_assessment(data: pd.DataFrame, fs: float = 1.0) -> Dict:
    """
    Run complete DQA pipeline and return all metrics.
    """
    completeness = compute_completeness(data)
    accuracy = compute_accuracy(data, method="mad")
    consistency = compute_drift_score(data, fs=fs)
    snr = compute_snr(data, fs=fs)
    snr_score = compute_snr_score(snr)
    composite = compute_composite_quality_score(
        completeness, accuracy, consistency, snr_score
    )

    return {
        "completeness": completeness,
        "accuracy": accuracy,
        "consistency": consistency,
        "snr_db": snr,
        "snr_score": snr_score,
        "composite_score": composite,
    }
