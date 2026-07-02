"""
Data loader for real bridge SHM datasets.

Supports:
  - Vänersborg Bridge (Zenodo DOI: 10.5281/zenodo.8300495)
  - Z-24 Bridge (HuggingFace: thanglexuan/Z24-dataset-processed)
"""
import numpy as np
import pandas as pd
import os
import zipfile
import glob
from typing import Optional
from src.config import (
    VANERSBORG_RAW_DIR, VANERSBORG_ZIP,
    Z24_RAW_DIR, Z24_INPUTS_NPY, Z24_LABELS_NPY,
    Z24_N_SCENARIOS, Z24_N_SETUPS, Z24_N_SEGMENTS_PER_SETUP,
    DATA_PROCESSED_DIR, RANDOM_SEED
)


def _ensure_vanersborg_extracted():
    """Extract Vänersborg zip if not already done."""
    extract_dir = os.path.join(VANERSBORG_RAW_DIR, "extracted")
    if os.path.exists(extract_dir) and len(os.listdir(extract_dir)) > 0:
        return extract_dir
    if not os.path.exists(VANERSBORG_ZIP):
        raise FileNotFoundError(
            f"Vänersborg data not found at {VANERSBORG_ZIP}. "
            "Please run download_data.py first."
        )
    print(f"[INFO] Extracting {VANERSBORG_ZIP}...")
    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(VANERSBORG_ZIP, 'r') as zf:
        zf.extractall(extract_dir)
    print(f"[INFO] Extracted to {extract_dir}")
    return extract_dir


def _discover_vanersborg_files(extract_dir: str) -> dict:
    """Discover and categorize files in the Vänersborg extraction."""
    info = {"mat_files": [], "csv_files": [], "hdf5_files": [], "other": []}
    for root, dirs, files in os.walk(extract_dir):
        for f in files:
            fp = os.path.join(root, f)
            ext = f.lower().split('.')[-1] if '.' in f else ''
            if ext == 'mat':
                info["mat_files"].append(fp)
            elif ext == 'csv':
                info["csv_files"].append(fp)
            elif ext in ('h5', 'hdf5'):
                info["hdf5_files"].append(fp)
            else:
                info["other"].append(fp)
    return info


def load_vanersborg_data(max_events: Optional[int] = None) -> dict:
    """
    Load real Vänersborg Bridge monitoring data.

    The dataset contains 64 bridge opening events with:
      - 5 accelerometers (200 Hz)
      - 16 strain gauges (200 Hz)
      - 1 inclinometer (200 Hz)
      - 3 weather sensors (temperature, wind speed, wind direction)

    The fracture was detected on 2023-03-09 (event ~45 onwards is post-damage).

    Returns dict with keys matching the original interface:
      'acceleration', 'strain', 'tilt', 'temperature',
      'labels', 'fracture_idx', 'fs', 'n_events', 'event_boundaries'
    """
    extract_dir = _ensure_vanersborg_extracted()
    files_info = _discover_vanersborg_files(extract_dir)

    print(f"[INFO] Found files: {len(files_info['mat_files'])} .mat, "
          f"{len(files_info['csv_files'])} .csv, "
          f"{len(files_info['hdf5_files'])} .h5, "
          f"{len(files_info['other'])} other")

    # Try loading based on available format
    if files_info['mat_files']:
        return _load_vanersborg_mat(files_info['mat_files'], max_events)
    elif files_info['csv_files']:
        return _load_vanersborg_csv(files_info['csv_files'], max_events)
    elif files_info['hdf5_files']:
        return _load_vanersborg_hdf5(files_info['hdf5_files'], max_events)
    else:
        return _load_vanersborg_generic(extract_dir, max_events)


