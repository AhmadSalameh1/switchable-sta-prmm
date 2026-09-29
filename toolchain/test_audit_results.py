#!/usr/bin/env python3
"""Unit tests for audit_results.py's raw trace parsing logic.

These are regression tests for the two historical parser bugs reproduced in
audit_results.py's comments:

  1. Estimate queries with a '+/-' margin used to have their CI silently
     discarded (ci_low/ci_high left empty).
  2. Deterministic / degenerate estimate queries -- printed by verifyta
     with a '~' and no margin, e.g. "(50 runs) E(min) = ~ 100" -- used to
     fail EST_RE, fall through to the generic '0' fallback, and silently
     corrupt any nonzero deterministic value.

Also covers probability query parsing, since that's the third distinct
raw output shape the toolchain has to handle.

Run with:  python3 -m pytest test_audit_results.py -v
       or: python3 test_audit_results.py
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_results as ar


def write_trace(tmpdir: Path, name: str, content: str) -> Path:
    path = tmpdir / name
    path.write_text(content, encoding="utf-8")
    return path


class TestDeterministicValueNoMargin(unittest.TestCase):
    """Regression test for bug #2: verifyta's degenerate output format
    'E(...) = ~ 100' (no +/- margin) must parse to value=100 with
    ci_low=ci_high=100, NOT silently fall back to 0."""

    def test_deterministic_min_availability(self):
        # NB: this format is loosely described as
        # "E(...) = ~ 100", but the actual verifyta output (confirmed by
        # inspecting real raw trace files under results/raw_traces/ during
        # this audit, e.g. "...R + E.../012_estimate_..._1.txt") uses the
        # unicode APPROXIMATELY EQUAL sign '≈' (≈), which is exactly
        # what EST_APPROX_RE matches. This test uses the real glyph.
        with tempfile.TemporaryDirectory() as td:
            path = write_trace(
                Path(td), "012_estimate_E_800_50_min_min_availability_pct_all_1.txt",
                "Verifying formula 1 at line ...\n"
                "-- Formula is satisfied.\n"
                "(50 runs) E(min) = ≈ 100\n",
            )
            parsed = ar.parse_trace(path)
            self.assertEqual(parsed.value, "100")
            self.assertEqual(parsed.ci_low, "100")
            self.assertEqual(parsed.ci_high, "100")
            self.assertNotEqual(parsed.value, "0", "regression: must not silently zero out a deterministic non-zero value")

    def test_deterministic_value_with_approx_symbol(self):
        # verifyta sometimes prints the unicode APPROX sign instead of '~'.
        with tempfile.TemporaryDirectory() as td:
            path = write_trace(
                Path(td), "007_estimate_E_800_50_max_max_stockout_duration_live_all_1.txt",
                "(50 runs) E(max) = ≈ 0\n",
            )
            parsed = ar.parse_trace(path)
            self.assertEqual(parsed.value, "0")
            self.assertEqual(parsed.ci_low, "0")
            self.assertEqual(parsed.ci_high, "0")


class TestNormalEstimateWithMargin(unittest.TestCase):
    """Regression test for bug #1: the +/- margin on a normal estimate query
    must be used to compute ci_low/ci_high, not discarded."""

    def test_estimate_with_plus_minus_margin(self):
        with tempfile.TemporaryDirectory() as td:
            path = write_trace(
                Path(td), "003_estimate_E_800_50_max_max_safe_stock_recovery_time_live_all_1.txt",
                "Verifying formula 3 at line ...\n"
                "-- Formula is satisfied.\n"
                "(50 runs) E(max) = 8.66 ± 0.450673 (95% CI)\n",
            )
            parsed = ar.parse_trace(path)
            self.assertEqual(parsed.value, "8.66")
            self.assertAlmostEqual(float(parsed.ci_low), 8.66 - 0.450673, places=5)
            self.assertAlmostEqual(float(parsed.ci_high), 8.66 + 0.450673, places=5)

    def test_ascii_plus_minus_variant(self):
        # Some raw traces may use the ASCII "+/-" spelled out; EST_RE only
        # matches the unicode '±' glyph verifyta actually emits, so this test
        # documents that ASCII "+/-" is NOT matched by EST_RE and falls back
        # to EST_APPROX_RE (which has no '+/-' alternative either) -- i.e.
        # confirms the regex is glyph exact rather than silently accepting a
        # different looking margin marker it was never designed for.
        with tempfile.TemporaryDirectory() as td:
            path = write_trace(
                Path(td), "003_estimate_E_800_50_max_x_1.txt",
                "(50 runs) E(max) = 8.66 +/- 0.450673 (95% CI)\n",
            )
            parsed = ar.parse_trace(path)
            # EST_APPROX_RE will match "E(max) = 8.66" ignoring the trailing
            # "+/- 0.45..." text (no err group), giving ci_low=ci_high=8.66 --
            # this documents current behavior, it is not asserting it is the
            # ideal outcome.
            self.assertEqual(parsed.value, "8.66")


class TestProbabilityQuery(unittest.TestCase):
    def test_probability_query_parses_value_and_ci(self):
        with tempfile.TemporaryDirectory() as td:
            path = write_trace(
                Path(td), "001_probability_Pr_800_sim_time_800_service_ratio_pct_95_1.txt",
                "Verifying formula 1 at line ...\n"
                "-- Formula is satisfied.\n"
                "(310/400 runs) Pr(sim_time<=800 and service_ratio_pct>=95) in [0.724413,0.819002] (95% CI)\n",
            )
            parsed = ar.parse_trace(path)
            self.assertAlmostEqual(float(parsed.value), 310 / 400, places=6)
            self.assertEqual(parsed.ci_low, "0.724413")
            self.assertEqual(parsed.ci_high, "0.819002")
            self.assertEqual(parsed.runs, "400")


class TestSeedCapture(unittest.TestCase):
    def test_seed_is_captured(self):
        with tempfile.TemporaryDirectory() as td:
            path = write_trace(
                Path(td), "002_estimate_E_800_50_max_avg_lead_time_1.txt",
                "Seed is 1780486213\n"
                "(50 runs) E(max) = 9.48 ± 0.14 (95% CI)\n",
            )
            parsed = ar.parse_trace(path)
            self.assertEqual(parsed.seed, "1780486213")


class TestCIOverlapSignificance(unittest.TestCase):
    def test_non_overlapping_is_significant(self):
        self.assertTrue(ar.significant((100.0, 5.0), (50.0, 5.0)))

    def test_overlapping_is_not_significant(self):
        self.assertFalse(ar.significant((100.0, 20.0), (110.0, 20.0)))

    def test_touching_bounds_count_as_overlap(self):
        # [95,105] and [105,115] touch at 105 -> overlap -> not significant
        self.assertFalse(ar.significant((100.0, 5.0), (110.0, 5.0)))

    def test_zero_width_ci_no_overlap(self):
        self.assertTrue(ar.significant((0.0, 0.0), (5.0, 0.0)))

    def test_zero_width_ci_identical_overlap(self):
        self.assertFalse(ar.significant((100.0, 0.0), (100.0, 0.0)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
