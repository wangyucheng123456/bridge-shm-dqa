"""
=============================================================================
Reviewer-Response Experiments (new work on top of the original manuscript)
=============================================================================
Addresses five reviewer questions on the Vanersborg Bridge case study:

  1. F1 threshold / data leakage
     -> reports BOTH the leakage-free fixed-threshold F1 (95th percentile of
        the healthy training reconstruction/anomaly score) AND the old
        test-set-optimised F1, so the optimistic bias can be quantified.

  2. Wilcoxon signed-rank test
     -> for every detector and condition we now run the non-parametric
        Wilcoxon test alongside the paired t-test and SAVE the raw per-seed
        arrays so the tests are fully reproducible.

  3. Additional baselines
     -> Isolation Forest, One-Class SVM and an LSTM autoencoder are added and
        evaluated with the identical protocol.

  5. Window-label threshold sensitivity
     -> the damaged-fraction threshold is swept over {0.2, 0.3, 0.4, 0.5}.

All outputs are written to results/tables/ (CSV + JSON) and
results/tables/reviewer_raw/ (per-seed .npy).
=============================================================================
"""
import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

from src.config import (
    TABLES_DIR, RANDOM_SEED, STAT_SEEDS, PCA_N_COMPONENTS,
    AUTOENCODER_LATENT_DIM, AUTOENCODER_EPOCHS,
    AUTOENCODER_BATCH_SIZE, AUTOENCODER_LR,
)
from src.data_loader import load_vanersborg_data
from src.data_degradation import (
    inject_random_missing, inject_gaussian_noise, inject_spikes, inject_drift,
)
from src.damage_detection import (
    PCADamageDetector, AutoencoderDamageDetector,
    IsolationForestDetector, OneClassSVMDetector, LSTMAutoencoderDetector,
    make_window_labels, evaluate_detection,
)
from src.statistical import paired_test, bootstrap_ci

RAW_DIR = os.path.join(TABLES_DIR, "reviewer_raw")
os.makedirs(RAW_DIR, exist_ok=True)

# --- Experiment scope (kept modest so the whole thing runs in a few minutes) ---
CHEAP_SEEDS = 10          # PCA / IsolationForest / OneClassSVM
AE_SEEDS = 10             # dense autoencoder (already in the paper)
LSTM_SEEDS = 5            # LSTM autoencoder (expensive on CPU)
CONDITIONS = ["baseline", "missing_20pct", "noise_5dB", "spikes_0.5pct", "drift"]
LSTM_CONDITIONS = ["baseline", "missing_20pct", "noise_5dB"]
WINDOW_THRESHOLDS = [0.2, 0.3, 0.4, 0.5]


def log(msg):
    print(msg, flush=True)


def make_degrade_fn(name, healthy_end):
    if name == "baseline":
        return None
    if name.startswith("missing"):
        rate = int(name.split("_")[1].replace("pct", "")) / 100
        return lambda d, seed: inject_random_missing(d, rate, seed=seed)
    if name.startswith("noise"):
        snr = int(name.split("_")[1].replace("dB", ""))
        return lambda d, seed, s=snr: inject_gaussian_noise(d, s, seed=seed)
    if name == "spikes_0.5pct":
        return lambda d, seed: inject_spikes(d, spike_rate=0.005, seed=seed)
    if name == "drift":
        return lambda d, seed, he=healthy_end: inject_drift(
            d, drift_magnitude=0.5, seed=seed, healthy_end=he)
    return None


def build_detector(name, seed):
    """Detector factory. Stochastic detectors receive the seed so that the
    'baseline' condition still shows genuine run-to-run variation."""
    if name == "PCA":
        return PCADamageDetector(n_components=PCA_N_COMPONENTS)
    if name == "IsolationForest":
        return IsolationForestDetector(random_state=seed)
    if name == "OneClassSVM":
        return OneClassSVMDetector()
    if name == "DenseAE":
        import torch
        torch.manual_seed(seed)
        return AutoencoderDamageDetector(
            latent_dim=AUTOENCODER_LATENT_DIM, epochs=AUTOENCODER_EPOCHS,
            batch_size=AUTOENCODER_BATCH_SIZE, lr=AUTOENCODER_LR)
    if name == "LSTM_AE":
        return LSTMAutoencoderDetector(seed=seed)
    raise ValueError(name)


