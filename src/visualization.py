"""
Publication-quality visualization for Bridge SHM DQA paper.
All figures designed for 2-3 zone SCI journal (300 DPI, serif font).
"""
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap
import seaborn as sns
from typing import Dict, List, Optional, Tuple
from collections import OrderedDict
from sklearn.metrics import roc_curve, auc, confusion_matrix
import os

from src.config import FIGURES_DIR

plt.rcParams.update({
    'font.size': 11, 'font.family': 'serif',
    'axes.labelsize': 12, 'axes.titlesize': 13,
    'xtick.labelsize': 10, 'ytick.labelsize': 10,
    'legend.fontsize': 9, 'figure.dpi': 300,
    'savefig.dpi': 300, 'savefig.bbox': 'tight',
    'axes.grid': True, 'grid.alpha': 0.3,
})

QUALITY_CMAP = LinearSegmentedColormap.from_list(
    'quality', ['#d32f2f', '#ff9800', '#fdd835', '#66bb6a', '#2e7d32']
)

def _save(fig, name):
    path = os.path.join(FIGURES_DIR, name)
    fig.savefig(path, dpi=300, bbox_inches='tight', pad_inches=0.15)
    plt.close(fig)
    print(f"[SAVED] {path}")
    return path


def plot_missing_heatmap(data, title="Data Completeness Heatmap",
                         save_name="fig1_missing_heatmap.png"):
    cols = list(data.columns)
    n_sensors = len(cols)

    acc_cols = [c for c in cols if 'Acc' in c]
    strain_cols = [c for c in cols if 'Strain' in c]
    tilt_cols = [c for c in cols if 'Tilt' in c]
    other_cols = [c for c in cols if c not in acc_cols + strain_cols + tilt_cols]
    ordered = acc_cols + strain_cols + tilt_cols + other_cols
    data_ordered = data[ordered]

    max_rows = 2000
    step = max(1, len(data_ordered) // max_rows)
    display = data_ordered.iloc[::step]
    matrix = display.isnull().astype(int).values.T

    fig_h = max(6, n_sensors * 0.45 + 2)
    fig, (ax_main, ax_group) = plt.subplots(
        1, 2, figsize=(14, fig_h),
        gridspec_kw={'width_ratios': [30, 1], 'wspace': 0.02}
    )

    present_color = '#4fc3f7'
    missing_color = '#ffffff'
    cmap = plt.cm.colors.ListedColormap([present_color, missing_color])
    ax_main.imshow(matrix, aspect='auto', cmap=cmap, interpolation='nearest')

    ax_main.set_yticks(range(len(ordered)))
    ax_main.set_yticklabels(ordered, fontsize=9, fontfamily='monospace')
    ax_main.set_xlabel("Time Index (downsampled)", fontsize=11)
    ax_main.set_title(title, fontweight='bold', fontsize=13)

    group_colors = {'Accelerometer': '#1565c0', 'Strain Gauge': '#2e7d32', 'Tiltmeter': '#e65100'}
    groups = []
    if acc_cols:    groups.append(('Accelerometer', 0, len(acc_cols)-1, group_colors['Accelerometer']))
    if strain_cols: groups.append(('Strain Gauge', len(acc_cols), len(acc_cols)+len(strain_cols)-1, group_colors['Strain Gauge']))
    if tilt_cols:   groups.append(('Tiltmeter', len(acc_cols)+len(strain_cols), len(acc_cols)+len(strain_cols)+len(tilt_cols)-1, group_colors['Tiltmeter']))

    for gname, y_start, y_end, gc in groups:
        ax_main.axhline(y=y_start - 0.5, color='#424242', linewidth=1.5, linestyle='-')
        mid_y = (y_start + y_end) / 2
        ax_group.barh(mid_y, 1, height=y_end - y_start + 0.8,
                      color=gc, alpha=0.7, edgecolor='white')
        ax_group.text(0.5, mid_y, gname, ha='center', va='center',
                      fontsize=7, fontweight='bold', color='white',
                      rotation=90)
    if groups:
        ax_main.axhline(y=groups[-1][2] + 0.5, color='#424242', linewidth=1.5)

    ax_group.set_ylim(ax_main.get_ylim())
    ax_group.set_xlim(0, 1)
    ax_group.axis('off')

    legend_elements = [
        mpatches.Patch(facecolor=present_color, edgecolor='gray', label='Present'),
        mpatches.Patch(facecolor=missing_color, edgecolor='gray', label='Missing'),
    ]
    ax_main.legend(handles=legend_elements, loc='upper right', fontsize=9,
                   framealpha=0.95)
    plt.tight_layout()
    return _save(fig, save_name)


def plot_timeseries_comparison(original, degraded, repaired, sensor_name,
                               start_idx=0, length=3000,
                               save_name="fig2_timeseries_overlay.png"):
    fig, axes = plt.subplots(3, 1, figsize=(14, 8), sharex=True)
    end_idx = min(start_idx + length, len(original))
    x = np.arange(start_idx, end_idx)

    orig = original.iloc[start_idx:end_idx].values.astype(float)
    deg = degraded.iloc[start_idx:end_idx].values.astype(float)
    rep = repaired.iloc[start_idx:end_idx].values.astype(float)

    # Detrend: remove DC offset so waveform oscillations are visible
    orig_mean = np.nanmean(orig)
    orig_d = orig - orig_mean
    deg_d = deg - orig_mean
    rep_d = rep - orig_mean

    valid_vals = orig_d[np.isfinite(orig_d)]
    if len(valid_vals) > 0:
        yrange = np.nanmax(np.abs(valid_vals))
        yrange = max(yrange, 1e-6)
        pad = yrange * 0.3
        ylim = (-yrange - pad, yrange + pad)
    else:
        ylim = (-1, 1)

    axes[0].plot(x, orig_d, color='#1565c0', linewidth=0.5)
    axes[0].set_ylabel("Amplitude (detrended)")
    axes[0].set_title(f"(a) Original Signal — {sensor_name}", fontweight='bold')
    axes[0].set_ylim(ylim)

    axes[1].plot(x, deg_d, color='#c62828', linewidth=0.5, alpha=0.8)
    missing_mask = np.isnan(deg_d)
    if np.any(missing_mask):
        starts = np.where(np.diff(missing_mask.astype(int)) == 1)[0]
        ends = np.where(np.diff(missing_mask.astype(int)) == -1)[0]
        if missing_mask[0]: starts = np.insert(starts, 0, 0)
        if missing_mask[-1]: ends = np.append(ends, len(missing_mask)-1)
        for s_i, e_i in zip(starts, ends):
            axes[1].axvspan(x[s_i], x[min(e_i, len(x)-1)],
                            color='#ffcdd2', alpha=0.6, zorder=0)
    axes[1].set_ylabel("Amplitude (detrended)")
    axes[1].set_title("(b) Degraded Signal (missing blocks highlighted in red)", fontweight='bold')
    axes[1].set_ylim(ylim)

    axes[2].plot(x, orig_d, color='#bdbdbd', linewidth=0.6, alpha=0.6, label='Original')
    axes[2].plot(x, rep_d, color='#2e7d32', linewidth=0.7, alpha=0.85, label='Repaired')
    axes[2].set_ylabel("Amplitude (detrended)")
    axes[2].set_xlabel("Sample Index")
    axes[2].set_title("(c) Repaired Signal (linear interpolation) vs. Original", fontweight='bold')
    axes[2].legend(loc='upper right', framealpha=0.9)
    axes[2].set_ylim(ylim)

    plt.tight_layout(h_pad=0.5)
    return _save(fig, save_name)


def plot_bridge_quality_map(sensor_scores, bridge_name="Vanersborg Bridge",
                            save_name="fig3_bridge_quality_map.png"):
    fig, ax = plt.subplots(figsize=(16, 9))

    bx = [0, 2, 4, 6, 8, 10, 12, 14]
    by_top = [1.5, 2.0, 2.3, 2.5, 2.5, 2.3, 2.0, 1.5]
    by_bot = [1.0]*8
    ax.fill_between(bx, by_bot, by_top, color='#e0e0e0', edgecolor='#616161', linewidth=2)
    ax.plot(bx, by_top, 'k-', linewidth=2.5)
    ax.plot(bx, by_bot, 'k-', linewidth=2.5)
    for px in [2, 7, 12]:
        ax.plot([px, px], [-0.5, 1.0], color='#757575', linewidth=7)
        ax.plot([px-0.3, px+0.3], [-0.5, -0.5], color='#424242', linewidth=10)

    acc_names = [n for n in sensor_scores.index if 'Acc' in n]
    str_names = [n for n in sensor_scores.index if 'Strain' in n]
    tlt_names = [n for n in sensor_scores.index if 'Tilt' in n]

    acc_y = 3.2
    acc_x = np.linspace(1.0, 13.0, len(acc_names))
    for i, name in enumerate(acc_names):
        score = sensor_scores[name]
        color = QUALITY_CMAP(score / 100.0)
        ax.scatter(acc_x[i], acc_y, c=[color], s=280, marker='^',
                   edgecolors='black', linewidths=1.0, zorder=5)
        ax.annotate(f"{score:.0f}", (acc_x[i], acc_y),
                    textcoords="offset points", xytext=(0, 18),
                    ha='center', fontsize=9, fontweight='bold')
        ax.annotate(f"A{i+1}", (acc_x[i], acc_y),
                    textcoords="offset points", xytext=(0, -18),
                    ha='center', fontsize=8, color='#1565c0', fontweight='bold')

    str_y = 0.3
    pillar_x = {2, 7, 12}
    # Distribute strain gauges avoiding pillar positions
    candidate_x = np.linspace(3.5, 10.5, len(str_names) + 4)
    str_x = [cx for cx in candidate_x if all(abs(cx - px) > 0.8 for px in pillar_x)]
    str_x = np.array(str_x[:len(str_names)])
    if len(str_x) < len(str_names):
        str_x = np.linspace(3.5, 10.5, len(str_names))

    for i, name in enumerate(str_names):
        score = sensor_scores[name]
        color = QUALITY_CMAP(score / 100.0)
        ax.scatter(str_x[i], str_y, c=[color], s=280, marker='s',
                   edgecolors='black', linewidths=1.0, zorder=5)
        ax.annotate(f"{score:.0f}", (str_x[i], str_y),
                    textcoords="offset points", xytext=(0, 18),
                    ha='center', fontsize=9, fontweight='bold')
        ax.annotate(f"S{i+1}", (str_x[i], str_y),
                    textcoords="offset points", xytext=(0, -18),
                    ha='center', fontsize=8, color='#2e7d32', fontweight='bold')

    tlt_y = 4.0
    tlt_x = np.linspace(8.5, 12.5, len(tlt_names))
    for i, name in enumerate(tlt_names):
        score = sensor_scores[name]
        color = QUALITY_CMAP(score / 100.0)
        ax.scatter(tlt_x[i], tlt_y, c=[color], s=280, marker='D',
                   edgecolors='black', linewidths=1.0, zorder=5)
        ax.annotate(f"{score:.0f}", (tlt_x[i], tlt_y),
                    textcoords="offset points", xytext=(0, 18),
                    ha='center', fontsize=9, fontweight='bold')
        ax.annotate(f"T{i+1}", (tlt_x[i], tlt_y),
                    textcoords="offset points", xytext=(0, -18),
                    ha='center', fontsize=8, color='#e65100', fontweight='bold')

    sm = plt.cm.ScalarMappable(cmap=QUALITY_CMAP, norm=plt.Normalize(0, 100))
    sm.set_array([])
    cbar = plt.colorbar(sm, ax=ax, shrink=0.5, pad=0.02)
    cbar.set_label("Composite Quality Score (0-100)", fontsize=11)

    legend_elems = []
    if acc_names:
        legend_elems.append(plt.Line2D([0],[0], marker='^', color='w', markerfacecolor='#1565c0',
                   markersize=11, label=f'Accelerometer (A1–A{len(acc_names)})'))
    if str_names:
        legend_elems.append(plt.Line2D([0],[0], marker='s', color='w', markerfacecolor='#2e7d32',
                   markersize=11, label=f'Strain Gauge (S1–S{len(str_names)})'))
    if tlt_names:
        legend_elems.append(plt.Line2D([0],[0], marker='D', color='w', markerfacecolor='#e65100',
                   markersize=11, label=f'Tiltmeter (T1–T{len(tlt_names)})'))
    ax.legend(handles=legend_elems, loc='upper left', fontsize=10, framealpha=0.95)
    ax.set_xlim(-0.5, 15.5)
    ax.set_ylim(-1.2, 5.5)
    ax.set_title(f"Sensor Data Quality Map — {bridge_name}", fontweight='bold', fontsize=14)
    ax.axis('off')
    plt.tight_layout()
    return _save(fig, save_name)


def plot_degradation_curves(results, metric_name="f1_score",
                            save_name="fig4_degradation.png",
                            error_bars=None):
    """
    Plot performance degradation curves.
    
    Args:
        results: dict mapping condition -> {pca_f1_score: val, ...}
        metric_name: which metric to plot
        error_bars: optional dict mapping condition -> {metric: std_array}
    """
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

    # Left: Missing data
    ax = axes[0]
    rates = [0, 5, 10, 20]
    pca, ae_rates, ae_vals = [], [], []
    pca_err = []
    for r in rates:
        key = "baseline" if r == 0 else f"missing_{r}pct"
        d = results.get(key, {})
        pca.append(d.get(f"pca_{metric_name}", 0))
        ae_val = d.get(f"ae_{metric_name}", 0)
        if ae_val > 0:
            ae_rates.append(r)
            ae_vals.append(ae_val)
        if error_bars and key in error_bars:
            pca_err.append(error_bars[key].get(f"pca_{metric_name}_std", 0))
        else:
            pca_err.append(0)

    if any(e > 0 for e in pca_err):
        ax.errorbar(rates, pca, yerr=pca_err, fmt='o-', color='#1565c0',
                   lw=2, ms=8, capsize=4, label='PCA Detector')
    else:
        ax.plot(rates, pca, 'o-', color='#1565c0', lw=2, ms=8, label='PCA Detector')
    if ae_vals:
        ax.plot(ae_rates, ae_vals, 's--', color='#c62828', lw=2, ms=8, label='AE Detector')

    if "missing_20pct_linear_interp" in results:
        d = results["missing_20pct_linear_interp"]
        ax.scatter([20], [d.get(f"pca_{metric_name}", 0)],
                   marker='*', s=250, color='#2e7d32', zorder=6,
                   label='PCA (After Linear Interp.)')

    all_vals = pca + ae_vals
    ymin = min(all_vals) - 0.05 if all_vals else 0
    ax.set_ylim(max(0, ymin), 1.02)
    ax.set_xlabel("Missing Data Rate (%)")
    ax.set_ylabel(metric_name.replace("_", " ").upper())
    ax.set_title("(a) Impact of Missing Data", fontweight='bold')
    ax.legend(loc='lower left', fontsize=9)

    # Right: Noise + Spikes combined
    ax2 = axes[1]
    conditions = ['Baseline', 'Noise\n20dB', 'Noise\n10dB', 'Noise\n5dB', 'Spikes\n0.5%', 'Drift']
    keys = ['baseline', 'noise_20dB', 'noise_10dB', 'noise_5dB', 'spikes_0.5pct', 'drift']
    pca2 = []
    ae2_pos, ae2_vals = [], []
    pca2_err = []
    for i, k in enumerate(keys):
        d = results.get(k, {})
        pca2.append(d.get(f"pca_{metric_name}", 0))
        ae_val = d.get(f"ae_{metric_name}", 0)
        if ae_val > 0:
            ae2_pos.append(i)
            ae2_vals.append(ae_val)
        if error_bars and k in error_bars:
            pca2_err.append(error_bars[k].get(f"pca_{metric_name}_std", 0))
        else:
            pca2_err.append(0)

    x_pos = np.arange(len(conditions))
    if any(e > 0 for e in pca2_err):
        ax2.errorbar(x_pos, pca2, yerr=pca2_err, fmt='o-', color='#1565c0',
                    lw=2, ms=8, capsize=4, label='PCA Detector')
    else:
        ax2.plot(x_pos, pca2, 'o-', color='#1565c0', lw=2, ms=8, label='PCA Detector')
    if ae2_vals:
        ax2.plot(ae2_pos, ae2_vals, 's--', color='#c62828', lw=2, ms=8, label='AE Detector')

    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(conditions, fontsize=9)
    ax2.set_xlabel("Defect Condition")
    ax2.set_ylabel(metric_name.replace("_", " ").upper())
    ax2.set_title("(b) Impact of Noise, Spikes, and Drift", fontweight='bold')
    ax2.legend(loc='lower left', fontsize=9)
    all_vals2 = pca2 + ae2_vals
    ymin2 = min(all_vals2) - 0.05 if all_vals2 else 0
    ax2.set_ylim(max(0, ymin2), 1.02)

    plt.tight_layout()
    return _save(fig, save_name)


def plot_roc_curves(roc_data, save_name="fig5_roc_curves.png"):
    fig, ax = plt.subplots(figsize=(7.5, 6.5))
    colors = ['#1565c0', '#c62828', '#ff8f00', '#2e7d32', '#6a1b9a']
    styles = ['-', '--', '-.', ':', '-']
    widths = [2.5, 2.5, 2.0, 2.0, 2.0]

    for idx, (label, data) in enumerate(roc_data.items()):
        if 'fpr' in data and 'tpr' in data:
            ax.plot(data['fpr'], data['tpr'],
                    color=colors[idx % len(colors)],
                    linestyle=styles[idx % len(styles)],
                    linewidth=widths[idx % len(widths)],
                    label=f'{label} (AUC={data.get("roc_auc",0):.4f})')

    ax.plot([0,1], [0,1], 'k--', alpha=0.3, label='Random Classifier')
    ax.set_xlabel("False Positive Rate", fontsize=12)
    ax.set_ylabel("True Positive Rate", fontsize=12)
    ax.set_title("ROC Curves Under Different Data Quality Conditions", fontweight='bold')
    ax.legend(loc='lower right', fontsize=9, framealpha=0.95)
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    plt.tight_layout()
    return _save(fig, save_name)


def plot_confusion_matrices(cm_data, save_name="fig6_confusion_matrices.png"):
    n = len(cm_data)
    fig, axes = plt.subplots(1, n, figsize=(4.8*n, 4.8))
    if n == 1: axes = [axes]
    cat_labels = ['Healthy', 'Damaged']
    for idx, (title, cm) in enumerate(cm_data.items()):
        sns.heatmap(cm, annot=True, fmt='d', cmap='Blues',
                    xticklabels=cat_labels, yticklabels=cat_labels,
                    ax=axes[idx], cbar=False,
                    annot_kws={"size": 15, "fontweight": "bold"},
                    linewidths=1, linecolor='white')
        # Ensure annotation text contrasts with background
        for t in axes[idx].texts:
            val = int(t.get_text())
            if val > cm.max() * 0.6:
                t.set_color('white')
            else:
                t.set_color('black')
        axes[idx].set_xlabel("Predicted", fontsize=11)
        axes[idx].set_ylabel("Actual", fontsize=11)
        axes[idx].set_title(title, fontsize=11, fontweight='bold')
    plt.suptitle("Confusion Matrices Under Different Data Quality Conditions",
                 fontweight='bold', y=1.02, fontsize=13)
    plt.tight_layout()
    return _save(fig, save_name)


def plot_dqa_radar(quality_metrics, sensor_name="Acc_1",
                   save_name="fig7_dqa_radar.png"):
    categories = ['Completeness', 'Accuracy', 'SNR', 'Consistency']
    n_cats = len(categories)
    angles = np.linspace(0, 2*np.pi, n_cats, endpoint=False)
    angles = (angles + np.pi/4) % (2*np.pi)
    angles = angles.tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(7.5, 6.5), subplot_kw=dict(polar=True))
    colors = ['#1565c0', '#c62828', '#ff8f00', '#2e7d32', '#6a1b9a']
    styles = ['-', '--', '-.', ':', '-']
    linewidths = [2.5, 2.0, 2.0, 2.0, 2.0]

    for idx, (label, metrics) in enumerate(quality_metrics.items()):
        values = [
            metrics.get('completeness', pd.Series()).get(sensor_name, 0),
            metrics.get('accuracy', pd.Series()).get(sensor_name, 0),
            metrics.get('snr_score', pd.Series()).get(sensor_name, 0),
            metrics.get('consistency', pd.Series()).get(sensor_name, 0),
        ]
        values += values[:1]
        c = colors[idx % len(colors)]
        ax.plot(angles, values, 'o-', color=c, linewidth=linewidths[idx % len(linewidths)],
                linestyle=styles[idx % len(styles)], label=label, markersize=6)
        ax.fill(angles, values, color=c, alpha=0.06)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, fontsize=11, fontweight='bold')
    ax.set_ylim(0, 1.05)
    ax.set_rticks([0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_rlabel_position(22.5)
    ax.set_title(f"Data Quality Radar — {sensor_name}", fontweight='bold',
                 fontsize=13, pad=20)
    ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1), fontsize=9,
              framealpha=0.95)
    plt.tight_layout(pad=1.5)
    return _save(fig, save_name)


