"""
Monitor downloads and auto-run experiments when data is ready.
Checks both Vanersborg and Z-24 datasets periodically.
Can start Vanersborg experiments independently when that dataset is ready.
"""
import os
import sys
import time
import subprocess

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
VB_ZIP = os.path.join(PROJECT_DIR, "data", "raw", "vanersborg", "DiB.zip")
Z24_INPUT = os.path.join(PROJECT_DIR, "data", "raw", "z24", "inputs.npy")
Z24_LABEL = os.path.join(PROJECT_DIR, "data", "raw", "z24", "labels.npy")

VB_EXPECTED = 551748539
Z24_EXPECTED = 991440128

CHECK_INTERVAL = 60


def get_size(path):
    return os.path.getsize(path) if os.path.exists(path) else 0


def is_ready(path, expected):
    return get_size(path) >= expected


def main():
    print("=" * 60)
    print("  DATA DOWNLOAD MONITOR & AUTO-RUNNER")
    print("=" * 60)
    print(f"  Vanersborg: {VB_ZIP}")
    print(f"  Z-24 inputs: {Z24_INPUT}")
    print(f"  Check interval: {CHECK_INTERVAL}s")
    print()

    vb_experiment_done = False
    z24_experiment_done = False
    last_vb_size = 0
    last_z24_size = 0

    while True:
        vb_size = get_size(VB_ZIP)
        z24_size = get_size(Z24_INPUT)
        z24_label_ok = os.path.exists(Z24_LABEL) and get_size(Z24_LABEL) > 100

        vb_pct = vb_size * 100 / VB_EXPECTED if VB_EXPECTED > 0 else 0
        z24_pct = z24_size * 100 / Z24_EXPECTED if Z24_EXPECTED > 0 else 0

        vb_speed = (vb_size - last_vb_size) / CHECK_INTERVAL / 1024 if last_vb_size > 0 else 0
        z24_speed = (z24_size - last_z24_size) / CHECK_INTERVAL / 1024 if last_z24_size > 0 else 0

        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] Vanersborg: {vb_size/1024/1024:.1f}/{VB_EXPECTED/1024/1024:.0f} MB "
              f"({vb_pct:.1f}%) {vb_speed:.0f} KB/s | "
              f"Z-24: {z24_size/1024/1024:.1f}/{Z24_EXPECTED/1024/1024:.0f} MB "
              f"({z24_pct:.1f}%) {z24_speed:.0f} KB/s | "
              f"Labels: {'OK' if z24_label_ok else 'MISSING'}",
              flush=True)

        last_vb_size = vb_size
        last_z24_size = z24_size

        if is_ready(VB_ZIP, VB_EXPECTED) and not vb_experiment_done:
            print(f"\n{'='*60}")
            print(f"  VANERSBORG DATA READY - LAUNCHING EXPERIMENT")
            print(f"{'='*60}\n")
            result = subprocess.run(
                [sys.executable, "run_experiment_v2.py"],
                cwd=PROJECT_DIR,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"}
            )
            vb_experiment_done = True
            print(f"\n  Experiment exit code: {result.returncode}")

        if is_ready(Z24_INPUT, Z24_EXPECTED) and z24_label_ok and not z24_experiment_done:
            print(f"\n{'='*60}")
            print(f"  ALL DATA READY - FULL EXPERIMENT RUN")
            print(f"{'='*60}\n")
            result = subprocess.run(
                [sys.executable, "run_experiment_v2.py"],
                cwd=PROJECT_DIR,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"}
            )
            z24_experiment_done = True
            print(f"\n  Full experiment exit code: {result.returncode}")
            print("  ALL EXPERIMENTS COMPLETE!")
            break

        if vb_experiment_done and z24_experiment_done:
            break

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
