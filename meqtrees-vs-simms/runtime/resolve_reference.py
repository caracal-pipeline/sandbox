#!/usr/bin/env python3
"""Capture the registry's reference-image digest and build history (no runtime).

The registry currently serves signed Docker schema 1. Its canonical digest is
reported by Docker-Content-Digest; a raw-response SHA256 is recorded separately.
"""

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import urllib.request

URL = "https://quay.io/v2/stimela2/meqtrees/manifests/cc0.2.1"


def summarize(raw, headers):
    manifest = json.loads(raw)
    if manifest.get("schemaVersion") != 1:
        raise ValueError(
            "Expected schema 1 history; inspect changed registry response before proceeding"
        )
    history = []
    for layer, entry in zip(manifest["fsLayers"], manifest["history"]):
        config = json.loads(entry["v1Compatibility"])
        history.append(
            {
                "layer": layer["blobSum"],
                "created": config.get("created"),
                "command": config.get("container_config", {}).get("Cmd"),
            }
        )
    return {
        "schema_version": 1,
        "status": "registry_metadata_only_runtime_unverified",
        "captured_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_url": URL,
        "image": "quay.io/stimela2/meqtrees:cc0.2.1",
        "registry_digest": headers.get("docker-content-digest"),
        "response_body_sha256": hashlib.sha256(raw).hexdigest(),
        "manifest_schema": manifest["schemaVersion"],
        "architecture": manifest.get("architecture"),
        "history_newest_first": history,
        "warning": "Tag resolution is current evidence, not proof of an earlier mkpsim installation. Build commands do not identify installed package versions or source commits.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error(
            "--output must be a fresh directory; existing evidence will not be overwritten"
        )
    request = urllib.request.Request(
        URL, headers={"Accept": "application/vnd.docker.distribution.manifest.v1+json"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
        headers = {key.lower(): value for key, value in response.headers.items()}
    report = summarize(raw, headers)
    if not report["registry_digest"]:
        raise ValueError("Registry did not provide Docker-Content-Digest")
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "reference-manifest.json").write_bytes(raw)
    (args.output / "reference-image.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(report["registry_digest"])


if __name__ == "__main__":
    main()
