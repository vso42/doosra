"""One active, immutable result package for the website.

The active pointer is changed only after a complete package has been checked.
Legacy exports beside it are never rendering inputs. A shared lock protects
both activation and rendering; compare-and-swap prevents a stale publisher
from replacing a newer publication.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
import tempfile

DATA = Path(__file__).resolve().parent / "data"
POINTER = "current-publication.json"
FILES = ("bands.json", "solver-results.json", "chain-snapshots.json",
         "solver-publication-policy.json", "prior-public-figures.json")
MANIFEST = "solver-publication-manifest.json"
_mutex = threading.RLock()
_local = threading.local()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@contextmanager
def locked():
    DATA.mkdir(parents=True, exist_ok=True)
    with _mutex:
        depth = getattr(_local, "depth", 0)
        if not depth:
            _local.fd = open(DATA / ".publication.lock", "a")
            fcntl.flock(_local.fd, fcntl.LOCK_EX)
        _local.depth = depth + 1
        try:
            yield
        finally:
            _local.depth -= 1
            if not _local.depth:
                fcntl.flock(_local.fd, fcntl.LOCK_UN)
                _local.fd.close()


def pointer_token():
    path = DATA / POINTER
    return digest(path.read_bytes()) if path.exists() else None


def checked_package(folder, expected_manifest=None):
    folder = Path(folder).resolve()
    manifest_path = folder / MANIFEST
    raw = manifest_path.read_bytes()
    if expected_manifest is not None and digest(raw) != expected_manifest:
        raise ValueError("Active publication manifest changed")
    manifest = json.loads(raw)
    if set(FILES) - set(manifest.get("files", {})):
        raise ValueError("Publication package is missing required source files")
    for name, record in manifest["files"].items():
        if Path(name).name != name:
            raise ValueError("Publication package paths must be plain filenames")
        path = folder / name
        if path.is_symlink():
            raise ValueError("Publication package cannot contain symlinks")
        data = path.read_bytes()
        if digest(data) != record["sha256"] or len(data) != record["bytes"]:
            raise ValueError(f"Publication package file changed: {name}")
    return manifest


def active_directory():
    pointer = DATA / POINTER
    if not pointer.exists():
        return DATA
    record = json.loads(pointer.read_bytes())
    relative = Path(record["directory"])
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("publications",):
        raise ValueError("Active publication must be inside data/publications")
    if (DATA / "publications").is_symlink():
        raise ValueError("Publication root cannot be a symlink")
    folder = DATA / relative
    if folder.is_symlink() or folder.resolve().parent != (DATA / "publications").resolve():
        raise ValueError("Invalid active publication directory")
    checked_package(folder, record["manifest_sha256"])
    bands = json.loads((folder / "bands.json").read_bytes())
    versions = {pid: {"block": value.get("block"),
        "bands_sha256": digest(canonical(value))} for pid, value in bands["pairs"].items()}
    if versions != record["pair_versions"]:
        raise ValueError("Active per-pair results differ from the publication pointer")
    return folder


def reject_legacy_publish():
    if (DATA / POINTER).exists():
        raise RuntimeError("Legacy publication is disabled. Use scripts/publish_saved_current_pair_site.py; "
                           "the site reads only data/current-publication.json.")


def activate(folder, *, expected_token, changed_pairs, render):
    """Activate a checked complete bundle, then render while holding the lock."""
    with locked():
        if pointer_token() != expected_token:
            raise ValueError("Publication changed while preparing; rebase on the active results")
        previous_dir = active_directory()
        previous_bands = json.loads((previous_dir / "bands.json").read_bytes())
        previous_rich = json.loads((previous_dir / "solver-results.json").read_bytes())
        folder = Path(folder).resolve()
        manifest = checked_package(folder)
        bands = json.loads((folder / "bands.json").read_bytes())
        rich = json.loads((folder / "solver-results.json").read_bytes())
        permitted = set(map(str, changed_pairs))
        if set(previous_bands["pairs"]) != set(bands["pairs"]):
            raise ValueError("A pair update cannot silently change website coverage")
        actual = {pid for pid in bands["pairs"]
                  if bands["pairs"][pid] != previous_bands["pairs"][pid]}
        if actual != permitted:
            raise ValueError(f"Publication changes unexpected pair results: {sorted(actual)}")
        if permitted:
            approval = manifest.get("activation_review", {})
            if approval.get("baseline_current_publication_token") != expected_token:
                raise ValueError("Independent review belongs to another publication baseline")
            review_name = approval.get("review_file")
            if review_name not in manifest["files"] or Path(review_name).name != review_name:
                raise ValueError("Independent source review must be pinned inside the publication package")
            review = json.loads((folder / review_name).read_bytes())
            if (review.get("passed") is not True
                    or review.get("baseline_current_publication_token") != expected_token):
                raise ValueError("Pinned source review does not approve the current publication baseline")
            for pid in permitted:
                old_pair_sha = digest(canonical(previous_bands["pairs"][pid]))
                if approval.get("baseline_pair_bands_sha256", {}).get(pid) != old_pair_sha:
                    raise ValueError("Independent review belongs to another pair result generation")
                if review.get("baseline_pair_bands_sha256") != old_pair_sha:
                    raise ValueError("Pinned review belongs to another pair result generation")
                old_summary = previous_rich.get("latest_pair_updates", {}).get(pid, {}).get("summary", {}).get("sha256")
                if approval.get("baseline_latest_summary", {}).get(pid) != old_summary:
                    raise ValueError("Independent review does not supersede the active source summary")
                if review.get("baseline_latest_summary") != old_summary:
                    raise ValueError("Pinned review does not supersede the active source summary")
                if review.get("candidate_pair_bands_sha256") != digest(canonical(bands["pairs"][pid])):
                    raise ValueError("Pinned review does not approve the incoming pair amounts")
                if review.get("candidate_solver_pair_sha256") != digest(canonical(rich["pairs"][pid])):
                    raise ValueError("Pinned review does not approve the incoming solver evidence")
                incoming_summary = rich.get("latest_pair_updates", {}).get(pid, {}).get("summary", {}).get("sha256")
                if review.get("summary", {}).get("sha256") != incoming_summary:
                    raise ValueError("Pinned review does not approve the incoming source summary")
        for pid, entry in bands["pairs"].items():
            old = previous_bands["pairs"][pid]
            if entry.get("chain_id") != old.get("chain_id"):
                raise ValueError("Pair chain identity changed")
            if int(entry.get("block", 0)) < int(old.get("block", 0)):
                raise ValueError(f"Pair {pid}: an older block cannot replace current results")
            if pid not in permitted and rich["pairs"].get(pid) != previous_rich["pairs"].get(pid):
                raise ValueError(f"Pair {pid}: unrequested solver evidence changed")
            if pid in permitted:
                for key in ("collateral_addr", "debt_addr", "chain_id"):
                    if rich["pairs"][pid].get(key) != previous_rich["pairs"][pid].get(key):
                        raise ValueError(f"Pair {pid}: token or chain identity changed")
        manifest_sha = digest((folder / MANIFEST).read_bytes())
        releases = DATA / "publications"
        releases.mkdir(exist_ok=True)
        destination = releases / manifest_sha
        if destination.exists():
            checked_package(destination, manifest_sha)
        else:
            temporary = releases / (manifest_sha + ".pending")
            temporary.mkdir(exist_ok=True)
            for name in (*manifest["files"], MANIFEST):
                shutil.copyfile(folder / name, temporary / name)
            checked_package(temporary, manifest_sha)
            os.replace(temporary, destination)
        old_pointer = json.loads((DATA / POINTER).read_bytes()) if expected_token is not None else {}
        record = {"schema_version": 1, "generation": old_pointer.get("generation", 0) + 1,
            "activated_at_utc": datetime.now(timezone.utc).isoformat(),
            "directory": str(destination.relative_to(DATA)), "manifest_sha256": manifest_sha,
            "previous_pointer_sha256": expected_token, "changed_pair_ids": sorted(permitted),
            "pair_versions": {pid: {"block": value.get("block"),
                "bands_sha256": digest(canonical(value))} for pid, value in bands["pairs"].items()}}
        # Publication is a transaction under the shared lock. A failed build
        # restores the previous pointer and generated files before releasing it.
        previous_pointer = (DATA / POINTER).read_bytes() if expected_token is not None else None
        docs = DATA.parent / "docs"
        with tempfile.TemporaryDirectory(prefix=".publication-rollback-", dir=DATA) as backup_text:
            backup = Path(backup_text) / "docs"
            had_docs = docs.exists()
            if had_docs:
                shutil.copytree(docs, backup)
            temporary_pointer = DATA / (POINTER + ".pending")
            temporary_pointer.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
            os.replace(temporary_pointer, DATA / POINTER)
            try:
                render()
            except BaseException:
                if previous_pointer is None:
                    (DATA / POINTER).unlink(missing_ok=True)
                else:
                    temporary_pointer.write_bytes(previous_pointer)
                    os.replace(temporary_pointer, DATA / POINTER)
                if docs.exists():
                    shutil.rmtree(docs)
                if had_docs:
                    os.replace(backup, docs)
                raise
        return record