def _load_vanersborg_mat(mat_files: list, max_events: Optional[int]) -> dict:
    """Load Vänersborg data from MATLAB .mat files."""
    try:
        from scipy.io import loadmat
    except ImportError:
        raise ImportError("scipy is required to load .mat files")

    mat_files = sorted(mat_files)
    if max_events:
        mat_files = mat_files[:max_events]

    print(f"[INFO] Loading {len(mat_files)} .mat files...")

    all_acc, all_strain, all_tilt, all_temp = [], [], [], []
    event_boundaries = [0]

    for i, mf in enumerate(mat_files):
        data = loadmat(mf, squeeze_me=True)
        keys = [k for k in data.keys() if not k.startswith('_')]

        acc_keys = sorted([k for k in keys if 'acc' in k.lower() or 'a' == k.lower()[0]])
        str_keys = sorted([k for k in keys if 'strain' in k.lower() or 'str' in k.lower()])
        tilt_keys = sorted([k for k in keys if 'tilt' in k.lower() or 'incl' in k.lower()])
        temp_keys = sorted([k for k in keys if 'temp' in k.lower()])

        if not acc_keys:
            acc_keys = sorted([k for k in keys
                             if isinstance(data[k], np.ndarray) and data[k].ndim >= 1])[:5]

        event_data = {}
        for k in keys:
            v = data[k]
            if isinstance(v, np.ndarray) and v.ndim >= 1:
                event_data[k] = v.flatten() if v.ndim == 1 else v

        if i == 0:
            print(f"  Event 0 keys: {keys}")
            for k in keys:
                v = data[k]
                if isinstance(v, np.ndarray):
                    print(f"    {k}: shape={v.shape}, dtype={v.dtype}")

        # Build arrays for this event
        n_samples = max(len(v) for v in event_data.values()
                       if isinstance(v, np.ndarray) and v.ndim == 1)

        acc_arrays = []
        for k in acc_keys[:5]:
            arr = event_data.get(k)
            if arr is not None and isinstance(arr, np.ndarray):
                if arr.ndim == 1:
                    acc_arrays.append(arr[:n_samples])
                elif arr.ndim == 2:
                    for col in range(arr.shape[1]):
                        acc_arrays.append(arr[:n_samples, col])

        str_arrays = []
        for k in str_keys[:16]:
            arr = event_data.get(k)
            if arr is not None and isinstance(arr, np.ndarray):
                if arr.ndim == 1:
                    str_arrays.append(arr[:n_samples])

        tilt_arrays = []
        for k in tilt_keys[:1]:
            arr = event_data.get(k)
            if arr is not None and isinstance(arr, np.ndarray):
                if arr.ndim == 1:
                    tilt_arrays.append(arr[:n_samples])

        temp_arr = None
        for k in temp_keys[:1]:
            arr = event_data.get(k)
            if arr is not None and isinstance(arr, np.ndarray) and arr.ndim == 1:
                temp_arr = arr[:n_samples]

        if acc_arrays:
            all_acc.append(np.column_stack(acc_arrays))
        if str_arrays:
            all_strain.append(np.column_stack(str_arrays))
        if tilt_arrays:
            all_tilt.append(np.column_stack(tilt_arrays))
        if temp_arr is not None:
            all_temp.append(temp_arr)

        event_boundaries.append(event_boundaries[-1] + n_samples)

    return _assemble_vanersborg(all_acc, all_strain, all_tilt, all_temp,
                                 event_boundaries, len(mat_files))


