#!/usr/bin/env python
"""
This script can be used as replacement script,
with an original salt package (3007.X) installed from pip in an local environment,
to work on systems with newer python (>3.10 up to 3.13) versions by monkeypatching.

"""

import sys
import types

import salt.utils.url
import salt.utils.platform
import salt.utils.path
import salt.utils.data
import salt.version

from urllib.parse import urlunsplit
from salt.scripts import salt_call

try:
    import bcrypt

    # XXX workaround pycrypto-passlib-bcrypt
    # salt.utils.pycrypto uses passlib uses bcrypt.
    # passlib expects brcypt.__about__.__version
    # check if __version__ exists but __about__ does not
    if hasattr(bcrypt, "__version__") and not hasattr(bcrypt, "__about__"):
        # mimic the old __about__ attribute by a namespace object with __version__ in it
        bcrypt.__about__ = types.SimpleNamespace(__version__=bcrypt.__version__)
except ImportError:
    # If bcrypt isn't installed, passlib will handle it gracefully. No patch needed
    pass


def _patched_url_create(path, saltenv=None):
    """
    join `path` and `saltenv` into a 'salt://' URL.
    """
    path = path.replace("\\", "/")
    if salt.utils.platform.is_windows():
        path = salt.utils.path.sanitize_win_path(path)
    path = salt.utils.data.decode(path)

    query = f"saltenv={saltenv}" if saltenv else ""
    return f"salt://{salt.utils.data.decode(urlunsplit(('', '', path, query, '')))}"


if __name__ == "__main__":
    print(f"Python: {sys.version_info} , Salt: {salt.version.__version__}", file=sys.stderr)

    if sys.version_info > (3, 10):
        print("Monkeypatch salt.utils.url.create for Python > 3.10", file=sys.stderr)
        salt.utils.url.create = _patched_url_create

    if sys.argv[0].endswith("-script.pyw"):
        sys.argv[0] = sys.argv[0][:-11]
    elif sys.argv[0].endswith(".exe"):
        sys.argv[0] = sys.argv[0][:-4]
    sys.exit(salt_call())
