#!/usr/bin/env python
import sys

import salt.utils.url
import salt.utils.platform
import salt.utils.path
import salt.utils.data
import salt.version

from urllib.parse import urlunsplit
from salt.scripts import salt_call


def create(path, saltenv=None):
    """
    join `path` and `saltenv` into a 'salt://' URL.
    """
    path = path.replace("\\", "/")
    if salt.utils.platform.is_windows():
        path = salt.utils.path.sanitize_win_path(path)
    path = salt.utils.data.decode(path)

    query = f"saltenv={saltenv}" if saltenv else ""
    return f'salt://{salt.utils.data.decode(urlunsplit(("", "", path, query, "")))}'


patch_ver = "3007.1"
current_ver = salt.version.__version__

if sys.version_info > (3, 10):
    if current_ver == patch_ver:
        print(f"Monkeypatch url.create for Python > 3.10 and Salt {patch_ver}")
        salt.utils.url.create = create
    else:
        print(
            f"Python > 3.10, but Salt is {current_ver}, not {patch_ver}. Skipping monkeypatch."
        )
else:
    print(f"Python version is <= 3.10 ({sys.version_info}). Skipping monkeypatch.")

if __name__ == "__main__":
    if sys.argv[0].endswith("-script.pyw"):
        sys.argv[0] = sys.argv[0][:-11]
    elif sys.argv[0].endswith(".exe"):
        sys.argv[0] = sys.argv[0][:-4]
    sys.exit(salt_call())
