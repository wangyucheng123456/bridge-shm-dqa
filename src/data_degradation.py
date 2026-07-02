"""
Data Degradation Module — artificially inject quality defects.

Creates controlled experimental groups:
- Group 1: Baseline (original data)
- Group 2: Random missing blocks (5%, 10%, 20%)
- Group 3: Gaussian noise injection (SNR 20dB, 10dB, 5dB)
- Group 4: Repaired data (after cleaning/imputation)
"""
import numpy as np
import pandas as pd
from typing import List, Tuple
from src.config import MISSING_RATES, NOISE_SNR_DB, RANDOM_SEED


def inject_random_missing(data: pd.DataFrame, missing_rate: float,
                          block_size_range: Tuple[int, int] = (10, 200),
                          seed: int = RANDOM_SEED) -> pd.DataFrame:
    """
    Inject missing data blocks to simulate sensor dropout / transmission loss.
    Missing values appear as contiguous blocks (more realistic than point-wise).
    """
    rng = np.random.default_rng(seed)
    degraded = data.copy()
    n_rows, n_cols = data.shape
    total_to_remove = int(n_rows * missing_rate)

    for col_idx in range(n_cols):
        removed = 0
        attempts = 0
        while removed < total_to_remove and attempts < 10000:
            block_len = rng.integers(block_size_range[0], block_size_range[1])
            start = rng.integers(0, max(n_rows - block_len, 1))
            end = min(start + block_len, n_rows)
            degraded.iloc[start:end, col_idx] = np.nan
            removed += (end - start)
            attempts += 1

    return degraded


def inject_gaussian_noise(data: pd.DataFrame, target_snr_db: float,
                          seed: int = RANDOM_SEED) -> pd.DataFrame:
    """
    Add Gaussian white noise to achieve a target SNR level.

    SNR(dB) = 10 * log10(P_signal / P_noise)
    => P_noise = P_signal / 10^(SNR/10)
    """
    rng = np.random.default_rng(seed)
    noisy = data.copy().astype(float)

    for col in data.columns:
        vals = data[col].dropna().values.astype(float)
        if len(vals) == 0:
            continue
        p_signal = np.mean(vals ** 2)
        if p_signal < 1e-20:
            p_signal = 1e-20
        p_noise_target = p_signal / (10 ** (target_snr_db / 10))
        noise_std = np.sqrt(p_noise_target)
        noise = rng.normal(0, noise_std, len(data))
        mask = data[col].notna()
        noisy.loc[mask, col] = data.loc[mask, col].values + noise[mask.values]

    return noisy


def inject_spikes(data: pd.DataFrame, spike_rate: float = 0.005,
                  spike_magnitude: float = 5.0,
                  seed: int = RANDOM_SEED) -> pd.DataFrame:
    """Inject random spikes/outliers into data."""
    rng = np.random.default_rng(seed)
    spiked = data.copy().astype(float)

    for col in data.columns:
        vals = data[col].dropna().values
        if len(vals) == 0:
            continue
        std = np.std(vals)
        n_spikes = int(len(data) * spike_rate)
        spike_idx = rng.choice(len(data), size=n_spikes, replace=False)
        spike_vals = rng.choice([-1, 1], size=n_spikes) * spike_magnitude * std
        spiked.iloc[spike_idx, data.columns.get_loc(col)] += spike_vals

    return spiked


def inject_drift(data: pd.DataFrame, drift_magnitude: float = 0.5,
                 seed: int = RANDOM_SEED,
                 healthy_end: int = None) -> pd.DataFrame:
    """Inject linear sensor-calibration drift WITHIN the healthy (pre-damage)
    segment only.

    Rationale
    ---------
    Earlier versions injected drift uniformly across the whole record,
    which spanned both healthy and damaged segments.  Because the injected
    linear trend runs across the eventual damage boundary, it becomes
    correlated with the label and can artificially amplify any detector's
    apparent separability.  To avoid this label-leakage, the drift is now
    only applied inside the healthy region ``[0, healthy_end)`` and is
    zero for the damaged tail.  If ``healthy_end`` is ``None`` the drift
    is restricted to the first half of the record as a safe default.
    """
    rng = np.random.default_rng(seed)
    drifted = data.copy().astype(float)
    n = len(data)
    if healthy_end is None or healthy_end <= 0 or healthy_end >= n:
        healthy_end = n // 2

    for col in data.columns:
        vals = data[col].dropna().values
        if len(vals) == 0:
            continue
        std = np.std(vals)
        drift = np.zeros(n)
        start_point = int(rng.integers(healthy_end // 3,
                                       max(2 * healthy_end // 3, healthy_end // 3 + 1)))
        end_point = healthy_end
        if end_point > start_point:
            drift[start_point:end_point] = np.linspace(
                0.0, drift_magnitude * std, end_point - start_point
            )
        mask = data[col].notna()
        drifted.loc[mask, col] = data.loc[mask, col].values + drift[mask.values]

    return drifted


def create_all_degraded_datasets(data: pd.DataFrame,
                                 healthy_end: int = None) -> dict:
    """
    Create the complete set of experimental groups.

    Parameters
    ----------
    data : pd.DataFrame
        Clean reference signal.
    healthy_end : int, optional
        Index marking the end of the healthy (pre-damage) segment.
        Used by :func:`inject_drift` to avoid label leakage; other
        injectors ignore this.  If ``None``, drift is restricted to the
        first half of the record.

    Returns dict mapping group name -> degraded DataFrame.
    """
    groups = {"baseline": data.copy()}

    for rate in MISSING_RATES:
        label = f"missing_{int(rate*100)}pct"
        groups[label] = inject_random_missing(data, rate, seed=RANDOM_SEED + int(rate * 100))

    for snr in NOISE_SNR_DB:
        label = f"noise_{snr}dB"
        groups[label] = inject_gaussian_noise(data, snr, seed=RANDOM_SEED + snr)

    groups["spikes_0.5pct"] = inject_spikes(data, spike_rate=0.005, seed=RANDOM_SEED + 200)
    groups["drift"] = inject_drift(data, drift_magnitude=0.5, seed=RANDOM_SEED + 300,
                                   healthy_end=healthy_end)

    # Combined degradation: missing + noise
    for rate in [0.10, 0.20]:
        for snr in [10, 5]:
            label = f"combined_miss{int(rate*100)}_snr{snr}"
            temp = inject_random_missing(data, rate, seed=RANDOM_SEED + int(rate * 100) + snr)
            groups[label] = inject_gaussian_noise(temp, snr, seed=RANDOM_SEED + snr + 50)

    return groups