def run_once(det_name, seed, clean_train, all_sensors, labels, test_start,
             window_size, degrade_fn, window_thr=0.3):
    """One detection run. Returns the full evaluate_detection dict."""
    if degrade_fn is not None:
        test_data = degrade_fn(all_sensors, seed=seed).iloc[test_start:]
    else:
        test_data = all_sensors.iloc[test_start:]
    test_labels = labels[test_start:]

    det = build_detector(det_name, seed)
    det.fit(clean_train, window_size=window_size)
    scores, preds = det.predict(test_data, window_size=window_size)
    wlabels = make_window_labels(test_labels, window_size, window_thr)

    m = min(len(wlabels), len(preds))
    return evaluate_detection(wlabels[:m], preds[:m], scores[:m])


def repeat(det_name, n_seeds, conditions, clean_train, all_sensors, labels,
           test_start, window_size):
    """Repeated runs across seeds for each condition. Collects clean
    (fixed-threshold) and leaked (test-optimised) F1, plus AUC/precision/recall."""
    out = {}
    for cond in conditions:
        degrade_fn = make_degrade_fn(cond, healthy_end=None)
        # healthy_end handled by caller-supplied global; re-derive for drift
        rec = {k: [] for k in ["f1_fixed", "f1_opt", "roc_auc",
                                "precision", "recall"]}
        for seed in STAT_SEEDS[:n_seeds]:
            r = run_once(det_name, seed, clean_train, all_sensors, labels,
                         test_start, window_size, degrade_fn)
            rec["f1_fixed"].append(r.get("f1_fixed", 0.0))
            rec["f1_opt"].append(r.get("f1_score", 0.0))
            rec["roc_auc"].append(r.get("roc_auc", 0.0))
            rec["precision"].append(r.get("precision", 0.0))
            rec["recall"].append(r.get("recall", 0.0))
        arr = {k: np.array(v, dtype=float) for k, v in rec.items()}
        out[cond] = arr
        # persist raw arrays
        for k, v in arr.items():
            np.save(os.path.join(RAW_DIR, f"{det_name}__{cond}__{k}.npy"), v)
        log(f"    [{det_name}/{cond}] F1_fixed={arr['f1_fixed'].mean():.4f} "
            f"F1_opt(leaked)={arr['f1_opt'].mean():.4f} "
            f"AUC={arr['roc_auc'].mean():.4f}")
    return out


def fmt(a):
    return f"{np.mean(a):.4f} ± {np.std(a, ddof=1) if len(a) > 1 else 0.0:.4f}"


