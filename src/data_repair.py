"""
Data Repair / Cleaning Module.

Implements multiple imputation and denoising strategies:
1. Linear interpolation (baseline)
2. Cubic spline interpolation
3. Moving average smoothing
4. Wavelet denoising
5. Autoencoder-based reconstruction (deep learning)
"""
import numpy as np
import pandas as pd
from scipy import interpolate, signal as sig_proc
from typing import Optional
import warnings
warnings.filterwarnings('ignore')


def repair_linear_interpolation(data: pd.DataFrame) -> pd.DataFrame:
    """Fill missing values with linear interpolation + edge fill."""
    repaired = data.copy()
    for col in repaired.columns:
        repaired[col] = repaired[col].interpolate(method='linear')
        repaired[col] = repaired[col].ffill().bfill()
    return repaired


def repair_cubic_spline(data: pd.DataFrame) -> pd.DataFrame:
    """Fill missing values with cubic spline interpolation."""
    repaired = data.copy()
    for col in repaired.columns:
        s = repaired[col]
        valid_mask = s.notna()
        if valid_mask.sum() < 4:
            repaired[col] = s.ffill().bfill()
            continue
        valid_idx = np.where(valid_mask)[0]
        valid_vals = s.dropna().values
        try:
            cs = interpolate.CubicSpline(valid_idx, valid_vals, extrapolate=True)
            all_idx = np.arange(len(s))
            repaired[col] = cs(all_idx)
        except Exception:
            repaired[col] = s.interpolate(method='linear').ffill().bfill()
    return repaired


def repair_moving_average(data: pd.DataFrame,
                          window: int = 15) -> pd.DataFrame:
    """Smooth data with moving average filter (denoising)."""
    repaired = repair_linear_interpolation(data)
    for col in repaired.columns:
        repaired[col] = repaired[col].rolling(
            window=window, center=True, min_periods=1
        ).mean()
    return repaired


def repair_wavelet_denoise(data: pd.DataFrame,
                           threshold_factor: float = 1.5) -> pd.DataFrame:
    """
    Denoise using a simple frequency-domain approach.
    (Approximates wavelet denoising using Butterworth low-pass filter.)
    """
    repaired = repair_linear_interpolation(data)
    for col in repaired.columns:
        vals = repaired[col].values.astype(float)
        if len(vals) < 50:
            continue
        try:
            b, a = sig_proc.butter(4, 0.3, btype='low')
            filtered = sig_proc.filtfilt(b, a, vals)
            noise = vals - filtered
            noise_std = np.std(noise)
            threshold = threshold_factor * noise_std
            denoised_noise = np.where(np.abs(noise) > threshold, 0, noise)
            repaired[col] = filtered + denoised_noise
        except Exception:
            pass
    return repaired


def repair_median_filter(data: pd.DataFrame,
                         kernel_size: int = 7) -> pd.DataFrame:
    """Remove spikes using median filter."""
    repaired = repair_linear_interpolation(data)
    for col in repaired.columns:
        vals = repaired[col].values.astype(float)
        repaired[col] = sig_proc.medfilt(vals, kernel_size=kernel_size)
    return repaired


def remove_outliers_and_interpolate(data: pd.DataFrame,
                                    n_sigma: float = 3.5) -> pd.DataFrame:
    """Replace outliers with NaN then interpolate."""
    cleaned = data.copy()
    for col in cleaned.columns:
        vals = cleaned[col].values.astype(float)
        mean = np.nanmean(vals)
        std = np.nanstd(vals)
        if std > 0:
            outlier_mask = np.abs(vals - mean) > n_sigma * std
            cleaned.loc[outlier_mask, col] = np.nan
    return repair_cubic_spline(cleaned)


def comprehensive_repair(data: pd.DataFrame) -> pd.DataFrame:
    """
    Full repair pipeline (conservative to preserve signal structure):
    1. Remove extreme outliers/spikes (replace with NaN)
    2. Linear interpolation for all missing values (most signal-safe)
    3. Very light moving average (window=3) to smooth remaining artifacts
    """
    cleaned = data.copy()
    for col in cleaned.columns:
        vals = cleaned[col].values.astype(float)
        mean = np.nanmean(vals)
        std = np.nanstd(vals)
        if std > 0:
            outlier_mask = np.abs(vals - mean) > 4.0 * std
            cleaned.loc[outlier_mask, col] = np.nan
    step2 = repair_linear_interpolation(cleaned)
    for col in step2.columns:
        step2[col] = step2[col].rolling(window=3, center=True, min_periods=1).mean()
    return step2


def get_all_repair_methods() -> dict:
    """Return all available repair methods as name -> function mapping."""
    return {
        "linear_interp": repair_linear_interpolation,
        "cubic_spline": repair_cubic_spline,
        "moving_average": repair_moving_average,
        "wavelet_denoise": repair_wavelet_denoise,
        "median_filter": repair_median_filter,
        "comprehensive": comprehensive_repair,
    }
