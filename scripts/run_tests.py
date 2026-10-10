#!/usr/bin/env python3
"""Machine-Readable Test Runner for MC Local AI Bot.

Executes the test suite, captures detailed per-test execution telemetry
(status, latency, tracebacks), validates runtime dependencies, and writes
a structured JSON test report to runs/<run_id>/test_report.json.
"""

import os
import sys
import time
import json
import shutil
import unittest
import argparse
import traceback
import importlib.util
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from utils.run_context import (
    generate_run_id,
    get_run_directory,
    get_git_commit_hash,
    set_current_run_id,
    get_current_run_id,
)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class StructuredTestResult(unittest.TestResult):
    """Custom TestResult collecting machine-readable test records and durations."""

    def __init__(self, verbosity: int = 1):
        super().__init__()
        self.verbosity = verbosity
        self.records: List[Dict[str, Any]] = []
        self._test_start_times: Dict[str, float] = {}

    def startTest(self, test: unittest.TestCase):
        super().startTest(test)
        self._test_start_times[test.id()] = time.perf_counter()

    def _get_duration_ms(self, test: unittest.TestCase) -> float:
        start_t = self._test_start_times.get(test.id())
        if start_t is not None:
            return round((time.perf_counter() - start_t) * 1000.0, 2)
        return 0.0

    def addSuccess(self, test: unittest.TestCase):
        super().addSuccess(test)
        dur = self._get_duration_ms(test)
        self.records.append({
            "id": test.id(),
            "class": test.__class__.__name__,
            "name": getattr(test, "_testMethodName", str(test)),
            "description": test.shortDescription() or "",
            "status": "passed",
            "duration_ms": dur,
            "error_message": None,
            "traceback": None
        })
        if self.verbosity > 1:
            sys.stdout.write(f"  ✅ {test.id()} ({dur} ms)\n")
        else:
            sys.stdout.write(".")
        sys.stdout.flush()

    def addFailure(self, test: unittest.TestCase, err):
        super().addFailure(test, err)
        dur = self._get_duration_ms(test)
        err_msg = str(err[1]) if len(err) > 1 else "AssertionError"
        tb_str = "".join(traceback.format_exception(*err))
        self.records.append({
            "id": test.id(),
            "class": test.__class__.__name__,
            "name": getattr(test, "_testMethodName", str(test)),
            "description": test.shortDescription() or "",
            "status": "failed",
            "duration_ms": dur,
            "error_message": err_msg,
            "traceback": tb_str
        })
        if self.verbosity > 1:
            sys.stdout.write(f"  ❌ FAIL: {test.id()} ({dur} ms)\n")
        else:
            sys.stdout.write("F")
        sys.stdout.flush()

    def addError(self, test: unittest.TestCase, err):
        super().addError(test, err)
        dur = self._get_duration_ms(test)
        err_msg = str(err[1]) if len(err) > 1 else "Exception"
        tb_str = "".join(traceback.format_exception(*err))
        self.records.append({
            "id": test.id(),
            "class": test.__class__.__name__,
            "name": getattr(test, "_testMethodName", str(test)),
            "description": test.shortDescription() or "",
            "status": "error",
            "duration_ms": dur,
            "error_message": err_msg,
            "traceback": tb_str
        })
        if self.verbosity > 1:
            sys.stdout.write(f"  💥 ERROR: {test.id()} ({dur} ms)\n")
        else:
            sys.stdout.write("E")
        sys.stdout.flush()

    def addSkip(self, test: unittest.TestCase, reason: str):
        super().addSkip(test, reason)
        dur = self._get_duration_ms(test)
        self.records.append({
            "id": test.id(),
            "class": test.__class__.__name__,
            "name": getattr(test, "_testMethodName", str(test)),
            "description": test.shortDescription() or "",
            "status": "skipped",
            "duration_ms": dur,
            "error_message": reason,
            "traceback": None
        })
        if self.verbosity > 1:
            sys.stdout.write(f"  ⏭️ SKIP: {test.id()} ({reason})\n")
        else:
            sys.stdout.write("S")
        sys.stdout.flush()


def check_runtime_dependencies() -> Dict[str, Any]:
    """Inspects system binaries and Python libraries needed for bot execution."""
    python_deps = {}
    for pkg in ["websockets", "aiohttp", "dotenv", "sqlite3"]:
        try:
            spec = importlib.util.find_spec(pkg)
            python_deps[pkg] = spec is not None
        except Exception:
            python_deps[pkg] = False

    has_git = shutil.which("git") is not None
    if not has_git and sys.platform == "win32":
        git_candidates = [
            r"C:\Program Files\Git\cmd\git.exe",
            r"C:\Users\omerf\AppData\Local\GitHubDesktop\app-3.6.4\resources\app\git\cmd\git.exe"
        ]
        has_git = any(os.path.isfile(c) for c in git_candidates)

    binaries = {
        "node": shutil.which("node") is not None,
        "java": shutil.which("java") is not None,
        "git": has_git
    }

    return {
        "python_version": sys.version.split()[0],
        "platform": sys.platform,
        "python_packages": python_deps,
        "system_binaries": binaries
    }