def main():
    t0 = time.time()
    log("Loading Vanersborg data ...")
    vb = load_vanersborg_data(max_events=40)

    all_sensors = pd.concat([
        vb["acceleration"], vb.get("strain", pd.DataFrame()),
        vb.get("tilt", pd.DataFrame())], axis=1)
    all_sensors = all_sensors.dropna(axis=1, how="all")
    all_sensors = all_sensors.loc[:, all_sensors.nunique() > 1]
    if all_sensors.shape[1] > 10:
        all_sensors = all_sensors.iloc[:, :10]

    fracture_idx = vb["fracture_idx"]
    labels = vb["labels"]

    MAX_SAMPLES = 500000
    if len(all_sensors) > MAX_SAMPLES:
        step = max(1, len(all_sensors) // MAX_SAMPLES)
        all_sensors = all_sensors.iloc[::step].reset_index(drop=True)
        fracture_idx = fracture_idx // step
        labels = labels[::step]

    n_total = len(all_sensors)
    window_size = max(50, min(200, n_total // 100))
    train_end = int(fracture_idx * 0.67)
    test_start = train_end
    clean_train = all_sensors.iloc[:train_end]

    log(f"  shape={all_sensors.shape}, window={window_size}, "
        f"train_end={train_end}, fracture_idx={fracture_idx}")

    # patch make_degrade_fn drift healthy_end via closure global
    global make_degrade_fn
    _orig = make_degrade_fn
    make_degrade_fn = lambda name, healthy_end=fracture_idx: _orig(name, fracture_idx)

    summary = {"params": {
        "dataset": "Vanersborg", "n_samples": int(n_total),
        "window_size": int(window_size), "train_end": int(train_end),
        "fracture_idx": int(fracture_idx),
        "cheap_seeds": CHEAP_SEEDS, "ae_seeds": AE_SEEDS,
        "lstm_seeds": LSTM_SEEDS,
        "fixed_threshold": "95th percentile of healthy-training anomaly score",
    }}

    # ---------------- Part A+C: all detectors, multi-seed ----------------
    log("\n== Detectors x conditions (clean fixed-threshold vs leaked F1) ==")
    detector_specs = [
        ("PCA", CHEAP_SEEDS, CONDITIONS),
        ("IsolationForest", CHEAP_SEEDS, CONDITIONS),
        ("OneClassSVM", CHEAP_SEEDS, CONDITIONS),
        ("DenseAE", AE_SEEDS, CONDITIONS),
        ("LSTM_AE", LSTM_SEEDS, LSTM_CONDITIONS),
    ]
    all_results = {}
    for det_name, n_seeds, conds in detector_specs:
        log(f"  -- {det_name} ({n_seeds} seeds) --")
        all_results[det_name] = repeat(
            det_name, n_seeds, conds, clean_train, all_sensors, labels,
            test_start, window_size)

    # ---- Table: clean vs leaked F1 (quantifies the data-leakage bias) ----
    leak_rows = []
    for det_name, res in all_results.items():
        for cond, arr in res.items():
            leak_rows.append({
                "Detector": det_name, "Condition": cond,
                "F1_fixed_clean": float(arr["f1_fixed"].mean()),
                "F1_fixed_std": float(np.std(arr["f1_fixed"], ddof=1)
                                      if len(arr["f1_fixed"]) > 1 else 0.0),
                "F1_optimal_leaked": float(arr["f1_opt"].mean()),
                "F1_leak_gap": float(arr["f1_opt"].mean()
                                     - arr["f1_fixed"].mean()),
                "AUC": float(arr["roc_auc"].mean()),
                "n_seeds": int(len(arr["f1_fixed"])),
            })
    pd.DataFrame(leak_rows).to_csv(
        os.path.join(TABLES_DIR, "reviewer_clean_vs_leaked_f1.csv"), index=False)
    summary["clean_vs_leaked"] = leak_rows
    log("  saved reviewer_clean_vs_leaked_f1.csv")

    # ---- Table: multi-baseline detection (fixed-threshold, honest) ----
    base_rows = []
    for det_name, res in all_results.items():
        for cond, arr in res.items():
            f1_m, f1_lo, f1_hi = bootstrap_ci(arr["f1_fixed"])
            auc_m, auc_lo, auc_hi = bootstrap_ci(arr["roc_auc"])
            base_rows.append({
                "Detector": det_name, "Condition": cond,
                "F1 (fixed)": fmt(arr["f1_fixed"]),
                "F1_CI95": f"[{f1_lo:.4f}, {f1_hi:.4f}]",
                "AUC": fmt(arr["roc_auc"]),
                "AUC_CI95": f"[{auc_lo:.4f}, {auc_hi:.4f}]",
                "Precision": fmt(arr["precision"]),
                "Recall": fmt(arr["recall"]),
                "n_seeds": int(len(arr["f1_fixed"])),
            })
    pd.DataFrame(base_rows).to_csv(
        os.path.join(TABLES_DIR, "reviewer_multibaseline_detection.csv"),
        index=False)
    summary["multibaseline"] = base_rows
    log("  saved reviewer_multibaseline_detection.csv")

    # ---------------- Part B: Wilcoxon + t-test ----------------
    log("\n== Wilcoxon signed-rank + paired t-test (baseline vs condition) ==")
    wilcox_rows = []
    for det_name, res in all_results.items():
        if "baseline" not in res:
            continue
        for metric in ["f1_fixed", "roc_auc"]:
            base_vals = res["baseline"][metric]
            for cond, arr in res.items():
                if cond == "baseline":
                    continue
                comp_vals = arr[metric]
                m = min(len(base_vals), len(comp_vals))
                a, b = base_vals[:m], comp_vals[:m]
                row = {"Detector": det_name,
                       "Metric": "F1_fixed" if metric == "f1_fixed" else "AUC",
                       "Comparison": f"baseline vs {cond}",
                       "baseline_mean": float(np.mean(a)),
                       "condition_mean": float(np.mean(b)),
                       "n_pairs": int(m)}
                try:
                    tt = paired_test(a, b, test="t-test")
                    row["t_p"] = float(tt["p_value"])
                    row["cohens_d"] = float(tt["cohens_d"])
                except Exception as e:
                    row["t_p"] = np.nan
                    row["cohens_d"] = np.nan
                # Wilcoxon needs non-zero differences
                if np.allclose(a - b, 0.0):
                    row["wilcoxon_p"] = np.nan
                    row["wilcoxon_note"] = "all diffs zero (deterministic)"
                else:
                    try:
                        wt = paired_test(a, b, test="wilcoxon")
                        row["wilcoxon_p"] = float(wt["p_value"])
                        row["wilcoxon_note"] = ""
                    except Exception as e:
                        row["wilcoxon_p"] = np.nan
                        row["wilcoxon_note"] = str(e)
                wilcox_rows.append(row)
                log(f"    {det_name} {row['Metric']} {cond}: "
                    f"t_p={row.get('t_p'):.4g} w_p={row.get('wilcoxon_p')}")
    pd.DataFrame(wilcox_rows).to_csv(
        os.path.join(TABLES_DIR, "reviewer_wilcoxon_tests.csv"), index=False)
    summary["wilcoxon"] = wilcox_rows
    log("  saved reviewer_wilcoxon_tests.csv")

    # ---------------- Part D: window-threshold sensitivity ----------------
    log("\n== Window-label threshold sensitivity {0.2,0.3,0.4,0.5} (PCA) ==")
    win_rows = []
    for thr in WINDOW_THRESHOLDS:
        for cond in CONDITIONS:
            degrade_fn = make_degrade_fn(cond)
            f1s, aucs = [], []
            for seed in STAT_SEEDS[:CHEAP_SEEDS]:
                r = run_once("PCA", seed, clean_train, all_sensors, labels,
                             test_start, window_size, degrade_fn,
                             window_thr=thr)
                f1s.append(r.get("f1_fixed", 0.0))
                aucs.append(r.get("roc_auc", 0.0))
            win_rows.append({
                "window_threshold": thr, "Condition": cond,
                "F1_fixed": float(np.mean(f1s)),
                "F1_std": float(np.std(f1s, ddof=1) if len(f1s) > 1 else 0.0),
                "AUC": float(np.mean(aucs)),
                "AUC_std": float(np.std(aucs, ddof=1) if len(aucs) > 1 else 0.0),
            })
            log(f"    thr={thr} {cond}: F1={np.mean(f1s):.4f} AUC={np.mean(aucs):.4f}")
    pd.DataFrame(win_rows).to_csv(
        os.path.join(TABLES_DIR, "reviewer_window_threshold_sensitivity.csv"),
        index=False)
    summary["window_sensitivity"] = win_rows
    log("  saved reviewer_window_threshold_sensitivity.csv")

    summary["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(TABLES_DIR, "reviewer_summary.json"), "w",
              encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    log(f"\nDONE in {summary['elapsed_sec']}s. Wrote reviewer_summary.json")


if __name__ == "__main__":
    main()
