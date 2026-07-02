"""
=============================================================================
Main Experiment Pipeline V2 — Real Data + Statistical Significance
=============================================================================
Paper: A Comprehensive Data Quality Assessment and Enhancement Framework
       for Bridge Structural Health Monitoring

Key improvements over V1:
  1. Uses REAL datasets (Vänersborg + Z-24) instead of synthetic
  2. Statistical significance: 10-seed repeated experiments with CI and t-tests
  3. Complete repair × defect evaluation matrix
  4. DQA weight sensitivity analysis
  5. Stronger Z-24 cross-validation
=============================================================================
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import numpy as np
import pandas as pd
from collections import OrderedDict
import time
import warnings
warnings.filterwarnings('ignore')

from src.config import *
from src.data_loader import load_vanersborg_data, load_z24_data, check_data_availability
from src.dqa_metrics import (
    full_quality_assessment, compute_composite_quality_score,
    compute_completeness, compute_accuracy, compute_drift_score,
    compute_snr, compute_snr_score, compute_entropy_weights
)
from src.data_degradation import (
    inject_random_missing, inject_gaussian_noise, inject_spikes,
    inject_drift, create_all_degraded_datasets
)
from src.data_repair import get_all_repair_methods
from src.damage_detection import (
    PCADamageDetector, AutoencoderDamageDetector, evaluate_detection
)
from src.statistical import (
    repeated_experiment, compute_ci, paired_test,
    format_with_ci, summary_table,
    bootstrap_ci, format_with_bootstrap, spearman_kendall
)
from src.visualization import (
    plot_missing_heatmap, plot_timeseries_comparison,
    plot_bridge_quality_map, plot_degradation_curves,
    plot_roc_curves, plot_confusion_matrices,
    plot_dqa_radar, plot_quality_boxplot,
    plot_repair_comparison_bar
)


def print_header(msg: str):
    print(f"\n{'='*70}")
    print(f"  {msg}")
    print(f"{'='*70}")


def run_detection_with_seed(seed, detector_class, train_data, test_data,
                            test_labels, window_size, **det_kwargs):
    """Run single detection experiment with a specific seed for degradation."""
    detector = detector_class(**det_kwargs)
    detector.fit(train_data, window_size=window_size)
    errors, predictions = detector.predict(test_data, window_size=window_size)
    window_labels = detector.get_window_labels(test_labels, window_size=window_size)

    min_len = min(len(window_labels), len(predictions))
    window_labels = window_labels[:min_len]
    predictions = predictions[:min_len]
    errors = errors[:min_len]

    results = evaluate_detection(window_labels, predictions, errors)
    return results


def run_repeated_detection(n_seeds, detector_class, clean_train, all_sensors,
                           labels, test_start, window_size, degrade_fn=None,
                           **det_kwargs):
    """
    Run detection experiment N times with different degradation seeds.
    Returns dict of metric_name -> array of values.
    """
    f1_vals, auc_vals, acc_vals, prec_vals, rec_vals = [], [], [], [], []

    for i, seed in enumerate(STAT_SEEDS[:n_seeds]):
        if degrade_fn is not None:
            degraded = degrade_fn(all_sensors, seed=seed)
            test_data = degraded.iloc[test_start:]
        else:
            test_data = all_sensors.iloc[test_start:]

        test_labels = labels[test_start:]
        results = run_detection_with_seed(
            seed, detector_class, clean_train, test_data, test_labels,
            window_size, **det_kwargs
        )
        f1_vals.append(results.get('f1_score', 0))
        auc_vals.append(results.get('roc_auc', 0))
        acc_vals.append(results.get('accuracy', 0))
        prec_vals.append(results.get('opt_precision', results.get('precision', 0)))
        rec_vals.append(results.get('opt_recall', results.get('recall', 0)))

    return {
        'f1_score': np.array(f1_vals),
        'roc_auc': np.array(auc_vals),
        'accuracy': np.array(acc_vals),
        'precision': np.array(prec_vals),
        'recall': np.array(rec_vals),
    }


# =============================================================================
def run_vanersborg_experiments(vb_data: dict) -> dict:
    """Run all experiments on Vänersborg Bridge data."""
    print_header("VANERSBORG BRIDGE EXPERIMENTS")
    results = {}

    all_sensors = pd.concat([
        vb_data["acceleration"],
        vb_data.get("strain", pd.DataFrame()),
        vb_data.get("tilt", pd.DataFrame()),
    ], axis=1)
    all_sensors = all_sensors.dropna(axis=1, how='all')
    all_sensors = all_sensors.loc[:, all_sensors.nunique() > 1]

    # Limit to 10 sensors max to manage memory on large datasets
    if all_sensors.shape[1] > 10:
        print(f"  Reducing from {all_sensors.shape[1]} to 10 sensors for memory")
        all_sensors = all_sensors.iloc[:, :10]

    fracture_idx = vb_data["fracture_idx"]
    labels = vb_data["labels"]
    fs = vb_data["fs"]

    # Subsample to manage memory (~500K total is practical for repair operations)
    MAX_SAMPLES = 500000
    if len(all_sensors) > MAX_SAMPLES:
        n_total_orig = len(all_sensors)
        step = max(1, n_total_orig // MAX_SAMPLES)
        all_sensors = all_sensors.iloc[::step].reset_index(drop=True)
        fracture_idx = fracture_idx // step
        labels = labels[::step]
        fs = fs / step
        print(f"  Subsampled {n_total_orig} -> {len(all_sensors)} (step={step})")

    print(f"  Data shape: {all_sensors.shape}")
    print(f"  Sensors: {list(all_sensors.columns)}")
    print(f"  Fracture at idx: {fracture_idx}")
    print(f"  Sampling freq: {fs} Hz")

    # Adaptive window size based on data length
    n_total = len(all_sensors)
    window_size = max(50, min(200, n_total // 100))
    print(f"  Window size: {window_size}")

    # Train/test split
    train_end = int(fracture_idx * 0.67)
    test_start = train_end
    clean_train = all_sensors.iloc[:train_end]

    print(f"  Training samples: {train_end}")
    print(f"  Test samples: {n_total - test_start}")

    # ===================== Phase 1: Baseline DQA =====================
    print("\n--- Phase 1: Baseline Data Quality Assessment ---")
    baseline_metrics = full_quality_assessment(all_sensors, fs=fs)
    metrics_df = pd.DataFrame({
        "Completeness": baseline_metrics["completeness"],
        "Accuracy": baseline_metrics["accuracy"],
        "Consistency": baseline_metrics["consistency"],
        "SNR (dB)": baseline_metrics["snr_db"],
        "Composite": baseline_metrics["composite_score"],
    })
    print(metrics_df.round(3).to_string())
    metrics_df.to_csv(os.path.join(TABLES_DIR, "vanersborg_baseline_dqa.csv"))
    results["baseline_metrics"] = baseline_metrics

    # ===================== Phase 2: Data Degradation =====================
    print("\n--- Phase 2: Creating Degraded Groups ---")
    # Restrict drift to the pre-damage segment to avoid label leakage.
    degraded_groups = create_all_degraded_datasets(all_sensors,
                                                   healthy_end=fracture_idx)
    all_group_metrics = OrderedDict()
    all_composite_scores = OrderedDict()
    for name, data in degraded_groups.items():
        metrics = full_quality_assessment(data, fs=fs)
        all_group_metrics[name] = metrics
        all_composite_scores[name] = metrics["composite_score"]
        avg = metrics["composite_score"].mean()
        print(f"  {name:30s} composite: {avg:.1f}/100")
    results["degraded_groups"] = degraded_groups
    results["all_group_metrics"] = all_group_metrics
    results["all_composite_scores"] = all_composite_scores

    # ===================== Phase 3: Repair =====================
    print("\n--- Phase 3: Data Repair ---")
    repair_methods = get_all_repair_methods()
    repaired_datasets = {}

    # Complete repair × defect matrix
    defect_keys = ["missing_5pct", "missing_10pct", "missing_20pct",
                   "noise_20dB", "noise_10dB", "noise_5dB",
                   "spikes_0.5pct", "drift"]

    for defect_key in defect_keys:
        if defect_key not in degraded_groups:
            continue
        for method_name, method_fn in repair_methods.items():
            key = f"{defect_key}_{method_name}"
            repaired_datasets[key] = method_fn(degraded_groups[defect_key])

    print(f"  Generated {len(repaired_datasets)} repair combinations")
    results["repaired_datasets"] = repaired_datasets

    # ===================== Phase 4: Detection with Stats =====================
    print("\n--- Phase 4: Damage Detection with Statistical Significance ---")

    n_seeds = N_REPEAT_SEEDS  # PCA: full 20 seeds
    detection_stats = OrderedDict()
    detection_single = OrderedDict()  # Single-run results for ROC/CM

    # Baseline (no degradation) - single run (no randomness)
    print("  [baseline] Running detection...")
    baseline_result = run_detection_with_seed(
        RANDOM_SEED, PCADamageDetector, clean_train,
        all_sensors.iloc[test_start:], labels[test_start:],
        window_size, n_components=PCA_N_COMPONENTS
    )
    detection_single["baseline"] = baseline_result
    detection_stats["baseline"] = {
        'f1_score': np.array([baseline_result.get('f1_score', 0)] * n_seeds),
        'roc_auc': np.array([baseline_result.get('roc_auc', 0)] * n_seeds),
    }
    print(f"    PCA F1={baseline_result.get('f1_score',0):.4f}, "
          f"AUC={baseline_result.get('roc_auc',0):.4f}")

    # Degraded conditions with multiple seeds
    def _make_degrade_fn(defect_name, healthy_end=None):
        if defect_name.startswith("missing"):
            rate = int(defect_name.split("_")[1].replace("pct", "")) / 100
            return lambda d, seed: inject_random_missing(d, rate, seed=seed)
        if defect_name.startswith("noise"):
            snr = int(defect_name.split("_")[1].replace("dB", ""))
            return lambda d, seed, s=snr: inject_gaussian_noise(d, s, seed=seed)
        if defect_name == "spikes_0.5pct":
            return lambda d, seed: inject_spikes(d, spike_rate=0.005, seed=seed)
        if defect_name == "drift":
            return lambda d, seed, he=healthy_end: inject_drift(
                d, drift_magnitude=0.5, seed=seed, healthy_end=he)
        return None

    for defect_name in ["missing_5pct", "missing_10pct", "missing_20pct",
                        "noise_20dB", "noise_10dB", "noise_5dB",
                        "spikes_0.5pct", "drift"]:
        print(f"  [{defect_name}] Running {n_seeds}-seed detection...")
        degrade_fn = _make_degrade_fn(defect_name, healthy_end=fracture_idx)
        if degrade_fn is None:
            continue

        stats_r = run_repeated_detection(
            n_seeds, PCADamageDetector, clean_train, all_sensors,
            labels, test_start, window_size,
            degrade_fn=degrade_fn, n_components=PCA_N_COMPONENTS
        )
        detection_stats[defect_name] = stats_r
        f1_str = format_with_ci(stats_r['f1_score'])
        auc_str = format_with_ci(stats_r['roc_auc'])
        print(f"    PCA F1={f1_str}, AUC={auc_str}")

        # Also get single-run result for ROC/CM
        if defect_name in degraded_groups:
            single_r = run_detection_with_seed(
                RANDOM_SEED, PCADamageDetector, clean_train,
                degraded_groups[defect_name].iloc[test_start:],
                labels[test_start:], window_size, n_components=PCA_N_COMPONENTS
            )
            detection_single[defect_name] = single_r

    # Autoencoder on ALL conditions with multi-seed repetitions
    try:
        from src.config import N_REPEAT_SEEDS_AE
    except ImportError:
        N_REPEAT_SEEDS_AE = 10
    n_seeds_ae = min(N_REPEAT_SEEDS_AE, n_seeds)

    print(f"\n  --- Autoencoder Detection ({n_seeds_ae} seeds, full matrix) ---")
    ae_detection_stats = OrderedDict()

    print(f"  [AE baseline] Running {n_seeds_ae}-seed detection...")
    ae_bl = run_repeated_detection(
        n_seeds_ae, AutoencoderDamageDetector, clean_train, all_sensors,
        labels, test_start, window_size, degrade_fn=None,
        latent_dim=AUTOENCODER_LATENT_DIM, epochs=AUTOENCODER_EPOCHS,
        batch_size=AUTOENCODER_BATCH_SIZE, lr=AUTOENCODER_LR
    )
    ae_detection_stats["baseline"] = ae_bl
    print(f"    AE F1={format_with_ci(ae_bl['f1_score'])}, "
          f"AUC={format_with_ci(ae_bl['roc_auc'])}")

    for defect_name in ["missing_5pct", "missing_10pct", "missing_20pct",
                        "noise_20dB", "noise_10dB", "noise_5dB",
                        "spikes_0.5pct", "drift"]:
        degrade_fn = _make_degrade_fn(defect_name, healthy_end=fracture_idx)
        if degrade_fn is None:
            continue
        print(f"  [AE {defect_name}] Running {n_seeds_ae}-seed detection...")
        ae_r = run_repeated_detection(
            n_seeds_ae, AutoencoderDamageDetector, clean_train, all_sensors,
            labels, test_start, window_size, degrade_fn=degrade_fn,
            latent_dim=AUTOENCODER_LATENT_DIM, epochs=AUTOENCODER_EPOCHS,
            batch_size=AUTOENCODER_BATCH_SIZE, lr=AUTOENCODER_LR
        )
        ae_detection_stats[defect_name] = ae_r
        print(f"    AE F1={format_with_ci(ae_r['f1_score'])}, "
              f"AUC={format_with_ci(ae_r['roc_auc'])}")

    results["detection_stats"] = detection_stats
    results["detection_single"] = detection_single
    results["ae_detection"] = ae_detection_stats
    results["n_seeds"] = n_seeds
    results["n_seeds_ae"] = n_seeds_ae

    # ===================== Phase 5: Repair Detection (multi-seed) ==============
    print("\n--- Phase 5: Repair Method Detection Comparison (multi-seed) ---")
    repair_detection = OrderedDict()      # PCA (multi-seed)
    repair_detection_ae = OrderedDict()   # AE (multi-seed subset)

    # PCA: full matrix × n_seeds_ae seeds (still PCA, inexpensive)
    for method_name, method_fn in repair_methods.items():
        for defect in ["missing_20pct", "noise_5dB", "spikes_0.5pct"]:
            if defect not in degraded_groups:
                continue
            f1s, aucs = [], []
            # Use different degradation seeds so that repair is evaluated
            # across independent realisations of the defect process.
            degrade_fn_rep = _make_degrade_fn(defect, healthy_end=fracture_idx)
            for seed in STAT_SEEDS[:n_seeds_ae]:
                try:
                    degraded_s = degrade_fn_rep(all_sensors, seed=seed)
                    repaired_s = method_fn(degraded_s)
                    r = run_detection_with_seed(
                        seed, PCADamageDetector, clean_train,
                        repaired_s.iloc[test_start:], labels[test_start:],
                        window_size, n_components=PCA_N_COMPONENTS
                    )
                    f1s.append(r.get("f1_score", 0))
                    aucs.append(r.get("roc_auc", 0))
                except Exception as e:
                    print(f"    [warn] {method_name}/{defect}/seed={seed}: {e}")
            key = f"{defect}_{method_name}"
            repair_detection[key] = {
                "pca_f1_score": float(np.mean(f1s)) if f1s else 0.0,
                "pca_roc_auc": float(np.mean(aucs)) if aucs else 0.0,
                "pca_f1_std": float(np.std(f1s, ddof=1)) if len(f1s) > 1 else 0.0,
                "pca_auc_std": float(np.std(aucs, ddof=1)) if len(aucs) > 1 else 0.0,
                "pca_f1_array": np.array(f1s),
                "pca_auc_array": np.array(aucs),
            }
            print(f"    PCA {key}: F1={format_with_ci(np.array(f1s))}, "
                  f"AUC={format_with_ci(np.array(aucs))}")

    # AE repair: focused subset (3 top methods on 2 key defects, n_seeds_ae seeds)
    ae_repair_methods = ["moving_average", "median_filter", "comprehensive"]
    ae_repair_defects = ["missing_20pct", "spikes_0.5pct"]
    for method_name in ae_repair_methods:
        method_fn = repair_methods[method_name]
        for defect in ae_repair_defects:
            if defect not in degraded_groups:
                continue
            f1s, aucs = [], []
            degrade_fn_rep = _make_degrade_fn(defect, healthy_end=fracture_idx)
            for seed in STAT_SEEDS[:n_seeds_ae]:
                try:
                    degraded_s = degrade_fn_rep(all_sensors, seed=seed)
                    repaired_s = method_fn(degraded_s)
                    r = run_detection_with_seed(
                        seed, AutoencoderDamageDetector, clean_train,
                        repaired_s.iloc[test_start:], labels[test_start:],
                        window_size,
                        latent_dim=AUTOENCODER_LATENT_DIM,
                        epochs=AUTOENCODER_EPOCHS,
                        batch_size=AUTOENCODER_BATCH_SIZE, lr=AUTOENCODER_LR,
                    )
                    f1s.append(r.get("f1_score", 0))
                    aucs.append(r.get("roc_auc", 0))
                except Exception as e:
                    print(f"    [warn AE] {method_name}/{defect}/seed={seed}: {e}")
            key = f"{defect}_{method_name}"
            repair_detection_ae[key] = {
                "ae_f1_score": float(np.mean(f1s)) if f1s else 0.0,
                "ae_roc_auc": float(np.mean(aucs)) if aucs else 0.0,
                "ae_f1_std": float(np.std(f1s, ddof=1)) if len(f1s) > 1 else 0.0,
                "ae_auc_std": float(np.std(aucs, ddof=1)) if len(aucs) > 1 else 0.0,
            }
            print(f"    AE  {key}: F1={format_with_ci(np.array(f1s))}, "
                  f"AUC={format_with_ci(np.array(aucs))}")

    results["repair_detection"] = repair_detection
    results["repair_detection_ae"] = repair_detection_ae

    # ===================== Phase 6: Statistical Tests =====================
    print("\n--- Phase 6: Statistical Significance Tests ---")
    stat_tests = []

    # PCA baseline vs degraded (F1 AND AUC; bootstrap + paired tests)
    pca_baseline_f1 = detection_stats["baseline"]["f1_score"]
    pca_baseline_auc = detection_stats["baseline"]["roc_auc"]
    for cond in ["missing_20pct", "noise_5dB", "spikes_0.5pct", "drift"]:
        if cond not in detection_stats:
            continue
        for metric, base_vals in [("F1", pca_baseline_f1),
                                  ("AUC", pca_baseline_auc)]:
            comp_vals = detection_stats[cond][
                "f1_score" if metric == "F1" else "roc_auc"]
            tr = paired_test(base_vals, comp_vals)
            b_mean, b_lo, b_hi = bootstrap_ci(comp_vals)
            print(f"  PCA[{metric}] Baseline vs {cond}: "
                  f"p={tr['p_value']:.4f}, d={tr['cohens_d']:.3f}, "
                  f"significant={tr['significant']}")
            stat_tests.append({
                "detector": "PCA",
                "metric": metric,
                "comparison": f"baseline vs {cond}",
                "condition_mean": float(np.mean(comp_vals)),
                "condition_ci_lo": b_lo,
                "condition_ci_hi": b_hi,
                **tr,
            })

    # AE baseline vs degraded on key conditions
    if "baseline" in ae_detection_stats:
        ae_baseline_f1 = ae_detection_stats["baseline"]["f1_score"]
        ae_baseline_auc = ae_detection_stats["baseline"]["roc_auc"]
        for cond in ["missing_20pct", "noise_5dB"]:
            if cond not in ae_detection_stats:
                continue
            for metric, base_vals in [("F1", ae_baseline_f1),
                                      ("AUC", ae_baseline_auc)]:
                comp_vals = ae_detection_stats[cond][
                    "f1_score" if metric == "F1" else "roc_auc"]
                tr = paired_test(base_vals, comp_vals)
                b_mean, b_lo, b_hi = bootstrap_ci(comp_vals)
                print(f"  AE [{metric}] Baseline vs {cond}: "
                      f"p={tr['p_value']:.4f}, d={tr['cohens_d']:.3f}, "
                      f"significant={tr['significant']}")
                stat_tests.append({
                    "detector": "AE",
                    "metric": metric,
                    "comparison": f"baseline vs {cond}",
                    "condition_mean": float(np.mean(comp_vals)),
                    "condition_ci_lo": b_lo,
                    "condition_ci_hi": b_hi,
                    **tr,
                })

    results["stat_tests"] = stat_tests

    # ===================== Phase 7: Weight Sensitivity =====================
    print("\n--- Phase 7: DQA Weight Sensitivity Analysis ---")

    comp = baseline_metrics["completeness"]
    acc = baseline_metrics["accuracy"]
    con = baseline_metrics["consistency"]
    snr_s = baseline_metrics["snr_score"]

    # Entropy-based objective weights
    entropy_weights, ewm_matrix = compute_entropy_weights(comp, acc, con, snr_s)
    print(f"  Entropy weights (data-driven): {tuple(f'{w:.4f}' for w in entropy_weights)}")
    results["entropy_weights"] = entropy_weights

    all_weight_sets = [entropy_weights] + list(WEIGHT_GRID)
    weight_labels = ["Entropy (data-driven)"] + [
        f"Expert ({', '.join(f'{w:.2f}' for w in wt)})" for wt in WEIGHT_GRID
    ]

    weight_results = []
    score_matrix = []
    for label, weights in zip(weight_labels, all_weight_sets):
        score = compute_composite_quality_score(comp, acc, con, snr_s, weights=weights)
        avg = score.mean()
        weight_results.append({
            "method": label,
            "weights": f"({', '.join(f'{w:.3f}' for w in weights)})",
            "mean_score": avg,
            "std_score": score.std(),
        })
        score_matrix.append(np.asarray(score))
        print(f"  {label}: mean composite = {avg:.2f}")

    results["weight_sensitivity"] = pd.DataFrame(weight_results)
    results["weight_sensitivity"].to_csv(
        os.path.join(TABLES_DIR, "weight_sensitivity.csv"), index=False
    )

    # Rank-stability analysis: Spearman / Kendall across all weighting schemes
    score_matrix = np.array(score_matrix).T  # (n_sensors, n_schemes)
    rank_corr = spearman_kendall(score_matrix)
    # Report upper-triangle mean (excluding diagonal) as summary
    n_sch = score_matrix.shape[1]
    iu = np.triu_indices(n_sch, k=1)
    rank_summary = pd.DataFrame({
        "scheme_i": [weight_labels[i] for i in iu[0]],
        "scheme_j": [weight_labels[j] for j in iu[1]],
        "spearman_rho": rank_corr["spearman"][iu],
        "kendall_tau": rank_corr["kendall"][iu],
    })
    rank_summary.to_csv(
        os.path.join(TABLES_DIR, "weight_rank_stability.csv"), index=False
    )
    print(f"  Mean Spearman rho across schemes = "
          f"{rank_summary['spearman_rho'].mean():.3f}")
    print(f"  Mean Kendall tau  across schemes = "
          f"{rank_summary['kendall_tau'].mean():.3f}")
    results["rank_stability"] = rank_summary

    # Store experiment parameters for reporting
    results["params"] = {
        "window_size": window_size,
        "train_end": train_end,
        "test_start": test_start,
        "n_seeds": n_seeds,
        "all_sensors_shape": all_sensors.shape,
        "fs": fs,
    }
    results["all_sensors"] = all_sensors
    results["labels"] = labels
    results["fracture_idx"] = fracture_idx

    return results


# =============================================================================
def run_z24_experiments(z24_data: dict) -> dict:
    """Run all experiments on Z-24 Bridge data."""
    print_header("Z-24 BRIDGE EXPERIMENTS")
    results = {}

    all_sensors = z24_data["acceleration"]
    labels = z24_data["labels"]
    damage_idx = z24_data["damage_idx"]
    fs = z24_data["fs"]
    segment_len = z24_data["segment_length"]

    # Use first N healthy segments for training, rest for testing
    n_sensors = all_sensors.shape[1]
    window_size = min(segment_len, 500)

    # Select subset of sensors for manageable computation
    n_use_sensors = min(n_sensors, 14)
    use_cols = all_sensors.columns[:n_use_sensors]
    all_sensors_sub = all_sensors[use_cols].copy()

    print(f"  Data shape: {all_sensors_sub.shape}")
    print(f"  Sensors used: {n_use_sensors}/{n_sensors}")
    print(f"  Window size: {window_size}")

    train_end = int(damage_idx * 0.67)
    test_start = train_end
    clean_train = all_sensors_sub.iloc[:train_end]

    print(f"  Training samples: {train_end}")
    print(f"  Test samples: {len(all_sensors_sub) - test_start}")
    print(f"  Damage idx: {damage_idx}")

    # Baseline DQA
    print("\n--- Z-24 Baseline DQA ---")
    baseline_metrics = full_quality_assessment(all_sensors_sub, fs=fs)
    results["baseline_metrics"] = baseline_metrics

    # Degradation + Detection
    print("\n--- Z-24 Degradation + Detection ---")
    degraded_groups = create_all_degraded_datasets(all_sensors_sub,
                                                   healthy_end=damage_idx)
    z24_detection = OrderedDict()

    n_seeds = N_REPEAT_SEEDS
    try:
        from src.config import N_REPEAT_SEEDS_AE
    except ImportError:
        N_REPEAT_SEEDS_AE = 10
    n_seeds_ae = min(N_REPEAT_SEEDS_AE, n_seeds)
    z24_detection_stats = OrderedDict()
    z24_ae_detection_stats = OrderedDict()

    # Baseline
    baseline_r = run_detection_with_seed(
        RANDOM_SEED, PCADamageDetector, clean_train,
        all_sensors_sub.iloc[test_start:], labels[test_start:],
        window_size, n_components=min(PCA_N_COMPONENTS, n_use_sensors - 1)
    )
    z24_detection["baseline"] = baseline_r
    z24_detection_stats["baseline"] = {
        "f1_score": np.array([baseline_r.get("f1_score", 0)] * n_seeds),
        "roc_auc": np.array([baseline_r.get("roc_auc", 0)] * n_seeds),
    }
    print(f"  Baseline: F1={baseline_r.get('f1_score',0):.4f}, "
          f"AUC={baseline_r.get('roc_auc',0):.4f}")

    def _z24_degrade_fn(defect_name, healthy_end=None):
        if defect_name.startswith("missing"):
            rate = int(defect_name.split("_")[1].replace("pct", "")) / 100
            return lambda d, seed: inject_random_missing(d, rate, seed=seed)
        if defect_name.startswith("noise"):
            snr = int(defect_name.split("_")[1].replace("dB", ""))
            return lambda d, seed, s=snr: inject_gaussian_noise(d, s, seed=seed)
        if defect_name == "spikes_0.5pct":
            return lambda d, seed: inject_spikes(d, spike_rate=0.005, seed=seed)
        if defect_name == "drift":
            return lambda d, seed, he=healthy_end: inject_drift(
                d, drift_magnitude=0.5, seed=seed, healthy_end=he)
        return None

    for defect_name in ["missing_5pct", "missing_10pct", "missing_20pct",
                        "noise_20dB", "noise_10dB", "noise_5dB",
                        "spikes_0.5pct", "drift"]:
        degrade_fn = _z24_degrade_fn(defect_name, healthy_end=damage_idx)
        if degrade_fn is None:
            continue

        stats_r = run_repeated_detection(
            n_seeds, PCADamageDetector, clean_train, all_sensors_sub,
            labels, test_start, window_size,
            degrade_fn=degrade_fn,
            n_components=min(PCA_N_COMPONENTS, n_use_sensors - 1)
        )
        z24_detection_stats[defect_name] = stats_r
        f1_str = format_with_ci(stats_r['f1_score'])
        print(f"  Z-24 [{defect_name}]: F1={f1_str}")

        # Single run for table
        if defect_name in degraded_groups:
            r = run_detection_with_seed(
                RANDOM_SEED, PCADamageDetector, clean_train,
                degraded_groups[defect_name].iloc[test_start:],
                labels[test_start:], window_size,
                n_components=min(PCA_N_COMPONENTS, n_use_sensors - 1)
            )
            z24_detection[defect_name] = r

    # Z-24 AE on 3 key conditions (baseline + missing_20pct + noise_5dB)
    print(f"\n--- Z-24 Autoencoder ({n_seeds_ae} seeds on key conditions) ---")
    for defect_name in ["baseline", "missing_20pct", "noise_5dB"]:
        degrade_fn = (None if defect_name == "baseline"
                      else _z24_degrade_fn(defect_name, healthy_end=damage_idx))
        ae_r = run_repeated_detection(
            n_seeds_ae, AutoencoderDamageDetector, clean_train, all_sensors_sub,
            labels, test_start, window_size,
            degrade_fn=degrade_fn,
            latent_dim=AUTOENCODER_LATENT_DIM, epochs=AUTOENCODER_EPOCHS,
            batch_size=AUTOENCODER_BATCH_SIZE, lr=AUTOENCODER_LR
        )
        z24_ae_detection_stats[defect_name] = ae_r
        print(f"  Z-24 AE [{defect_name}]: F1={format_with_ci(ae_r['f1_score'])}")

    # Repair on Z-24
    print("\n--- Z-24 Repair Experiments ---")
    repair_methods = get_all_repair_methods()
    z24_repair_detection = OrderedDict()
    for method_name, method_fn in repair_methods.items():
        for defect in ["missing_20pct", "noise_5dB"]:
            if defect not in degraded_groups:
                continue
            repaired = method_fn(degraded_groups[defect])
            r = run_detection_with_seed(
                RANDOM_SEED, PCADamageDetector, clean_train,
                repaired.iloc[test_start:], labels[test_start:],
                window_size, n_components=min(PCA_N_COMPONENTS, n_use_sensors - 1)
            )
            key = f"{defect}_{method_name}"
            z24_repair_detection[key] = {
                "pca_f1_score": r.get("f1_score", 0),
                "pca_roc_auc": r.get("roc_auc", 0),
            }
            print(f"    Z-24 {key}: F1={r.get('f1_score',0):.4f}")

    # Z-24 DQA radar
    z24_group_metrics = {}
    for name in ["baseline", "missing_20pct", "noise_5dB"]:
        if name in degraded_groups:
            z24_group_metrics[name] = full_quality_assessment(
                degraded_groups[name], fs=fs
            )
    z24_group_metrics["baseline"] = baseline_metrics

    results["detection"] = z24_detection
    results["detection_stats"] = z24_detection_stats
    results["ae_detection_stats"] = z24_ae_detection_stats
    results["repair_detection"] = z24_repair_detection
    results["group_metrics"] = z24_group_metrics
    results["all_sensors"] = all_sensors_sub
    results["labels"] = labels
    results["degraded_groups"] = degraded_groups
    results["n_seeds"] = n_seeds
    results["n_seeds_ae"] = n_seeds_ae

    # Save
    det_df = pd.DataFrame({k: {
        "pca_f1": v.get("f1_score", 0),
        "pca_auc": v.get("roc_auc", 0),
        "pca_acc": v.get("accuracy", 0),
    } for k, v in z24_detection.items()}).T
    det_df.to_csv(os.path.join(TABLES_DIR, "z24_detection_results.csv"))

    return results


# =============================================================================
def generate_all_figures(vb_results: dict, z24_results: dict):
    """Generate all publication-quality figures."""
    print_header("GENERATING PUBLICATION-QUALITY FIGURES")

    # ---- Vänersborg Figures ----
    all_sensors = vb_results["all_sensors"]
    labels = vb_results["labels"]
    fracture_idx = vb_results["fracture_idx"]
    degraded = vb_results["degraded_groups"]
    group_metrics = vb_results["all_group_metrics"]
    composite_scores = vb_results["all_composite_scores"]
    det_single = vb_results["detection_single"]
    repair_det = vb_results["repair_detection"]
    repaired = vb_results["repaired_datasets"]

    # Fig 1: Missing heatmap
    print("[Fig 1] Missing Data Heatmap...")
    if "missing_20pct" in degraded:
        plot_missing_heatmap(
            degraded["missing_20pct"],
            title="Data Completeness Heatmap - Vanersborg Bridge (20% Missing)",
            save_name="fig1_missing_heatmap.png"
        )

    # Fig 2: Time-series overlay
    print("[Fig 2] Time-series Comparison...")
    sensor_col = all_sensors.columns[0]
    degraded_ts = degraded.get("missing_20pct", all_sensors)
    li_key = f"missing_20pct_linear_interp"
    repaired_ts = repaired.get(li_key, all_sensors)
    plot_timeseries_comparison(
        all_sensors[sensor_col],
        degraded_ts[sensor_col],
        repaired_ts[sensor_col],
        sensor_name=sensor_col,
        start_idx=max(0, fracture_idx - 1500),
        length=3000,
        save_name="fig2_timeseries_overlay.png"
    )

    # Fig 3: Bridge quality map
    print("[Fig 3] Bridge Quality Map...")
    plot_bridge_quality_map(
        vb_results["baseline_metrics"]["composite_score"],
        bridge_name="Vanersborg Bridge",
        save_name="fig3_bridge_quality_map_baseline.png"
    )
    if "missing_20pct" in group_metrics:
        plot_bridge_quality_map(
            group_metrics["missing_20pct"]["composite_score"],
            bridge_name="Vanersborg Bridge (20% Missing)",
            save_name="fig3b_bridge_quality_map_degraded.png"
        )

    # Fig 4: Degradation curves with error bars
    print("[Fig 4] Degradation Curves...")
    det_stats = vb_results["detection_stats"]
    # Build results dict for the existing plot function
    det_for_plot = OrderedDict()
    ae_stats_plot = vb_results.get("ae_detection", {})
    for key, st in det_stats.items():
        ae_f1 = ae_stats_plot.get(key, {}).get("f1_score", 0)
        ae_auc = ae_stats_plot.get(key, {}).get("roc_auc", 0)
        det_for_plot[key] = {
            "pca_f1_score": float(np.mean(st["f1_score"])),
            "pca_roc_auc": float(np.mean(st["roc_auc"])),
            "ae_f1_score": float(np.mean(ae_f1)) if hasattr(ae_f1, "__len__") else float(ae_f1),
            "ae_roc_auc": float(np.mean(ae_auc)) if hasattr(ae_auc, "__len__") else float(ae_auc),
        }
    # Add repair results
    for key, val in repair_det.items():
        if "linear_interp" in key and "missing_20pct" in key:
            det_for_plot["missing_20pct_linear_interp"] = val

    plot_degradation_curves(det_for_plot, metric_name="f1_score",
                           save_name="fig4a_degradation_f1.png")
    plot_degradation_curves(det_for_plot, metric_name="roc_auc",
                           save_name="fig4b_degradation_auc.png")

    # Fig 5: ROC curves
    print("[Fig 5] ROC Curves...")
    roc_data = OrderedDict()
    for key, r in det_single.items():
        if "fpr" in r:
            roc_data[f"{key} (PCA)"] = {
                "fpr": r["fpr"], "tpr": r["tpr"],
                "roc_auc": r.get("roc_auc", 0)
            }
    if roc_data:
        plot_roc_curves(roc_data, save_name="fig5_roc_curves.png")

    # Fig 6: Confusion matrices
    print("[Fig 6] Confusion Matrices...")
    cm_data = OrderedDict()
    cm_titles = {
        "baseline": "Baseline",
        "missing_20pct": "Missing 20%",
        "noise_5dB": "Noise 5 dB",
    }
    for key in ["baseline", "missing_20pct", "noise_5dB"]:
        if key in det_single and "confusion_matrix" in det_single[key]:
            cm_data[cm_titles.get(key, key)] = det_single[key]["confusion_matrix"]
    if cm_data:
        plot_confusion_matrices(cm_data, save_name="fig6_confusion_matrices.png")

    # Fig 7: DQA radar
    print("[Fig 7] DQA Radar...")
    radar_data = OrderedDict()
    for key in ["baseline", "missing_20pct", "noise_5dB"]:
        if key in group_metrics:
            radar_data[key] = group_metrics[key]
    if li_key in repaired:
        rep_met = full_quality_assessment(repaired[li_key], fs=vb_results["params"]["fs"])
        radar_data["Repaired"] = rep_met
    if radar_data:
        plot_dqa_radar(radar_data, sensor_name=all_sensors.columns[0],
                      save_name="fig7_dqa_radar.png")

    # Fig 8: Quality boxplot
    print("[Fig 8] Quality Boxplots...")
    boxplot_scores = OrderedDict()
    for key in ["baseline", "missing_5pct", "missing_10pct", "missing_20pct",
                "noise_20dB", "noise_10dB", "noise_5dB"]:
        if key in composite_scores:
            boxplot_scores[key] = composite_scores[key]
    if boxplot_scores:
        plot_quality_boxplot(boxplot_scores, save_name="fig8_quality_boxplot.png")

    # Fig 9: Repair comparison (complete matrix)
    print("[Fig 9] Repair Method Comparison...")
    repair_for_plot = OrderedDict()
    repair_for_plot["No Repair"] = det_for_plot.get("missing_20pct", {})
    for method_name in get_all_repair_methods():
        key = f"missing_20pct_{method_name}"
        if key in repair_det:
            label = method_name.replace("_", " ").title()
            repair_for_plot[label] = repair_det[key]
    if repair_for_plot:
        plot_repair_comparison_bar(repair_for_plot, metric="f1_score",
                                  save_name="fig9_repair_comparison_f1.png")
        plot_repair_comparison_bar(repair_for_plot, metric="roc_auc",
                                  save_name="fig9b_repair_comparison_auc.png")

    # ---- Z-24 Figures ----
    print("\n[Fig 10] Z-24 DQA Radar...")
    if z24_results and "group_metrics" in z24_results:
        z24_gm = z24_results["group_metrics"]
        z24_sensor = z24_results["all_sensors"].columns[0]
        plot_dqa_radar(z24_gm, sensor_name=z24_sensor,
                      save_name="fig10_z24_dqa_radar.png")


# =============================================================================
def _save_z24_only(z24_results: dict):
    """Write only the Z-24 tables. Used for partial-run checkpoints."""
    z24_rows = []
    for cond, st in z24_results["detection_stats"].items():
        f1_mean, f1_lo, f1_hi = bootstrap_ci(st["f1_score"])
        auc_mean, auc_lo, auc_hi = bootstrap_ci(st["roc_auc"])
        z24_rows.append({
            "Condition": cond,
            "F1 (mean±std)": format_with_ci(st["f1_score"]),
            "AUC (mean±std)": format_with_ci(st["roc_auc"]),
            "F1_CI95": f"[{f1_lo:.4f}, {f1_hi:.4f}]",
            "AUC_CI95": f"[{auc_lo:.4f}, {auc_hi:.4f}]",
            "F1_mean": f1_mean,
            "AUC_mean": auc_mean,
            "n_seeds": len(st["f1_score"]),
        })
    pd.DataFrame(z24_rows).to_csv(
        os.path.join(TABLES_DIR, "z24_detection_with_ci.csv"), index=False)
    print(f"  Saved z24_detection_with_ci.csv (z24-only checkpoint)")
    if "ae_detection_stats" in z24_results:
        z24_ae_rows = []
        for cond, st in z24_results["ae_detection_stats"].items():
            f1_mean, f1_lo, f1_hi = bootstrap_ci(st["f1_score"])
            auc_mean, auc_lo, auc_hi = bootstrap_ci(st["roc_auc"])
            z24_ae_rows.append({
                "Condition": cond,
                "F1 (mean±std)": format_with_ci(st["f1_score"]),
                "AUC (mean±std)": format_with_ci(st["roc_auc"]),
                "F1_CI95": f"[{f1_lo:.4f}, {f1_hi:.4f}]",
                "AUC_CI95": f"[{auc_lo:.4f}, {auc_hi:.4f}]",
                "n_seeds": len(st["f1_score"]),
            })
        pd.DataFrame(z24_ae_rows).to_csv(
            os.path.join(TABLES_DIR, "z24_ae_detection_with_ci.csv"), index=False)
        print(f"  Saved z24_ae_detection_with_ci.csv (z24-only checkpoint)")


def save_results_tables(vb_results: dict, z24_results: dict):
    """Save comprehensive results tables for the paper.

    Both arguments accept an empty dict so that a partial run can still
    commit whichever bridge's tables finished before a later failure.
    """
    print_header("SAVING RESULTS TABLES")

    if not vb_results:
        # Z-24-only checkpoint: skip V-bridge tables but still write Z-24.
        if z24_results and "detection_stats" in z24_results:
            _save_z24_only(z24_results)
        return

    # Table: Detection (PCA) with mean ± std and 95% bootstrap CI
    det_stats = vb_results["detection_stats"]
    rows = []
    for cond, st in det_stats.items():
        f1_mean, f1_lo, f1_hi = bootstrap_ci(st["f1_score"])
        auc_mean, auc_lo, auc_hi = bootstrap_ci(st["roc_auc"])
        rows.append({
            "Condition": cond,
            "F1 (mean±std)": format_with_ci(st["f1_score"]),
            "AUC (mean±std)": format_with_ci(st["roc_auc"]),
            "F1_CI95": f"[{f1_lo:.4f}, {f1_hi:.4f}]",
            "AUC_CI95": f"[{auc_lo:.4f}, {auc_hi:.4f}]",
            "F1_mean": f1_mean,
            "F1_std": np.std(st["f1_score"], ddof=1) if len(st["f1_score"]) > 1 else 0.0,
            "AUC_mean": auc_mean,
            "AUC_std": np.std(st["roc_auc"], ddof=1) if len(st["roc_auc"]) > 1 else 0.0,
            "n_seeds": len(st["f1_score"]),
        })
    det_table = pd.DataFrame(rows)
    det_table.to_csv(os.path.join(TABLES_DIR, "detection_with_ci.csv"), index=False)
    print(f"  Saved detection_with_ci.csv (with 95% bootstrap CI)")

    # Table: AE Detection with CI
    ae_stats = vb_results.get("ae_detection", {})
    if ae_stats:
        ae_rows = []
        for cond, st in ae_stats.items():
            f1_mean, f1_lo, f1_hi = bootstrap_ci(st["f1_score"])
            auc_mean, auc_lo, auc_hi = bootstrap_ci(st["roc_auc"])
            ae_rows.append({
                "Condition": cond,
                "F1 (mean±std)": format_with_ci(st["f1_score"]),
                "AUC (mean±std)": format_with_ci(st["roc_auc"]),
                "F1_CI95": f"[{f1_lo:.4f}, {f1_hi:.4f}]",
                "AUC_CI95": f"[{auc_lo:.4f}, {auc_hi:.4f}]",
                "F1_mean": f1_mean,
                "F1_std": np.std(st["f1_score"], ddof=1) if len(st["f1_score"]) > 1 else 0.0,
                "AUC_mean": auc_mean,
                "AUC_std": np.std(st["roc_auc"], ddof=1) if len(st["roc_auc"]) > 1 else 0.0,
                "n_seeds": len(st["f1_score"]),
            })
        pd.DataFrame(ae_rows).to_csv(
            os.path.join(TABLES_DIR, "ae_detection_with_ci.csv"), index=False)
        print(f"  Saved ae_detection_with_ci.csv")

    # Table: Complete repair matrix with CI (PCA + AE subset)
    repair_det = vb_results["repair_detection"]
    if repair_det:
        repair_rows = []
        for key, val in repair_det.items():
            parts = key.split("_", 2)
            defect = "_".join(parts[:2]) if len(parts) > 2 else parts[0]
            method = "_".join(parts[2:]) if len(parts) > 2 else ""
            f1_arr = val.get("pca_f1_array", np.array([val.get("pca_f1_score", 0)]))
            auc_arr = val.get("pca_auc_array", np.array([val.get("pca_roc_auc", 0)]))
            f1_mean, f1_lo, f1_hi = bootstrap_ci(f1_arr)
            auc_mean, auc_lo, auc_hi = bootstrap_ci(auc_arr)
            repair_rows.append({
                "Detector": "PCA",
                "Defect": defect,
                "Method": method,
                "F1": f1_mean,
                "F1_std": val.get("pca_f1_std", 0.0),
                "F1_CI95": f"[{f1_lo:.4f}, {f1_hi:.4f}]",
                "AUC": auc_mean,
                "AUC_std": val.get("pca_auc_std", 0.0),
                "AUC_CI95": f"[{auc_lo:.4f}, {auc_hi:.4f}]",
                "n_seeds": len(f1_arr),
            })
        for key, val in vb_results.get("repair_detection_ae", {}).items():
            parts = key.split("_", 2)
            defect = "_".join(parts[:2]) if len(parts) > 2 else parts[0]
            method = "_".join(parts[2:]) if len(parts) > 2 else ""
            repair_rows.append({
                "Detector": "AE",
                "Defect": defect,
                "Method": method,
                "F1": val.get("ae_f1_score", 0),
                "F1_std": val.get("ae_f1_std", 0.0),
                "F1_CI95": "",
                "AUC": val.get("ae_roc_auc", 0),
                "AUC_std": val.get("ae_auc_std", 0.0),
                "AUC_CI95": "",
                "n_seeds": vb_results.get("n_seeds_ae", 0),
            })
        repair_table = pd.DataFrame(repair_rows)
        repair_table.to_csv(os.path.join(TABLES_DIR, "repair_matrix.csv"), index=False)
        print(f"\n  Saved repair_matrix.csv (PCA multi-seed + AE subset)")

    # Table: Statistical tests
    if vb_results["stat_tests"]:
        stat_df = pd.DataFrame(vb_results["stat_tests"])
        stat_df.to_csv(os.path.join(TABLES_DIR, "statistical_tests.csv"), index=False)
        print(f"\n  Saved statistical_tests.csv")

    # Z-24 results with bootstrap CI
    if z24_results and "detection_stats" in z24_results:
        z24_rows = []
        for cond, st in z24_results["detection_stats"].items():
            f1_mean, f1_lo, f1_hi = bootstrap_ci(st["f1_score"])
            auc_mean, auc_lo, auc_hi = bootstrap_ci(st["roc_auc"])
            z24_rows.append({
                "Condition": cond,
                "F1 (mean±std)": format_with_ci(st["f1_score"]),
                "AUC (mean±std)": format_with_ci(st["roc_auc"]),
                "F1_CI95": f"[{f1_lo:.4f}, {f1_hi:.4f}]",
                "AUC_CI95": f"[{auc_lo:.4f}, {auc_hi:.4f}]",
                "F1_mean": f1_mean,
                "AUC_mean": auc_mean,
                "n_seeds": len(st["f1_score"]),
            })
        z24_table = pd.DataFrame(z24_rows)
        z24_table.to_csv(os.path.join(TABLES_DIR, "z24_detection_with_ci.csv"), index=False)
        print(f"\n  Saved z24_detection_with_ci.csv")

        # Z-24 AE
        if "ae_detection_stats" in z24_results:
            z24_ae_rows = []
            for cond, st in z24_results["ae_detection_stats"].items():
                f1_mean, f1_lo, f1_hi = bootstrap_ci(st["f1_score"])
                auc_mean, auc_lo, auc_hi = bootstrap_ci(st["roc_auc"])
                z24_ae_rows.append({
                    "Condition": cond,
                    "F1 (mean±std)": format_with_ci(st["f1_score"]),
                    "AUC (mean±std)": format_with_ci(st["roc_auc"]),
                    "F1_CI95": f"[{f1_lo:.4f}, {f1_hi:.4f}]",
                    "AUC_CI95": f"[{auc_lo:.4f}, {auc_hi:.4f}]",
                    "n_seeds": len(st["f1_score"]),
                })
            pd.DataFrame(z24_ae_rows).to_csv(
                os.path.join(TABLES_DIR, "z24_ae_detection_with_ci.csv"), index=False)
            print(f"  Saved z24_ae_detection_with_ci.csv")


# =============================================================================
def main():
    total_start = time.time()

    # Check data availability
    avail = check_data_availability()
    print_header("DATA AVAILABILITY CHECK")
    for k, v in avail.items():
        status = "AVAILABLE" if v else "NOT FOUND"
        print(f"  {k}: {status}")

    if not avail["vanersborg"] and not avail["z24"]:
        print("\n[ERROR] No real datasets available!")
        print("Please run: python download_data.py")
        print("Or wait for the current download to complete.")
        return

    # Run experiments — save tables incrementally after each bridge so
    # that a later failure does not destroy earlier results.
    vb_results = None
    z24_results = None

    if avail["vanersborg"]:
        try:
            vb_data = load_vanersborg_data(max_events=40)
            vb_results = run_vanersborg_experiments(vb_data)
            print_header("SAVING VÄNERSBORG RESULT TABLES (checkpoint)")
            save_results_tables(vb_results, {})
        except Exception as e:
            print(f"[ERROR] Vanersborg experiment failed: {e}")
            import traceback
            traceback.print_exc()

    if avail["z24"]:
        try:
            z24_data = load_z24_data(max_segments=600)
            z24_results = run_z24_experiments(z24_data)
            print_header("SAVING Z-24 RESULT TABLES (checkpoint)")
            save_results_tables(vb_results or {}, z24_results)
        except Exception as e:
            print(f"[ERROR] Z-24 experiment failed: {e}")
            import traceback
            traceback.print_exc()

    # Figure regeneration is last because it's the most fragile step.
    if vb_results:
        try:
            generate_all_figures(vb_results, z24_results or {})
        except Exception as _fig_err:
            import traceback
            print(f"[WARN] Figure generation failed: {_fig_err}")
            traceback.print_exc()

    # Summary
    elapsed = time.time() - total_start
    print_header("EXPERIMENT COMPLETE")
    print(f"Total execution time: {elapsed:.1f} seconds ({elapsed/60:.1f} min)")
    print(f"Figures saved to: {FIGURES_DIR}")
    print(f"Tables saved to:  {TABLES_DIR}")

    if vb_results:
        det_stats = vb_results["detection_stats"]
        print("\n--- KEY FINDINGS ---")
        if "baseline" in det_stats and "missing_20pct" in det_stats:
            bl_f1 = np.mean(det_stats["baseline"]["f1_score"])
            m20_f1 = np.mean(det_stats["missing_20pct"]["f1_score"])
            drop = (bl_f1 - m20_f1) / max(bl_f1, 1e-10) * 100
            print(f"1. 20% missing data: F1 drops {drop:.1f}% "
                  f"({bl_f1:.4f} -> {format_with_ci(det_stats['missing_20pct']['f1_score'])})")
        if "baseline" in det_stats and "noise_5dB" in det_stats:
            bl_f1 = np.mean(det_stats["baseline"]["f1_score"])
            n5_f1 = np.mean(det_stats["noise_5dB"]["f1_score"])
            drop = (bl_f1 - n5_f1) / max(bl_f1, 1e-10) * 100
            print(f"2. SNR=5dB noise: F1 drops {drop:.1f}% "
                  f"({bl_f1:.4f} -> {format_with_ci(det_stats['noise_5dB']['f1_score'])})")


if __name__ == "__main__":
    main()
