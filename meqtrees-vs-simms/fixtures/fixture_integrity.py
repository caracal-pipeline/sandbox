"""Stable hashes of scientific table contents, excluding volatile storage/lock files."""

import hashlib
import json
from pathlib import Path

import numpy as np
from casacore.tables import table

TABLES = (
    "MAIN",
    "ANTENNA",
    "FEED",
    "FIELD",
    "POINTING",
    "SPECTRAL_WINDOW",
    "POLARIZATION",
    "DATA_DESCRIPTION",
    "OBSERVATION",
    "PROCESSOR",
)


def snapshot_ms(path):
    snapshot = {}
    for name in TABLES:
        location = Path(path) if name == "MAIN" else Path(path) / name
        with table(str(location), ack=False) as tab:
            columns = {}
            for column in sorted(tab.colnames()):
                array = np.asarray(tab.getcol(column))
                payload = (
                    json.dumps(array.tolist(), separators=(",", ":")).encode()
                    if array.dtype.kind in "OUS"
                    else np.ascontiguousarray(array).tobytes()
                )
                columns[column] = {
                    "shape": list(array.shape),
                    "dtype": array.dtype.str,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "keywords": tab.getcolkeywords(column),
                }
            snapshot[name] = {"rows": tab.nrows(), "columns": columns}
    snapshot = json.loads(json.dumps(snapshot, default=lambda value: value.tolist()))
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    return {"sha256": hashlib.sha256(payload).hexdigest(), "tables": snapshot}