def plot_quality_boxplot(all_scores, save_name="fig8_quality_boxplot.png"):
    fig, ax = plt.subplots(figsize=(12, 5.5))
    plot_data = []
    for gn, scores in all_scores.items():
        for v in scores.values:
            plot_data.append({"Group": gn, "Quality Score": v})
    df = pd.DataFrame(plot_data)
    palette = sns.color_palette("RdYlGn", n_colors=len(all_scores))
    sns.boxplot(data=df, x="Group", y="Quality Score", palette=palette, ax=ax, width=0.6)
    ax.set_xticklabels(ax.get_xticklabels(), rotation=30, ha='right')
    ax.set_ylabel("Composite Quality Score (0-100)")
    ax.set_title("Data Quality Score Distribution Across Experimental Groups", fontweight='bold')
    ax.axhline(y=70, color='green', ls='--', alpha=0.5, label='Good threshold')
    ax.axhline(y=40, color='red', ls='--', alpha=0.5, label='Poor threshold')
    ax.legend(loc='lower left')
    plt.tight_layout()
    return _save(fig, save_name)


def plot_repair_comparison_bar(repair_results, metric="f1_score",
                               save_name="fig9_repair_comparison.png"):
    fig, ax = plt.subplots(figsize=(11, 6))
    methods = list(repair_results.keys())
    pca_v = [repair_results[m].get(f"pca_{metric}", 0) for m in methods]
    ae_v = [repair_results[m].get(f"ae_{metric}", 0) for m in methods]

    has_ae = any(v > 0 for v in ae_v)
    x = np.arange(len(methods))

    if has_ae:
        w = 0.35
        b1 = ax.bar(x - w/2, pca_v, w, label='PCA Detector', color='#1565c0', alpha=0.85)
        b2 = ax.bar(x + w/2, ae_v, w, label='AE Detector', color='#c62828', alpha=0.85)
        for b in b2:
            if b.get_height() > 0:
                ax.text(b.get_x() + b.get_width()/2., b.get_height() + 0.008,
                        f'{b.get_height():.3f}', ha='center', va='bottom', fontsize=8)
    else:
        w = 0.5
        b1 = ax.bar(x, pca_v, w, label='PCA Detector', color='#1565c0', alpha=0.85)

    for b in b1:
        ax.text(b.get_x() + b.get_width()/2., b.get_height() + 0.008,
                f'{b.get_height():.3f}', ha='center', va='bottom', fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels(methods, rotation=25, ha='right', fontsize=9)
    nice = metric.replace('_', ' ').upper()
    ax.set_ylabel(nice, fontsize=12)
    ax.set_title(f"Damage Detection {nice} After Different Repair Methods", fontweight='bold')
    ax.legend(fontsize=10)
    max_v = max(pca_v + [v for v in ae_v if v > 0] + [0.1])
    ax.set_ylim(0, max_v * 1.12)
    plt.tight_layout()
    return _save(fig, save_name)
