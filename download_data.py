"""Robust data downloader with resume support for bridge SHM datasets."""
import os
import sys
import time
import requests

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def download_with_resume(url, dest, expected_size=None, chunk_size=1024*1024, max_retries=200):
    """Download a file with resume support, re-reading file size from disk each attempt."""
    attempt = 0

    while True:
        downloaded = os.path.getsize(dest) if os.path.exists(dest) else 0
        if expected_size and downloaded >= expected_size:
            print(f"  Complete: {downloaded / 1024 / 1024:.1f} MB")
            return True

        attempt += 1
        if attempt > max_retries:
            print(f"  FAILED after {max_retries} attempts")
            return False

        headers = {'Range': f'bytes={downloaded}-'} if downloaded > 0 else {}
        mode = 'ab' if downloaded > 0 else 'wb'
        pct = (downloaded * 100 / expected_size) if expected_size else 0
        print(f"  [Attempt {attempt}] {downloaded/1024/1024:.1f} MB ({pct:.1f}%)", flush=True)

        try:
            resp = requests.get(url, headers=headers, stream=True, timeout=60,
                              allow_redirects=True)

            if resp.status_code == 416:
                print(f"  Range not satisfiable - likely complete")
                return True

            if resp.status_code not in (200, 206):
                print(f"  HTTP {resp.status_code}, retrying in 5s...")
                time.sleep(5)
                continue

            total = expected_size
            if not total:
                cr = resp.headers.get('content-range')
                cl = resp.headers.get('content-length')
                if cr:
                    total = int(cr.split('/')[-1])
                elif cl and downloaded == 0:
                    total = int(cl)

            last_print = time.time()
            session_bytes = 0
            with open(dest, mode) as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        f.flush()
                        downloaded += len(chunk)
                        session_bytes += len(chunk)
                        now = time.time()
                        if now - last_print >= 30:
                            pct = (downloaded * 100 / total) if total else 0
                            print(f"  {pct:.1f}% ({downloaded/1024/1024:.1f} MB)", flush=True)
                            last_print = now

            gained = session_bytes / 1024 / 1024
            print(f"  Session: +{gained:.1f} MB (total: {downloaded/1024/1024:.1f} MB)", flush=True)

            if total and downloaded >= total:
                print(f"  Download complete: {downloaded / 1024 / 1024:.1f} MB")
                return True

        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as e:
            actual = os.path.getsize(dest) if os.path.exists(dest) else 0
            print(f"  Connection error at {actual/1024/1024:.1f} MB, retry in 5s...")
            time.sleep(5)
            continue

    return False


def main():
    raw_dir = os.path.join(os.path.dirname(__file__), 'data', 'raw')

    vb_dir = os.path.join(raw_dir, 'vanersborg')
    z24_dir = os.path.join(raw_dir, 'z24')
    os.makedirs(vb_dir, exist_ok=True)
    os.makedirs(z24_dir, exist_ok=True)

    tasks = [
        ("Vanersborg DiB.zip (526 MB)",
         "https://zenodo.org/records/8300495/files/DiB.zip?download=1",
         os.path.join(vb_dir, 'DiB.zip'),
         551748539),
        ("Z-24 inputs.npy (945 MB)",
         "https://huggingface.co/datasets/thanglexuan/Z24-dataset-processed/resolve/main/inputs.npy",
         os.path.join(z24_dir, 'inputs.npy'),
         991440128),
        ("Z-24 labels.npy (small)",
         "https://huggingface.co/datasets/thanglexuan/Z24-dataset-processed/resolve/main/labels.npy",
         os.path.join(z24_dir, 'labels.npy'),
         None),
    ]

    for name, url, dest, expected in tasks:
        if os.path.exists(dest) and expected:
            actual = os.path.getsize(dest)
            if actual >= expected:
                print(f"[SKIP] {name}: already complete ({actual/1024/1024:.1f} MB)")
                continue

        print(f"\n[DOWNLOADING] {name}")
        print(f"  URL: {url}")
        ok = download_with_resume(url, dest, expected_size=expected)
        if ok:
            sz = os.path.getsize(dest) if os.path.exists(dest) else 0
            print(f"  => Saved to {dest} ({sz/1024/1024:.1f} MB)")
        else:
            print(f"  => FAILED: {name}")

    print("\n=== VERIFICATION ===")
    for name, url, dest, expected in tasks:
        if os.path.exists(dest):
            sz = os.path.getsize(dest)
            status = "OK" if (not expected or sz >= expected) else f"INCOMPLETE ({sz*100/expected:.1f}%)"
            print(f"  {status}: {os.path.basename(dest)} = {sz/1024/1024:.1f} MB")
        else:
            print(f"  MISSING: {os.path.basename(dest)}")


if __name__ == '__main__':
    main()
