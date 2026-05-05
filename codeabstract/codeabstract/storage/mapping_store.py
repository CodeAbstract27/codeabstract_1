"""
Mapping Store

Helpers for serializing / deserializing mapping tables
and exporting session data for portability.
"""

import json
from typing import Any, Dict


def mapping_to_json(mapping: Dict[str, Any]) -> str:
    """Serialize a mapping table to a JSON string."""
    return json.dumps(mapping, indent=2, ensure_ascii=False)


def json_to_mapping(json_string: str) -> Dict[str, Any]:
    """Deserialize a JSON string to a mapping table."""
    return json.loads(json_string)


def export_session_data(session: Dict[str, Any]) -> str:
    """
    Export session data as a human-readable JSON string
    (excluding encrypted mapping and raw key for security).

    Args:
        session: Session dict from session_manager.load_session().

    Returns:
        JSON string with metadata and statistics.
    """
    export = {
        'session_id': session.get('session_id'),
        'source_file_path': session.get('source_file_path'),
        'created_at': session.get('created_at'),
        'context_window': session.get('context_window'),
        'statistics': session.get('statistics', {}),
        'note': 'Encrypted mapping and key are excluded for security.',
    }
    return json.dumps(export, indent=2, ensure_ascii=False)
