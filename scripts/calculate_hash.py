import hashlib

def calculate_id(network_name):
    """Calculates the SHA256 hash of a network name."""
    return hashlib.sha256(network_name.encode('utf-8')).hexdigest()

if __name__ == "__main__":
    print(f"pgmtls: {calculate_id('pgmtls')}")
    print(f"pgpwd: {calculate_id('pgpwd')}")
