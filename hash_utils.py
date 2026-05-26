from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Dict, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_text_hash(value: str, *, algorithm: str = "md5") -> str:
    digest = hashlib.new(algorithm)
    digest.update((value or "").encode("utf-8"))
    return digest.hexdigest()


def build_hash_record(
    value: str,
    *,
    label: str = "content_hash",
    algorithm: str = "md5",
    recorded_at: Optional[str] = None,
) -> Dict[str, str]:
    timestamp = recorded_at or utc_now_iso()
    return {
        label: compute_text_hash(value, algorithm=algorithm),
        f"{label}_algorithm": algorithm,
        f"{label}_timestamp": timestamp,
    }


def merge_hash_metadata(
    metadata: Optional[Dict],
    value: str,
    *,
    label: str = "content_hash",
    algorithm: str = "md5",
    recorded_at: Optional[str] = None,
) -> Dict:
    merged = dict(metadata or {})
    merged.update(
        build_hash_record(
            value,
            label=label,
            algorithm=algorithm,
            recorded_at=recorded_at,
        )
    )
    return merged
