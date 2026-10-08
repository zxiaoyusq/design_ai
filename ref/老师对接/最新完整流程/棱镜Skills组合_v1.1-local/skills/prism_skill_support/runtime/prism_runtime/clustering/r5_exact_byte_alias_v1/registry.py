"""Pins for the unchanged consumers and R5 producer; no source rewriting."""
from pathlib import Path
from ..id_reference_board_v5.common import checked, read


def dependencies():
    manifest = read(Path(__file__).with_name("dependencies.json"))
    def resolve(value):
        if isinstance(value, dict):
            if set(value) == {"path", "sha256"}:
                value["path"] = str((Path(__file__).parent / value["path"]).resolve())
            else:
                for child in value.values(): resolve(child)
        elif isinstance(value, list):
            for child in value: resolve(child)
    resolve(manifest)
    for ref in manifest["files"]:
        checked(ref, False)
    return manifest
