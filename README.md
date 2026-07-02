# Data Quality Assessment and Enhancement for Bridge SHM

[![DOI](https://zenodo.org/badge/1287021222.svg)](https://doi.org/10.5281/zenodo.21130764)

Reproducible code for the manuscript *"A Comprehensive Data Quality Assessment
and Enhancement Framework for Bridge Structural Health Monitoring."*

The framework (i) scores multi-sensor SHM data along completeness, accuracy,
consistency and SNR, (ii) injects controlled quality defects (missing blocks,
Gaussian noise, spikes, drift), (iii) repairs them with six strategies, and
(iv) measures the downstream impact on unsupervised damage detection.

## Datasets (both public)

| Dataset | Source | Identifier |
|---|---|---|
| Vänersborg Bridge | Zenodo | DOI `10.5281/zenodo.8300495` |
| Z-24 Bridge (processed) | HuggingFace Hub | `thanglexuan/Z24-dataset-processed` |

Raw data (~4 GB) is **not** stored in the repository. Fetch it with:

```bash
python download_data.py        # or download_z24.py / download_vanersborg.py
```

## Installation

```bash
pip install -r requirements.txt
```

Tested with Python 3.9+, scikit-learn 1.0+, SciPy 1.7+, PyTorch 1.13 (CPU).

## Reproducing the results

```bash
# Main experiment pipeline (DQA, degradation, repair, PCA + dense-AE detection,
# multi-seed statistics) -> results/tables/, results/figures/
python run_experiment_v2.py

# Reviewer-response experiments (new work): leakage-free fixed-threshold F1,
# Wilcoxon signed-rank tests, Isolation Forest / One-Class SVM / LSTM-AE
# baselines, and window-label threshold sensitivity.
python reviewer_response.py
```

## Repository layout

```
src/
  config.py            # paths, seeds, hyper-parameters
  data_loader.py       # Vänersborg + Z-24 loaders
  data_degradation.py  # missing / noise / spike / drift injectors
  data_repair.py       # six repair strategies
  dqa_metrics.py       # completeness / accuracy / consistency / SNR + entropy weights
  damage_detection.py  # PCA, dense-AE, IsolationForest, OneClassSVM, LSTM-AE detectors
  statistical.py       # bootstrap CI, paired t-test, Wilcoxon signed-rank
  visualization.py     # publication figures
run_experiment_v2.py   # main pipeline
reviewer_response.py   # reviewer-response experiments
results/tables/        # CSV result tables (tracked)
results/figures/       # figures (tracked)
```

## Anomaly-detection protocol (leakage-free)

Each detector is trained on **healthy data only**. The decision threshold is
fixed as the **95th percentile of the anomaly-score distribution on the
training set** and applied unchanged to the test segment; no test-set labels
inform the operating point. We report AUC (threshold-independent) together
with fixed-threshold F1, precision and recall.

## Citation

If you use this code, please cite the manuscript (details to follow upon
acceptance), the archived software release, and the two datasets above.

Software archive (all versions): Zenodo, DOI
[`10.5281/zenodo.21130764`](https://doi.org/10.5281/zenodo.21130764).

## License

Released for academic use. See `LICENSE` (to be added) for details.
