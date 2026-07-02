"""Download Z-24 inputs.npy in explicit segments with seek-based writing."""
import os
import sys
import time
import requests

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HF_URL = "https://huggingface.co/datasets/thanglexuan/Z24-dataset-processed/resolve/main/inputs.npy"
DEST = os.path.join(os.path.dirname(__file__), "data", "raw", "z24", "inputs.npy")
EXPECTED = 991440128
SEGMENT_SIZE = 4 * 1024 * 1024  # 4 MB segments (smaller to survive connection drops)


def resolve_cdn_url():
    r = requests.head(HF_URL, allow_redirects=True, timeout=30)
    r.raise_for_status()
    return r.url


def download_segment(cdn_url, start, end, dest_path):
    """Download bytes [start, end) using streaming + seek-based writing."""
    headers = {'Range': f'bytes={start}-{end - 1}'}
    resp = requests.get(cdn_url, headers=headers, stream=True, timeout=120)

    if resp.status_code not in (200, 206):
        raise RuntimeError(f"HTTP {resp.status_code}")

    if resp.status_code == 200 and start > 0:
        raise RuntimeError("Server ignored Range (returned 200)")

    written = 0
    with open(dest_path, 'r+b') as f:
        f.seek(start)
        for chunk in resp.iter_content(chunk_size=256 * 1024):
            if chunk:
                f.write(chunk)
                written += len(chunk)
        f.flush()
        os.fsync(f.fileno())

    return written


def download():
    os.makedirs(os.path.dirname(DEST), exist_ok=True)

    if not os.path.exists(DEST):
        with open(DEST, 'wb') as f:
            f.truncate(EXPECTED)
        print(f"Created sparse file: {EXPECTED / 1024 / 1024:.0f} MB")

    progress_file = DEST + '.progress'
    if os.path.exists(progress_file):
        with open(progress_file, 'r') as f:
            completed_bytes = int(f.read().strip())
    else:
        completed_bytes = 0

    total_start = time.time()
    cdn_url = None
    cdn_time = 0
    retry_count = 0

    while completed_bytes < EXPECTED:
        if cdn_url is None or time.time() - cdn_time > 2400:
            try:
                print("  Resolving CDN URL...", flush=True)
                cdn_url = resolve_cdn_url()
                cdn_time = time.time()
                retry_count = 0
            except Exception as e:
                print(f"  URL resolution failed: {e}, retry in 10s...")
                time.sleep(10)
                continue

        seg_start = completed_bytes
        seg_end = min(completed_bytes + SEGMENT_SIZE, EXPECTED)
        seg_size = seg_end - seg_start
        pct = completed_bytes * 100 / EXPECTED
        elapsed = time.time() - total_start
        speed = completed_bytes / elapsed if elapsed > 1 else 0
        eta_s = (EXPECTED - completed_bytes) / speed if speed > 0 else 0

        print(f"  [{pct:5.1f}%] {completed_bytes/1024/1024:7.1f} MB | "
              f"Seg {seg_start/1024/1024:.0f}-{seg_end/1024/1024:.0f} MB | "
              f"{speed/1024:.0f} KB/s | ETA {eta_s/60:.0f}min",
              flush=True)

        try:
            n = download_segment(cdn_url, seg_start, seg_end, DEST)
            completed_bytes += n
            retry_count = 0

            with open(progress_file, 'w') as f:
                f.write(str(completed_bytes))

        except (requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.Timeout) as e:
            # Partial data may have been written via streaming
            # Re-read progress file to check if any progress was saved
            retry_count += 1
            err_msg = str(e)
            if 'IncompleteRead' in err_msg:
                import re
                m = re.search(r'(\d+) bytes read', err_msg)
                if m:
                    partial = int(m.group(1))
                    completed_bytes += partial
                    with open(progress_file, 'w') as f:
                        f.write(str(completed_bytes))
                    print(f"  Partial: +{partial/1024/1024:.1f} MB saved")
            else:
                print(f"  Error: {type(e).__name__}")

            if retry_count > 3:
                cdn_url = None
            time.sleep(min(5 * retry_count, 30))
        except Exception as e:
            retry_count += 1
            print(f"  Error: {type(e).__name__}: {e}")
            if retry_count > 5:
                cdn_url = None
            time.sleep(10)

    if os.path.exists(progress_file):
        os.remove(progress_file)

    final = os.path.getsize(DEST)
    print(f"\nDownload COMPLETE: {final / 1024 / 1024:.1f} MB")
    elapsed = time.time() - total_start
    print(f"Total time: {elapsed/60:.1f} min")


if __name__ == "__main__":
    download()
