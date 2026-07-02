"""Download Vanersborg DiB.zip with robust resume support."""
import os
import sys
import time
import requests

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

URL = "https://zenodo.org/records/8300495/files/DiB.zip?download=1"
DEST = os.path.join(os.path.dirname(__file__), "data", "raw", "vanersborg", "DiB.zip")
EXPECTED = 551748539
CHUNK = 1024 * 1024


def download():
    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    attempt = 0

    while True:
        downloaded = os.path.getsize(DEST) if os.path.exists(DEST) else 0
        if downloaded >= EXPECTED:
            print(f"Complete: {downloaded / 1024 / 1024:.1f} MB")
            return

        attempt += 1
        if attempt > 500:
            print("Too many attempts")
            break

        pct = downloaded * 100 / EXPECTED
        print(f"[Attempt {attempt}] {downloaded/1024/1024:.1f}/{EXPECTED/1024/1024:.0f} MB ({pct:.1f}%)", flush=True)

        headers = {'Range': f'bytes={downloaded}-'} if downloaded > 0 else {}

        try:
            resp = requests.get(URL, headers=headers, stream=True, timeout=60, allow_redirects=True)

            if resp.status_code == 416:
                print("  Range not satisfiable - likely complete")
                return

            if resp.status_code == 200 and downloaded > 0:
                print(f"  Server returned 200 (no range support), restarting from 0...")
                mode = 'wb'
                downloaded = 0
            elif resp.status_code == 206:
                mode = 'ab'
            elif resp.status_code == 200:
                mode = 'wb'
            else:
                print(f"  HTTP {resp.status_code}, retry in 5s...")
                time.sleep(5)
                continue

            last_print = time.time()
            session_bytes = 0
            with open(DEST, mode) as f:
                flush_cnt = 0
                for chunk in resp.iter_content(chunk_size=CHUNK):
                    if chunk:
                        f.write(chunk)
                        flush_cnt += 1
                        if flush_cnt % 4 == 0:
                            f.flush()
                            os.fsync(f.fileno())
                        downloaded += len(chunk)
                        session_bytes += len(chunk)
                        now = time.time()
                        if now - last_print >= 30:
                            pct = downloaded * 100 / EXPECTED
                            print(f"  {pct:.1f}% ({downloaded/1024/1024:.1f} MB)", flush=True)
                            last_print = now

            gained = session_bytes / 1024 / 1024
            print(f"  Session: +{gained:.1f} MB (total: {downloaded/1024/1024:.1f} MB)", flush=True)

        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError):
            actual = os.path.getsize(DEST) if os.path.exists(DEST) else 0
            print(f"  Connection error at {actual/1024/1024:.1f} MB, retry in 5s...")
            time.sleep(5)

    final = os.path.getsize(DEST) if os.path.exists(DEST) else 0
    if final >= EXPECTED:
        print(f"\nVanersborg download COMPLETE: {final / 1024 / 1024:.1f} MB")
    else:
        print(f"\nIncomplete: {final / 1024 / 1024:.1f} / {EXPECTED / 1024 / 1024:.0f} MB")


if __name__ == "__main__":
    download()
