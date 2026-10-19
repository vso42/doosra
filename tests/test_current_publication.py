"""Old exports, stale publishers and changed evidence cannot replace the site."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("publication_test_build", ROOT / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
publication = build.publication


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def package(folder, block, amount):
    pair = {"chain_id": 1, "collateral_addr": "wbtc", "debt_addr": "usdc", "cases": []}
    write(folder / "bands.json", {"pairs": {"57": {"block": block, "chain_id": 1,
          "bands": {"3": {"amount": amount, "usd": amount, "kind": "modeled"}}}}})
    write(folder / "solver-results.json", {"pairs": {"57": pair}})
    for name in ("chain-snapshots.json", "solver-publication-policy.json", "prior-public-figures.json"):
        write(folder / name, {})
    records = {}
    for name in publication.FILES:
        data = (folder / name).read_bytes()
        records[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    write(folder / publication.MANIFEST, {"files": records})


def approve(folder, token):
    old = json.loads((publication.active_directory() / "bands.json").read_text())["pairs"]["57"]
    old_sha = publication.digest(publication.canonical(old))
    review = {"passed": True, "baseline_current_publication_token": token,
              "baseline_pair_bands_sha256": old_sha, "baseline_latest_summary": None}
    candidate_bands = json.loads((folder / "bands.json").read_text())["pairs"]["57"]
    candidate_pair = json.loads((folder / "solver-results.json").read_text())["pairs"]["57"]
    review.update(candidate_pair_bands_sha256=publication.digest(publication.canonical(candidate_bands)),
        candidate_solver_pair_sha256=publication.digest(publication.canonical(candidate_pair)), summary={"sha256": None})
    write(folder / "source-review.json", review)
    manifest = json.loads((folder / publication.MANIFEST).read_text())
    data = (folder / "source-review.json").read_bytes()
    manifest["files"]["source-review.json"] = {"sha256": publication.digest(data), "bytes": len(data)}
    manifest["activation_review"] = {"baseline_current_publication_token": token,
        "baseline_pair_bands_sha256": {"57": old_sha}, "baseline_latest_summary": {"57": None},
        "review_file": "source-review.json"}
    write(folder / publication.MANIFEST, manifest)


class CurrentPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name) / "data"
        self.patch = patch.object(publication, "DATA", self.data)
        self.patch.start()
        package(self.data, 100, 10)
        self.initial = Path(self.temp.name) / "initial"
        package(self.initial, 100, 10)
        publication.activate(self.initial, expected_token=None, changed_pairs=[], render=lambda: None)

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_legacy_files_never_become_active_inputs(self):
        active = publication.active_directory()
        package(self.data, 1, 999999)
        self.assertEqual(publication.active_directory(), active)
        values = json.loads((active / "bands.json").read_text())
        self.assertEqual(values["pairs"]["57"]["block"], 100)

    def test_stale_publisher_cannot_overwrite_new_result(self):
        token = publication.pointer_token()
        newer, stale = Path(self.temp.name) / "new", Path(self.temp.name) / "stale"
        package(newer, 102, 20)
        package(stale, 101, 15)
        approve(newer, token)
        approve(stale, token)
        publication.activate(newer, expected_token=token, changed_pairs=[57], render=lambda: None)
        with self.assertRaisesRegex(ValueError, "changed while preparing"):
            publication.activate(stale, expected_token=token, changed_pairs=[57], render=lambda: None)
        self.assertEqual(json.loads((publication.active_directory() / "bands.json").read_text())
                         ["pairs"]["57"]["block"], 102)

    def test_old_block_rejected_even_with_fresh_pointer_token(self):
        old = Path(self.temp.name) / "old"
        package(old, 99, 1000)
        approve(old, publication.pointer_token())
        with self.assertRaisesRegex(ValueError, "older block"):
            publication.activate(old, expected_token=publication.pointer_token(), changed_pairs=[57], render=lambda: None)

    def test_changed_package_is_not_rendered(self):
        folder = publication.active_directory()
        write(folder / "bands.json", {"pairs": {"57": {"block": 1}}})
        with self.assertRaisesRegex(ValueError, "file changed"):
            publication.active_directory()

    def test_edited_candidate_cannot_reuse_another_candidates_review(self):
        token = publication.pointer_token()
        candidate = Path(self.temp.name) / "edited-candidate"
        package(candidate, 101, 20)
        approve(candidate, token)
        bands = json.loads((candidate / "bands.json").read_text())
        bands["pairs"]["57"]["bands"]["3"]["amount"] = 999999
        write(candidate / "bands.json", bands)
        manifest = json.loads((candidate / publication.MANIFEST).read_text())
        raw = (candidate / "bands.json").read_bytes()
        manifest["files"]["bands.json"] = {"sha256": publication.digest(raw), "bytes": len(raw)}
        write(candidate / publication.MANIFEST, manifest)
        with self.assertRaisesRegex(ValueError, "incoming pair amounts"):
            publication.activate(candidate, expected_token=token, changed_pairs=[57], render=lambda: None)

    def test_failed_render_restores_pointer_and_published_documents(self):
        token = publication.pointer_token()
        docs = self.data.parent / "docs"
        write(docs / "data/figures.json", {"generation": "old"})
        (docs / "index.html").write_text("old page")
        candidate = Path(self.temp.name) / "failed-render"
        package(candidate, 101, 20)
        approve(candidate, token)

        def fail():
            (docs / "index.html").write_text("half rendered new page")
            raise RuntimeError("render failed")

        with self.assertRaisesRegex(RuntimeError, "render failed"):
            publication.activate(candidate, expected_token=token, changed_pairs=[57], render=fail)
        self.assertEqual(publication.pointer_token(), token)
        self.assertEqual((docs / "index.html").read_text(), "old page")
        self.assertEqual(json.loads((docs / "data/figures.json").read_text()), {"generation": "old"})

    def test_old_same_block_review_cannot_restore_earlier_math(self):
        token = publication.pointer_token()
        corrected, stale = Path(self.temp.name) / "corrected", Path(self.temp.name) / "earlier-math"
        package(corrected, 101, 20)
        package(stale, 101, 12)
        approve(corrected, token)
        approve(stale, token)
        publication.activate(corrected, expected_token=token, changed_pairs=[57], render=lambda: None)
        with self.assertRaisesRegex(ValueError, "review belongs to another publication baseline"):
            publication.activate(stale, expected_token=publication.pointer_token(), changed_pairs=[57], render=lambda: None)

    def test_explicit_old_input_cannot_write_published_docs(self):
        with self.assertRaisesRegex(ValueError, "explicit inputs are for previews"):
            build.build(self.data / "bands.json", out=build.OUT)

    def test_legacy_publish_is_disabled_before_writes(self):
        with self.assertRaisesRegex(RuntimeError, "Legacy publication is disabled"):
            publication.reject_legacy_publish()

    def test_concurrent_preparations_only_one_can_activate_and_render(self):
        token = publication.pointer_token()
        folders = [Path(self.temp.name) / "a", Path(self.temp.name) / "b"]
        for i, folder in enumerate(folders):
            package(folder, 101+i, 20+i)
            approve(folder, token)
        barrier = threading.Barrier(2)
        rendered, rejected = [], []

        def publish(folder):
            barrier.wait()
            try:
                publication.activate(folder, expected_token=token, changed_pairs=[57],
                    render=lambda: rendered.append(publication.pointer_token()))
            except ValueError:
                rejected.append(True)

        threads = [threading.Thread(target=publish, args=(folder,)) for folder in folders]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive(), "Publication lock deadlocked")
        self.assertEqual((len(rendered), len(rejected)), (1, 1))
        self.assertEqual(publication.pointer_token(), rendered[0])


if __name__ == "__main__":
    unittest.main()