def execute_test_runner(
    test_dir: str = "tests",
    pattern: str = "test_*.py",
    run_id: Optional[str] = None,
    verbosity: int = 1,
    failfast: bool = False,
    base_dir: Optional[str] = None
) -> Tuple[Dict[str, Any], str, int]:
    """Runs test discovery and produces runs/<run_id>/test_report.json."""
    active_run_id = run_id or generate_run_id(is_test=True)
    set_current_run_id(active_run_id)
    run_dir = get_run_directory(active_run_id, base_dir=base_dir)

    deps = check_runtime_dependencies()

    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=test_dir, pattern=pattern)

    result = StructuredTestResult(verbosity=verbosity)
    if failfast:
        result.failfast = True

    t_start = time.perf_counter()
    suite.run(result)
    t_total = round(time.perf_counter() - t_start, 2)
    sys.stdout.write("\n\n")

    total_count = len(result.records)
    failed_count = len(result.failures)
    error_count = len(result.errors)
    skipped_count = len(result.skipped)
    passed_count = total_count - failed_count - error_count - skipped_count
    success_rate = round((passed_count / max(1, total_count - skipped_count)) * 100, 1)

    summary = {
        "total": total_count,
        "passed": passed_count,
        "failed": failed_count,
        "errors": error_count,
        "skipped": skipped_count,
        "success_rate_pct": success_rate,
        "total_duration_seconds": t_total
    }

    report = {
        "run_id": active_run_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "commit_hash": get_git_commit_hash(short=False),
        "summary": summary,
        "environment": deps,
        "tests": result.records
    }

    report_path = os.path.join(run_dir, "test_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    exit_code = 0 if (failed_count == 0 and error_count == 0) else 1
    return report, report_path, exit_code


def print_report_summary(report: Dict[str, Any], report_path: str):
    """Outputs a clean console summary of the test execution."""
    s = report["summary"]
    env = report["environment"]

    print("=" * 65)
    print(f"📋 TEST SUITE SUMMARY (Run ID: {report['run_id']})")
    print("=" * 65)
    print(f"  • Total Tests  : {s['total']}")
    print(f"  • Passed       : {s['passed']} (✅)")
    print(f"  • Failed       : {s['failed']} (❌)")
    print(f"  • Errors       : {s['errors']} (💥)")
    print(f"  • Skipped      : {s['skipped']} (⏭️)")
    print(f"  • Success Rate : {s['success_rate_pct']}%")
    print(f"  • Duration     : {s['total_duration_seconds']}s")
    print("-" * 65)

    missing_pkgs = [p for p, ok in env["python_packages"].items() if not ok]
    missing_bins = [b for b, ok in env["system_binaries"].items() if not ok]
    if missing_pkgs or missing_bins:
        print("⚠️ Environment Warnings:")
        if missing_pkgs:
            print(f"  • Missing Python Packages: {', '.join(missing_pkgs)} (run: pip install -r requirements.txt)")
        if missing_bins:
            print(f"  • Missing System Binaries: {', '.join(missing_bins)}")
        print("-" * 65)

    # Print failures / errors summary if any
    failures = [t for t in report["tests"] if t["status"] in ("failed", "error")]
    if failures:
        print("❌ Failed Tests:")
        for f in failures:
            print(f"  [{f['status'].upper()}] {f['id']}")
            if f.get("error_message"):
                msg_preview = str(f["error_message"]).splitlines()[0][:100]
                print(f"    Reason: {msg_preview}")
        print("-" * 65)

    print(f"📁 Machine-readable report saved to:\n   {report_path}")
    print("=" * 65)


def main():
    parser = argparse.ArgumentParser(description="Machine-readable test runner for MC Local AI Bot.")
    parser.add_argument("--test-dir", default="tests", help="Directory containing tests")
    parser.add_argument("--pattern", default="test_*.py", help="Test file match pattern")
    parser.add_argument("--run-id", default=None, help="Custom run identifier")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose test progress")
    parser.add_argument("-f", "--failfast", action="store_true", help="Stop on first failure")
    args = parser.parse_args()

    verbosity = 2 if args.verbose else 1
    report, report_path, exit_code = execute_test_runner(
        test_dir=args.test_dir,
        pattern=args.pattern,
        run_id=args.run_id,
        verbosity=verbosity,
        failfast=args.failfast
    )
    print_report_summary(report, report_path)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
