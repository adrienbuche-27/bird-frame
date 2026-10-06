#!/usr/bin/env python3
"""Focused path and transport checks for the workstation cutout upgrader."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import types
import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "avian" / "scripts" / "upgrade_cutouts.py"
SPEC = importlib.util.spec_from_file_location("upgrade_cutouts", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UpgradeCutoutsTest(unittest.TestCase):
    def test_accepts_station_target_and_relative_repo(self) -> None:
        self.assertEqual(MODULE.validate_target("monalisa@birdnet.local"),
                         "monalisa@birdnet.local")
        self.assertEqual(MODULE.validate_repo("BirdNET-Pi"), "BirdNET-Pi")
        self.assertEqual(MODULE.validate_repo("stations/BirdNET-Pi/"),
                         "stations/BirdNET-Pi")

    def test_rejects_shell_and_path_injection(self) -> None:
        for value in ("birdnet.local", "bird@host;touch /tmp/pwn", "-oProxyCommand=x@host"):
            with self.subTest(target=value), self.assertRaises(ValueError):
                MODULE.validate_target(value)
        for value in ("/BirdNET-Pi", "../BirdNET-Pi", "BirdNET-Pi/../root", "BirdNET Pi"):
            with self.subTest(repo=value), self.assertRaises(ValueError):
                MODULE.validate_repo(value)
        for value in ("../secret", "bird;id", "bird name", ""):
            with self.subTest(slug=value), self.assertRaises(ValueError):
                MODULE.validate_slug(value)

    def test_reads_private_inputs_over_ssh(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout=b'{"Bird": "chroma"}', stderr=b"")
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run:
            data = MODULE.read_remote(
                "bird@birdnet.local",
                "BirdNET-Pi/avian/assets/illustrations/cuts.json",
            )
        self.assertEqual(data, completed.stdout)
        argv = run.call_args.args[0]
        self.assertEqual(argv[0:2], ["ssh", "bird@birdnet.local"])
        self.assertIn("cuts.json", argv[2])
        self.assertNotIn("http://", SCRIPT.read_text())
        self.assertNotIn("urllib", SCRIPT.read_text())

    def test_ssh_read_failure_is_not_silent(self) -> None:
        completed = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"missing")
        with mock.patch.object(MODULE.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "missing"):
                MODULE.read_remote("bird@birdnet.local", "BirdNET-Pi/missing")

    def test_fmt_duration(self) -> None:
        self.assertEqual(MODULE.fmt_duration(7.4), "7s")
        self.assertEqual(MODULE.fmt_duration(125), "2m05s")
        self.assertEqual(MODULE.fmt_duration(3 * 3600 + 7 * 60), "3h07m")

    def run_main(self, argv, cuts, fail=()):
        """Run main() end to end with SSH, scp and the model stubbed out."""
        def read_remote(pi, path):
            if path.endswith("cuts.json"):
                return json.dumps(cuts).encode()
            if any(path.endswith(f"/raw/{slug}.png") for slug in fail):
                raise RuntimeError("cat: no such file")
            return b"x" * 2_000_000

        def cut(src, dst, sess):
            dst.write_bytes(b"y" * 500_000)

        fake_rembg = types.ModuleType("rembg")
        fake_rembg.new_session = lambda name: object()
        ok = subprocess.CompletedProcess([], 0)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(sys.modules, {"rembg": fake_rembg, "scipy": types.ModuleType("scipy")}), \
                mock.patch.object(MODULE, "read_remote", side_effect=read_remote), \
                mock.patch.object(MODULE, "birefnet_cut", side_effect=cut), \
                mock.patch.object(MODULE.subprocess, "run", return_value=ok), \
                mock.patch.object(sys, "argv", ["upgrade_cutouts.py", *argv]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = MODULE.main()
        return code, out.getvalue(), err.getvalue()

    def test_progress_shows_steps_counter_and_summary(self) -> None:
        cuts = {"pica-pica": "chroma", "pica-pica-2": "chroma", "bubo-bubo": "birefnet"}
        code, out, err = self.run_main(["--pi", "bird@birdnet.local"], cuts, fail=("pica-pica-2",))
        self.assertEqual(code, 0, err)
        for step in ("1/5 reading", "2/5 loading", "3/5 cutting 2 bird(s)", "4/5 pushing 1",
                     "5/5 installing"):
            self.assertIn(step, out)
        self.assertIn("[1/2] pica-pica [ok]", out)
        self.assertIn("left", out)
        self.assertIn("[2/2] pica-pica-2 [fail]", out)
        self.assertIn("[fail] pica-pica-2: cat: no such file", err)
        self.assertIn("done: 1 upgraded, 1 failed in", out)
        self.assertIn("retried next run: pica-pica-2", out)
        self.assertNotIn("fetching raw/", out)

    def test_verbose_adds_per_step_detail(self) -> None:
        code, out, err = self.run_main(["--pi", "bird@birdnet.local", "-v"], {"pica-pica": "chroma"})
        self.assertEqual(code, 0, err)
        self.assertIn("[1/1] pica-pica: fetching raw/pica-pica.png", out)
        self.assertIn("2.0 MB in", out)
        self.assertIn("matted in", out)
        self.assertIn("ssh bird@birdnet.local cd -- BirdNET-Pi", out)


if __name__ == "__main__":
    unittest.main()
