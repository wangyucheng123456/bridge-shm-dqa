"""
Global configuration for the Bridge SHM Data Quality Assessment project.
Supports both real datasets and synthetic fallback.
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_RAW_DIR = os.path.join(PROJECT_ROOT, "data", "raw")
DATA_PROCESSED_DIR = os.path.join(PROJECT_ROOT, "data", "processed")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
FIGURES_DIR = os.path.join(RESULTS_DIR, "figures")
TABLES_DIR = os.path.join(RESULTS_DIR, "tables")
MODELS_DIR = os.path.join(PROJECT_ROOT, "models")

RANDOM_SEED = 42

# --- Real Vänersborg Bridge Data ---
VANERSBORG_RAW_DIR = os.path.join(DATA_RAW_DIR, "vanersborg")
VANERSBORG_ZIP = os.path.join(VANERSBORG_RAW_DIR, "DiB.zip")

# --- Real Z-24 Bridge Data ---
Z24_RAW_DIR = os.path.join(DATA_RAW_DIR, "z24")
Z24_INPUTS_NPY = os.path.join(Z24_RAW_DIR, "inputs.npy")
Z24_LABELS_NPY = os.path.join(Z24_RAW_DIR, "labels.npy")

# --- Z-24 Dataset Structure ---
# 17 scenarios: scenario 0 = reference (undamaged), scenarios 1-16 = progressive damage
# 9 setups per scenario, 10 segments per setup => 1530 total segments
Z24_N_SCENARIOS = 17
Z24_N_SETUPS = 9
Z24_N_SEGMENTS_PER_SETUP = 10
Z24_N_SENSORS = 27
Z24_SEGMENT_LENGTH = 6000

# --- Data Degradation Parameters ---
MISSING_RATES = [0.05, 0.10, 0.20]
NOISE_SNR_DB = [20, 10, 5]
SPIKE_RATES = [0.005, 0.01]
DRIFT_MAGNITUDES = [0.5, 1.0]

# --- Damage Detection Model ---
PCA_N_COMPONENTS = 10
AUTOENCODER_LATENT_DIM = 16
AUTOENCODER_EPOCHS = 50
AUTOENCODER_BATCH_SIZE = 64
AUTOENCODER_LR = 1e-3

# --- Statistical Significance ---
# PCA is cheap so we use a larger pool; AE is capped at N_REPEAT_SEEDS_AE.
N_REPEAT_SEEDS = 20
N_REPEAT_SEEDS_AE = 10
N_BOOTSTRAP = 2000
STAT_SEEDS = [RANDOM_SEED + i * 7 for i in range(N_REPEAT_SEEDS)]
SIGNIFICANCE_ALPHA = 0.05

# --- DQA Weight Sensitivity ---
WEIGHT_GRID = [
    (0.4, 0.3, 0.2, 0.1),
    (0.3, 0.3, 0.2, 0.2),  # default
    (0.25, 0.25, 0.25, 0.25),
    (0.2, 0.4, 0.2, 0.2),
    (0.2, 0.2, 0.3, 0.3),
]

for d in [DATA_RAW_DIR, DATA_PROCESSED_DIR, FIGURES_DIR, TABLES_DIR, MODELS_DIR,
          VANERSBORG_RAW_DIR, Z24_RAW_DIR]:
    os.makedirs(d, exist_ok=True)
