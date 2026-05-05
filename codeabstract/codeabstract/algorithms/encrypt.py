"""
ENCRYPT/DECRYPT Algorithm Implementation

Implements formal Algorithm 4 from specification.

Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256)
for secure mapping table storage.
"""

import json
from typing import Dict, Tuple

from cryptography.fernet import Fernet, InvalidToken


def encrypt_mapping(mapping_table: Dict) -> Tuple[bytes, bytes]:
    """
    ENCRYPT(M) — Secure Mapping Encryption.

    Generates a random Fernet key, serializes the mapping table
    to JSON, and encrypts it.

    Args:
        mapping_table: Mapping table M (dict of token → entry).

    Returns:
        Tuple of (M̃, K):
        - encrypted_mapping: Encrypted bytes M̃
        - encryption_key: Fernet key K (url-safe base64)

    Implements:
        ENCRYPT from Algorithm 4.
    """
    # Step 1: Generate 256-bit Fernet key
    encryption_key = Fernet.generate_key()

    # Step 2: Serialize mapping to JSON
    json_string = json.dumps(mapping_table, indent=2, ensure_ascii=False)
    json_bytes = json_string.encode('utf-8')

    # Step 3: Encrypt using AES-128-CBC + HMAC-SHA256 (Fernet)
    cipher = Fernet(encryption_key)
    encrypted_mapping = cipher.encrypt(json_bytes)

    # Step 4: Return encrypted data and key
    return encrypted_mapping, encryption_key


def decrypt_mapping(
    encrypted_mapping: bytes,
    encryption_key: bytes
) -> Dict:
    """
    DECRYPT(M̃, K) — Secure Mapping Decryption.

    Verifies the HMAC, decrypts the mapping data, and
    deserializes the JSON back to a Python dict.

    Args:
        encrypted_mapping: Encrypted mapping M̃ (bytes).
        encryption_key: Fernet key K (bytes).

    Returns:
        Mapping table M (dict).

    Raises:
        ValueError: If decryption fails (wrong key or corrupted data).

    Implements:
        DECRYPT from Algorithm 4.
    """
    # Create cipher with the provided key
    cipher = Fernet(encryption_key)

    try:
        # Step 1: Verify HMAC and decrypt
        json_bytes = cipher.decrypt(encrypted_mapping)
    except InvalidToken as e:
        raise ValueError(
            "Decryption failed — invalid key or corrupted data"
        ) from e
    except Exception as e:
        raise ValueError(
            f"Decryption failed: {e}"
        ) from e

    # Step 2: Deserialize JSON to mapping table
    json_string = json_bytes.decode('utf-8')
    mapping_table = json.loads(json_string)

    return mapping_table