def _load_vanersborg_csv(csv_files: list, max_events: Optional[int]) -> dict:
    """Load Vänersborg data from CSV files.

    The Zenodo DiB dataset has columns:
      'Unnamed: 0', 'ts', 'id', 'ch_1'...'ch_30', 'fileid', 'event'
    Channels 1-5: accelerometers, 6-21: strain gauges,
    22: inclinometer, 23-30: weather/other.
    """
    csv_files = sorted(csv_files)
    fracture_event = 45

    if max_events and max_events < len(csv_files):
        n_total = len(csv_files)
        n_pre = min(fracture_event, n_total)
        n_post = n_total - n_pre

        pre_take = min(max_events * 2 // 3, n_pre)
        post_take = min(max_events - pre_take, n_post)
        if post_take < max_events // 3 and n_post > 0:
            post_take = min(max_events // 3, n_post)
            pre_take = min(max_events - post_take, n_pre)

        pre_start = max(0, n_pre - pre_take)
        pre_files = csv_files[pre_start:n_pre]
        post_files = csv_files[n_pre:n_pre + post_take]
        csv_files = pre_files + post_files

        # Adjust fracture_event to reflect the new indexing
        fracture_event = len(pre_files)
        print(f"[INFO] Selected {len(pre_files)} pre-fracture + "
              f"{len(post_files)} post-fracture events")

    print(f"[INFO] Loading {len(csv_files)} CSV files...")
    all_acc, all_strain, all_tilt, all_temp = [], [], [], []
    event_boundaries = [0]

    for i, cf in enumerate(csv_files):
        df = pd.read_csv(cf)
        if i == 0:
            print(f"  CSV columns: {list(df.columns)}")
            print(f"  Rows: {len(df)}")

        # Try standard named columns first
        acc_cols = [c for c in df.columns if 'acc' in c.lower()]
        str_cols = [c for c in df.columns if 'strain' in c.lower()]
        tilt_cols = [c for c in df.columns if 'tilt' in c.lower() or 'incl' in c.lower()]
        temp_cols = [c for c in df.columns if 'temp' in c.lower()]

        # Fallback: DiB dataset uses ch_1..ch_30 naming
        ch_cols = sorted([c for c in df.columns if c.startswith('ch_')],
                         key=lambda x: int(x.split('_')[1]))

        if not acc_cols and ch_cols:
            # Map channels based on DiB dataset documentation:
            # ch_1-ch_5: accelerometers (200 Hz vibration data)
            # ch_6-ch_21: strain gauges (16 channels)
            # ch_22: inclinometer
            # ch_23-ch_25: weather (temperature, wind speed, wind direction)
            # ch_26-ch_30: additional sensors
            n_ch = len(ch_cols)
            if i == 0:
                print(f"  Using ch_N format: {n_ch} channels")

            acc_cols = ch_cols[:min(5, n_ch)]
            if n_ch > 5:
                str_cols = ch_cols[5:min(21, n_ch)]
            if n_ch > 21:
                tilt_cols = ch_cols[21:min(22, n_ch)]
            if n_ch > 22:
                temp_cols = ch_cols[22:min(23, n_ch)]

        if acc_cols:
            vals = df[acc_cols].apply(pd.to_numeric, errors='coerce').values
            all_acc.append(vals)
        if str_cols:
            vals = df[str_cols].apply(pd.to_numeric, errors='coerce').values
            all_strain.append(vals)
        if tilt_cols:
            vals = df[tilt_cols].apply(pd.to_numeric, errors='coerce').values
            all_tilt.append(vals)
        if temp_cols:
            vals = df[temp_cols[0]].apply(pd.to_numeric, errors='coerce').values
            all_temp.append(vals)

        event_boundaries.append(event_boundaries[-1] + len(df))

    return _assemble_vanersborg(all_acc, all_strain, all_tilt, all_temp,
                                 event_boundaries, len(csv_files),
                                 fracture_event_override=fracture_event)


def _load_vanersborg_hdf5(hdf5_files: list, max_events: Optional[int]) -> dict:
    """Load Vänersborg data from HDF5 files."""
    import h5py
    hdf5_files = sorted(hdf5_files)
    if max_events:
        hdf5_files = hdf5_files[:max_events]

    print(f"[INFO] Loading {len(hdf5_files)} HDF5 files...")
    all_acc, all_strain, all_tilt, all_temp = [], [], [], []
    event_boundaries = [0]

    for i, hf in enumerate(hdf5_files):
        with h5py.File(hf, 'r') as f:
            if i == 0:
                print(f"  HDF5 keys: {list(f.keys())}")
            for k in f.keys():
                arr = np.array(f[k])
                if 'acc' in k.lower():
                    all_acc.append(arr if arr.ndim == 2 else arr.reshape(-1, 1))
                elif 'strain' in k.lower():
                    all_strain.append(arr if arr.ndim == 2 else arr.reshape(-1, 1))
                elif 'tilt' in k.lower() or 'incl' in k.lower():
                    all_tilt.append(arr if arr.ndim == 2 else arr.reshape(-1, 1))
                elif 'temp' in k.lower():
                    all_temp.append(arr.flatten())
            n_samples = max(len(arr.flatten()) for arr in
                          [np.array(f[k]) for k in f.keys()])
            event_boundaries.append(event_boundaries[-1] + n_samples)

    return _assemble_vanersborg(all_acc, all_strain, all_tilt, all_temp,
                                 event_boundaries, len(hdf5_files))


def _load_vanersborg_generic(extract_dir: str, max_events: Optional[int]) -> dict:
    """Try to load Vänersborg data by probing all files."""
    all_files = []
    for root, dirs, files in os.walk(extract_dir):
        for f in files:
            all_files.append(os.path.join(root, f))
    print(f"[INFO] Found {len(all_files)} files, attempting generic load...")
    for f in all_files[:20]:
        print(f"  {f} ({os.path.getsize(f)} bytes)")

    npy_files = [f for f in all_files if f.endswith('.npy') or f.endswith('.npz')]
    if npy_files:
        print("[INFO] Found .npy/.npz files, loading...")
        return _load_vanersborg_numpy(npy_files, max_events)

    raise RuntimeError(
        f"Could not determine format of Vänersborg data in {extract_dir}. "
        f"Files found: {[os.path.basename(f) for f in all_files[:10]]}"
    )


def _load_vanersborg_numpy(npy_files: list, max_events: Optional[int]) -> dict:
    """Load from numpy files."""
    for f in npy_files:
        data = np.load(f, allow_pickle=True)
        print(f"  {os.path.basename(f)}: type={type(data)}")
        if isinstance(data, np.lib.npyio.NpzFile):
            print(f"    keys: {list(data.keys())}")
    raise NotImplementedError("NumPy format loader needs actual file inspection")


def _assemble_vanersborg(all_acc, all_strain, all_tilt, all_temp,
                          event_boundaries, n_events,
                          fracture_event_override=None):
    """Assemble loaded Vänersborg data into standard dict format."""
    fs = 200.0  # Hz (from the paper)

    fracture_event = fracture_event_override if fracture_event_override is not None else 45

    if all_acc:
        acc_data = np.vstack(all_acc)
        n_acc = acc_data.shape[1]
        acc_df = pd.DataFrame(acc_data,
                             columns=[f"Acc_{i+1}" for i in range(n_acc)])
    else:
        acc_df = pd.DataFrame()

    if all_strain:
        strain_data = np.vstack(all_strain)
        n_str = strain_data.shape[1]
        strain_df = pd.DataFrame(strain_data,
                                columns=[f"Strain_{i+1}" for i in range(n_str)])
    else:
        strain_df = pd.DataFrame()

    if all_tilt:
        tilt_data = np.vstack(all_tilt)
        n_tlt = tilt_data.shape[1]
        tilt_df = pd.DataFrame(tilt_data,
                              columns=[f"Tilt_{i+1}" for i in range(n_tlt)])
    else:
        tilt_df = pd.DataFrame()

    if all_temp:
        temp_arr = np.concatenate(all_temp)
        temp_series = pd.Series(temp_arr, name="Temperature")
    else:
        temp_series = pd.Series(dtype=float, name="Temperature")

    total_samples = event_boundaries[-1]
    fracture_idx = event_boundaries[min(fracture_event, len(event_boundaries) - 1)]

    labels = np.zeros(total_samples, dtype=int)
    labels[fracture_idx:] = 1

    print(f"[INFO] Vänersborg data assembled:")
    print(f"  Total samples: {total_samples}")
    print(f"  Accelerometers: {acc_df.shape[1] if len(acc_df) > 0 else 0}")
    print(f"  Strain gauges: {strain_df.shape[1] if len(strain_df) > 0 else 0}")
    print(f"  Tiltmeters: {tilt_df.shape[1] if len(tilt_df) > 0 else 0}")
    print(f"  Events: {n_events}, Fracture at event {fracture_event} (idx {fracture_idx})")

    return {
        "acceleration": acc_df,
        "strain": strain_df,
        "tilt": tilt_df,
        "temperature": temp_series,
        "labels": labels,
        "fracture_idx": fracture_idx,
        "fs": fs,
        "n_events": n_events,
        "event_boundaries": event_boundaries,
    }


def load_z24_data(max_segments: Optional[int] = None) -> dict:
    """
    Load real Z-24 Bridge dataset from preprocessed numpy files.

    Dataset structure:
      - inputs.npy: (1530, 27, 6000) acceleration time-series
      - labels.npy: (1530,) scenario labels (0-16)
      - Scenario 0 = reference (undamaged)
      - Scenarios 1-16 = progressive damage
      - 27 accelerometer sensors
      - 6000 time samples per segment at ~100 Hz

    Returns dict with:
      'acceleration': DataFrame (concatenated segments × sensors)
      'labels': array of 0/1 labels
      'scenario_labels': original 0-16 scenario IDs
      'segment_info': metadata about each segment
      'fs': sampling frequency
      'damage_idx': first sample index of damaged data
    """
    if not os.path.exists(Z24_INPUTS_NPY):
        raise FileNotFoundError(
            f"Z-24 inputs not found at {Z24_INPUTS_NPY}. "
            "Please run download_data.py first."
        )
    if not os.path.exists(Z24_LABELS_NPY):
        raise FileNotFoundError(
            f"Z-24 labels not found at {Z24_LABELS_NPY}. "
            "Please run download_data.py first."
        )

    print("[INFO] Loading Z-24 Bridge dataset from HuggingFace...")
    inputs = np.load(Z24_INPUTS_NPY)  # (1530, 27, 6000)
    raw_labels = np.load(Z24_LABELS_NPY)  # (1530,)

    print(f"  inputs shape: {inputs.shape}")
    print(f"  labels shape: {raw_labels.shape}")
    print(f"  unique labels: {np.unique(raw_labels)}")

    n_segments, n_sensors, segment_len = inputs.shape

    # Use actual labels from the dataset file as primary truth
    scenario_ids = raw_labels.astype(int)
    unique_labels = np.unique(scenario_ids)
    print(f"  Scenario distribution: {dict(zip(*np.unique(scenario_ids, return_counts=True)))}")

    # Binary labels: scenario 0 = healthy (0), all other scenarios = damaged (1)
    binary_labels = (scenario_ids > 0).astype(int)

    if max_segments and max_segments < n_segments:
        rng = np.random.default_rng(RANDOM_SEED)
        healthy_idx = np.where(binary_labels == 0)[0]
        damaged_idx = np.where(binary_labels == 1)[0]
        n_healthy = min(len(healthy_idx), max_segments // 2)
        n_damaged = min(len(damaged_idx), max_segments - n_healthy)
        selected = np.concatenate([
            healthy_idx[:n_healthy],
            rng.choice(damaged_idx, n_damaged, replace=False)
        ])
        selected = np.sort(selected)
        inputs = inputs[selected]
        binary_labels = binary_labels[selected]
        scenario_ids = scenario_ids[selected]
        raw_labels = raw_labels[selected] if len(raw_labels) == n_segments else raw_labels
        n_segments = len(selected)

    # Concatenate all segments into one long time series for each sensor
    # Shape: (n_segments * segment_len, n_sensors)
    acc_data = inputs.transpose(0, 2, 1).reshape(-1, n_sensors)
    acc_df = pd.DataFrame(acc_data,
                         columns=[f"Acc_{i+1}" for i in range(n_sensors)])

    # Expand labels to per-sample
    sample_labels = np.repeat(binary_labels, segment_len)
    damage_idx = np.argmax(sample_labels == 1) if np.any(sample_labels == 1) else len(sample_labels)

    # Segment metadata
    segment_info = pd.DataFrame({
        'segment_id': np.arange(n_segments),
        'scenario': scenario_ids,
        'binary_label': binary_labels,
        'start_sample': np.arange(n_segments) * segment_len,
        'end_sample': (np.arange(n_segments) + 1) * segment_len,
    })

    fs = 100.0  # approximate from the paper

    print(f"[INFO] Z-24 data assembled:")
    print(f"  Total samples: {len(acc_df)}")
    print(f"  Sensors: {n_sensors}")
    print(f"  Healthy segments: {np.sum(binary_labels == 0)}")
    print(f"  Damaged segments: {np.sum(binary_labels == 1)}")
    print(f"  Damage starts at sample index: {damage_idx}")

    return {
        "acceleration": acc_df,
        "labels": sample_labels,
        "scenario_labels": scenario_ids,
        "binary_labels": binary_labels,
        "segment_info": segment_info,
        "inputs_raw": inputs,
        "fs": fs,
        "damage_idx": damage_idx,
        "n_segments": n_segments,
        "segment_length": segment_len,
    }


def check_data_availability() -> dict:
    """Check which real datasets are available locally."""
    status = {}
    status["vanersborg"] = os.path.exists(VANERSBORG_ZIP) and \
                           os.path.getsize(VANERSBORG_ZIP) > 500_000_000
    status["z24_inputs"] = os.path.exists(Z24_INPUTS_NPY) and \
                           os.path.getsize(Z24_INPUTS_NPY) > 900_000_000
    status["z24_labels"] = os.path.exists(Z24_LABELS_NPY) and \
                           os.path.getsize(Z24_LABELS_NPY) > 100
    status["z24"] = status["z24_inputs"] and status["z24_labels"]
    return status
