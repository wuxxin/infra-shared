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

from collections import namedtuple
from urllib.parse import urlunsplit
from salt.scripts import salt_call

try:
    import bcrypt

    # Check if the patch for passlib is needed: __version__ exists but __about__ does not
    if hasattr(bcrypt, "__version__") and not hasattr(bcrypt, "__about__"):
        # Create a simple namespace object to mimic the old __about__ attribute
        bcrypt.__about__ = types.SimpleNamespace(__version__=bcrypt.__version__)
except ImportError:
    # If bcrypt isn't installed, passlib will handle it gracefully. No patch needed
    pass

try:
    from passlib.hash import sha512_crypt, sha256_crypt, bcrypt, md5_crypt, des_crypt

    HAS_PASSLIB = True
except ImportError:
    HAS_PASSLIB = False


# Monkeypatch salt.url.create for Python > 3.10
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


# Monkeypatch salt.utils.pycrypto.gen_hash for Python > 3.13
def _patched_gen_hash(crypt_salt=None, password=None, algorithm=None):
    """
    Patched version of gen_hash that uses passlib to emulate the crypt module
    """
    pycrypto_module = sys.modules.get("salt.utils.pycrypto")
    if not pycrypto_module:
        raise RuntimeError("The 'salt.utils.pycrypto' module was not found in sys.modules.")

    if password is None:
        password = pycrypto_module.secure_password()

    if algorithm is None:
        algorithm = "sha512"

    if algorithm not in pycrypto_module.known_methods:
        raise pycrypto_module.SaltInvocationError(
            f"Unsupported hash algorithm '{algorithm}'. Supported algorithms are: "
            f"{pycrypto_module.known_methods}"
        )

    if algorithm == "crypt" and crypt_salt and len(crypt_salt) != 2:
        pycrypto_module.log.warning("Hash salt is too long for 'crypt' hash algorithm.")

    return _patched_gen_hash_crypt(
        crypt_salt=crypt_salt, password=password, algorithm=algorithm
    )


def _patched_gen_hash_crypt(crypt_salt=None, password=None, algorithm=None):
    """
    Generates an /etc/shadow compatible hash using passlib to emulate the native crypt module
    """
    # Map algorithm names to their corresponding passlib hashers
    hashers = {
        "sha512": sha512_crypt,
        "sha256": sha256_crypt,
        "blowfish": bcrypt,
        "md5": md5_crypt,
        "crypt": des_crypt,
    }

    hasher = hashers.get(algorithm)
    if not hasher:
        raise NotImplementedError(f"Algorithm '{algorithm}' is not implemented in this patch.")

    try:
        # passlib's hash method correctly handles salt generation if crypt_salt is None
        return hasher.hash(password, salt=crypt_salt)
    except Exception as e:
        pycrypto_module = sys.modules.get("salt.utils.pycrypto")
        if pycrypto_module:
            pycrypto_module.log.error(
                f"Error hashing password with passlib for algorithm {algorithm}: {e}"
            )
        return None


def activate_pycrypto_patch():
    """
    Activates the monkeypatch for salt.utils.pycrypto
    """
    if not HAS_PASSLIB:
        print(
            "ERROR: Cannot apply patch. The 'passlib' library is not installed.",
            file=sys.stderr,
        )
        return False

    try:
        import salt.utils.pycrypto as pycrypto_module
    except ImportError:
        print(
            "ERROR: Could not import 'salt.utils.pycrypto'. Ensure SaltStack is installed.",
            file=sys.stderr,
        )
        return False

    if not hasattr(pycrypto_module, "_gen_hash_crypt"):
        print(
            "WARNING: Could not apply patch. salt.utils.pycrypto does not have func _gen_hash_crypt. Probably already patched outside.",
            file=sys.stderr,
        )
        return False

    mock_crypt_obj = types.ModuleType("crypt")
    MockMethod = namedtuple("MockMethod", ["name", "ident"])
    mock_methods_list = [
        MockMethod(name="SHA512", ident="6"),
        MockMethod(name="SHA256", ident="5"),
        MockMethod(name="BLOWFISH", ident="2a"),
        MockMethod(name="MD5", ident="1"),
        MockMethod(name="CRYPT", ident=None),
    ]
    mock_crypt_obj.methods = mock_methods_list

    pycrypto_module.HAS_CRYPT = True
    pycrypto_module.crypt = mock_crypt_obj
    pycrypto_module.methods = {m.name.lower(): m for m in mock_crypt_obj.methods}

    pycrypto_module._gen_hash_crypt = _patched_gen_hash_crypt
    pycrypto_module.gen_hash = _patched_gen_hash

    print(
        "INFO: The salt.utils.pycrypto module has been patched to use 'passlib'.",
        file=sys.stderr,
    )
    return True


def test_pycrypto():
    print("Testing salt.utils.pycrypto", file=sys.stderr)
    import salt.utils.pycrypto

    sha_hash = salt.utils.pycrypto.gen_hash(
        password="MySuperSecretPassword123!", algorithm="sha512"
    )
    print(f"\nGenerated SHA512 hash:\n{sha_hash}", file=sys.stderr)
    bf_hash = salt.utils.pycrypto.gen_hash(
        password="another-secure-password", algorithm="blowfish"
    )
    print(f"\nGenerated Blowfish (bcrypt) hash:\n{bf_hash}", file=sys.stderr)
    md5_hash = salt.utils.pycrypto.gen_hash(password="less-secure-password", algorithm="md5")
    print(f"\nGenerated MD5 hash:\n{md5_hash}", file=sys.stderr)


if __name__ == "__main__":
    if sys.version_info > (3, 10):
        if salt.version.__version__ == "3007.1":
            print(
                "Monkeypatch salt.utils.url.create for Python > 3.10, Salt 3007.1",
                file=sys.stderr,
            )
            salt.utils.url.create = _patched_url_create

    if sys.version_info > (3, 12):
        if activate_pycrypto_patch():
            print("Monkeypatch utils.pycrypto for Python > 3.12", file=sys.stderr)
        else:
            print("Warning: could not monkeypatch salt.utils.pycypto", file=sys.stderr)

        test_pycrypto()

    if sys.argv[0].endswith("-script.pyw"):
        sys.argv[0] = sys.argv[0][:-11]
    elif sys.argv[0].endswith(".exe"):
        sys.argv[0] = sys.argv[0][:-4]
    sys.exit(salt_call())
