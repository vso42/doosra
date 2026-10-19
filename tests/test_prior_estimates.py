"""Prior public estimates stay identifiable and cannot overwrite corrected quotes."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("prior_estimates_build", Path(__file__).resolve().parents[1] / "build.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class PriorEstimateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        prior = {"pairs": {"2": {"block": 42, "block_timestamp_utc": None,
                                  "bands": {"1": {"amount": 10., "usd": 1000., "kind": "modeled"}}}}}
        self.prior = self.folder / "prior-public-figures.json"
        self.prior.write_text(json.dumps(prior))
        self.results = {"publication_policy": "corrected_with_prior_estimates", "pairs": {},
                        "prior_publication": {"path": "site/data/prior-public-figures.json",
                            "sha256": hashlib.sha256(self.prior.read_bytes()).hexdigest()}}
        self.bands = {"pairs": {"2": {"block": 42, "block_timestamp_utc": None,
                     "bands": {"1": {"amount": 10., "usd": 1000., "kind": "prior_modeled",
                         "native_validated": False,
                         "validation_level": "earlier_public_model_awaiting_corrected_rerun"}}}}}

    def tearDown(self):
        self.temp.cleanup()

    def validate(self):
        results, bands = self.folder / "solver-results.json", self.folder / "bands.json"
        results.write_text(json.dumps(self.results))
        bands.write_text(json.dumps(self.bands))
        build.validate_newer_publication(bands, results)

    def test_exact_prior_value_passes_with_pending_label(self):
        self.validate()

    def test_changed_prior_amount_is_rejected(self):
        self.bands["pairs"]["2"]["bands"]["1"]["usd"] = 1001.
        with self.assertRaisesRegex(ValueError, "actual public figure"):
            self.validate()

    def test_another_snapshot_is_rejected(self):
        self.bands["pairs"]["2"]["block"] = 43
        with self.assertRaisesRegex(ValueError, "another snapshot"):
            self.validate()

    def test_prior_value_cannot_be_labeled_corrected(self):
        self.bands["pairs"]["2"]["bands"]["1"]["kind"] = "modeled"
        with self.assertRaisesRegex(ValueError, "no corrected solver evidence"):
            self.validate()

    def test_prior_value_cannot_invent_raw_quantities(self):
        self.bands["pairs"]["2"]["bands"]["1"]["amount_in_raw"] = "10000000"
        with self.assertRaisesRegex(ValueError, "explicit pending label"):
            self.validate()

    def test_changed_prior_publication_is_rejected(self):
        self.prior.write_text('{"pairs":{}}')
        with self.assertRaisesRegex(ValueError, "pinned publication"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
