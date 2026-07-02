"""
Statistical significance testing for experimental results.

Provides multi-seed repeated experiments with confidence intervals
and paired t-tests / Wilcoxon signed-rank tests.
"""
import numpy as np
import pandas as pd
from scipy import stats
from typing import Dict, List, Tuple, Callable
from collections import OrderedDict


def repeated_experiment(
    experiment_fn: Callable,
    seeds: List[int],
    **kwargs
) -> Dict[str, np.ndarray]:
    """
    Run an experiment function multiple times with different random seeds.

    Args:
        experiment_fn: Function(seed, **kwargs) -> dict of metric_name -> value
        seeds: List of random seeds for repetition
        **kwargs: Additional arguments passed to experiment_fn

    Returns:
        Dict mapping metric_name -> array of values across seeds
    """
    all_results = []
    for seed in seeds:
        result = experiment_fn(seed=seed, **kwargs)
        all_results.append(result)

    metrics = {}
    for key in all_results[0].keys():
        vals = [r.get(key, np.nan) for r in all_results]
        if isinstance(vals[0], (int, float, np.floating, np.integer)):
            metrics[key] = np.array(vals, dtype=float)
    return metrics


def compute_ci(values: np.ndarray, confidence: float = 0.95) -> Tuple[float, float, float]:
    """
    Compute mean and confidence interval.

    Returns (mean, ci_lower, ci_upper).
    """
    n = len(values)
    mean = np.mean(values)
    if n < 2:
        return mean, mean, mean
    se = stats.sem(values)
    ci = stats.t.interval(confidence, df=n-1, loc=mean, scale=se)
    return mean, ci[0], ci[1]


def paired_test(values_a: np.ndarray, values_b: np.ndarray,
                test: str = "t-test") -> Dict:
    """
    Perform paired statistical test between two conditions.

    Args:
        values_a, values_b: Paired measurements from N repetitions
        test: "t-test" for parametric, "wilcoxon" for non-parametric

    Returns dict with test statistic, p-value, effect size (Cohen's d)
    """
    diff = values_a - values_b
    result = {"mean_diff": np.mean(diff), "std_diff": np.std(diff, ddof=1)}

    if test == "t-test":
        stat, pval = stats.ttest_rel(values_a, values_b)
        result["test"] = "Paired t-test"
    else:
        stat, pval = stats.wilcoxon(values_a, values_b, alternative='two-sided')
        result["test"] = "Wilcoxon signed-rank"

    result["statistic"] = stat
    result["p_value"] = pval

    # Cohen's d for effect size
    pooled_std = np.sqrt((np.var(values_a, ddof=1) + np.var(values_b, ddof=1)) / 2)
    if pooled_std > 0:
        result["cohens_d"] = np.mean(diff) / pooled_std
    else:
        result["cohens_d"] = 0.0

    result["significant"] = pval < 0.05

    return result


def format_with_ci(values: np.ndarray, fmt: str = ".4f") -> str:
    """Format mean ± std for reporting."""
    mean = np.mean(values)
    std = np.std(values, ddof=1) if len(values) > 1 else 0.0
    return f"{mean:{fmt}} ± {std:{fmt}}"


def bootstrap_ci(values: np.ndarray, n_boot: int = 2000,
                 confidence: float = 0.95,
                 seed: int = 12345) -> Tuple[float, float, float]:
    """Percentile bootstrap confidence interval for the mean.

    Returns ``(mean, ci_lower, ci_upper)``.  Falls back to the
    analytical t-interval when ``n_boot`` is non-positive.
    """
    values = np.asarray(values, dtype=float)
    n = len(values)
    mean = float(np.mean(values))
    if n < 2:
        return mean, mean, mean
    if n_boot <= 0:
        return compute_ci(values, confidence=confidence)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_means = values[idx].mean(axis=1)
    lo = float(np.percentile(boot_means, (1 - confidence) / 2 * 100))
    hi = float(np.percentile(boot_means, (1 + confidence) / 2 * 100))
    return mean, lo, hi


def format_with_bootstrap(values: np.ndarray, n_boot: int = 2000,
                          fmt: str = ".3f", confidence: float = 0.95) -> str:
    """Format ``mean [CI_lo, CI_hi]`` using percentile bootstrap."""
    mean, lo, hi = bootstrap_ci(values, n_boot=n_boot, confidence=confidence)
    return f"{mean:{fmt}} [{lo:{fmt}}, {hi:{fmt}}]"


def spearman_kendall(values_matrix: np.ndarray) -> Dict[str, np.ndarray]:
    """Compute pairwise Spearman and Kendall rank correlations between
    columns (e.g. sensor rankings under different weighting schemes).

    Parameters
    ----------
    values_matrix : np.ndarray, shape (n_items, n_schemes)
        Scores to be ranked; each column is one scheme.

    Returns
    -------
    dict with keys
        ``spearman`` : (n_schemes, n_schemes) matrix of Spearman rho.
        ``kendall``  : (n_schemes, n_schemes) matrix of Kendall tau.
    """
    vals = np.asarray(values_matrix, dtype=float)
    n_items, n_schemes = vals.shape
    sp = np.eye(n_schemes)
    kd = np.eye(n_schemes)
    for i in range(n_schemes):
        for j in range(i + 1, n_schemes):
            rho, _ = stats.spearmanr(vals[:, i], vals[:, j])
            tau, _ = stats.kendalltau(vals[:, i], vals[:, j])
            sp[i, j] = sp[j, i] = rho
            kd[i, j] = kd[j, i] = tau
    return {"spearman": sp, "kendall": kd}


def summary_table(results_dict: Dict[str, Dict[str, np.ndarray]],
                  metrics: List[str] = None) -> pd.DataFrame:
    """
    Create a summary table with mean ± std for all conditions and metrics.

    Args:
        results_dict: {condition_name: {metric_name: array of values}}
        metrics: List of metric names to include (None = all)

    Returns DataFrame with formatted results
    """
    rows = []
    for cond_name, cond_results in results_dict.items():
        row = {"Condition": cond_name}
        available_metrics = metrics or list(cond_results.keys())
        for m in available_metrics:
            vals = cond_results.get(m)
            if vals is not None and len(vals) > 0:
                mean, ci_lo, ci_hi = compute_ci(vals)
                row[f"{m}_mean"] = mean
                row[f"{m}_std"] = np.std(vals, ddof=1)
                row[f"{m}_ci_lo"] = ci_lo
                row[f"{m}_ci_hi"] = ci_hi
                row[f"{m}"] = format_with_ci(vals)
        rows.append(row)
    return pd.DataFrame(rows)
