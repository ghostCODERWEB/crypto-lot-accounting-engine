import unittest, copy, json
from decimal import Decimal
from pathlib import Path
from cryptolab import analyze
from cryptolab.engine import *

EXAMPLE = json.loads(Path("examples/input.json").read_text())


class DomainTests(unittest.TestCase):
    def test_partial_basis(self):
        self.assertEqual(Decimal(analyze(EXAMPLE)["realized_gain"]), 290)

    def test_transfer_continuity(self):
        self.assertEqual(
            Decimal(analyze(EXAMPLE)["positions"]["hot:ETH"]["basis"]), 500
        )

    def test_lifo(self):
        d = copy.deepcopy(EXAMPLE)
        d["method"] = "LIFO"
        self.assertEqual(Decimal(analyze(d)["realized_gain"]), -210)

    def test_insufficient_inventory(self):
        d = copy.deepcopy(EXAMPLE)
        d["events"][-1]["quantity"] = "5"
        with self.assertRaises(ValueError):
            analyze(d)

    def test_fee_basis(self):
        d = copy.deepcopy(EXAMPLE)
        d["events"][0]["fee"] = "200"
        self.assertEqual(Decimal(analyze(d)["realized_gain"]), 240)
