"""Keep the SQLite DB alive on a Hugging Face Space, whose disk is wiped on restart.

With HF_BACKUP_REPO (private dataset repo id) and HF_TOKEN set: restore() pulls the
last snapshot before init_db, start() uploads one every HF_BACKUP_MINUTES (default 15)
and once more at exit. Without them every call is a no-op.
"""
import atexit
import os
import shutil
import sqlite3
import tempfile
import threading

from db import DB_PATH

FILE = "mealplanner.db"


def _cfg():
    repo, token = os.environ.get("HF_BACKUP_REPO"), os.environ.get("HF_TOKEN")
    return (repo, token) if repo and token else None


def snapshot(src=DB_PATH, dest=None):
    """Consistent copy of a live DB via the sqlite backup API; returns its path."""
    dest = dest or os.path.join(tempfile.mkdtemp(), FILE)
    with sqlite3.connect(src) as s, sqlite3.connect(dest) as d:
        s.backup(d)
    return dest


def restore():
    cfg = _cfg()
    if not cfg:
        return False
    from huggingface_hub import hf_hub_download
    try:
        path = hf_hub_download(cfg[0], FILE, repo_type="dataset", token=cfg[1])
    except Exception as e:   # first boot: nothing uploaded yet
        print(f"hf_backup: no snapshot restored ({e.__class__.__name__})")
        return False
    shutil.copyfile(path, DB_PATH)
    return True


def upload():
    cfg = _cfg()
    if not cfg or not os.path.exists(DB_PATH):
        return False
    from huggingface_hub import HfApi
    path = snapshot()
    try:
        HfApi(token=cfg[1]).upload_file(path_or_fileobj=path, path_in_repo=FILE,
                                        repo_id=cfg[0], repo_type="dataset",
                                        commit_message="db snapshot")
        return True
    except Exception as e:
        print(f"hf_backup: upload failed: {e}")
        return False
    finally:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


def start():
    if not _cfg():
        return False
    every = float(os.environ.get("HF_BACKUP_MINUTES", "15")) * 60
    stop = threading.Event()

    def loop():
        while not stop.wait(every):
            upload()
    threading.Thread(target=loop, daemon=True).start()
    atexit.register(lambda: (stop.set(), upload()))
    return True
