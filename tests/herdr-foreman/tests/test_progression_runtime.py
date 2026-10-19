"""Delegated observation needs current owner, kernel lease and live OS process."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import copy
from datetime import timedelta
import json
import subprocess
import threading
import unittest
from unittest.mock import patch

from foreman import progression_runtime as runtime, supervision, supervision_runtime
from foreman.errors import ForemanError
from foreman.state import TransactionBusy, state_lock
from tests import test_progression_owner as fixture


CHILD = """
import sys
sys.path.insert(0, sys.argv[1])
from foreman import progression_owner, progression_runtime
with progression_owner.service_session(sys.argv[2], 'one', 1, 'fixture-service', sys.argv[3]) as cap:
    progression_runtime.pulse(cap, sys.argv[4])
    print('ready', flush=True)
    sys.stdin.readline()
"""


class ProgressionRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.case = fixture.ProgressionOwnerTest()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.admit()

    def at(self, seconds=0):
        return (supervision.timestamp(fixture.AT) + timedelta(seconds=seconds)).isoformat()

    def health(self, at=None, **kwargs):
        return runtime.health(self.case.state(), supervision.load(self.case.path), "one", at or fixture.AT, **kwargs)

    def test_pulses_replace_one_current_row_without_root_or_event_history(self):
        before = self.case.path.read_bytes()
        with self.case.session() as cap:
            for index in range(10):
                runtime.pulse(cap, self.at(index * 15))
            data = supervision.load(self.case.path)
            self.assertEqual(len(data["watchers"]), 1)
            self.assertEqual(data["watchers"][0]["at"], fixture.AT)
            self.assertEqual(data["events"], [])
            self.assertEqual(self.case.path.read_bytes(), before)
            self.assertEqual(self.health(self.at(135))["state"], "live")

    def test_transient_real_transaction_contention_does_not_kill_heartbeat(self):
        collided, recovered = threading.Event(), threading.Event()
        original = runtime.pulse
        def observed(*args, **kwargs):
            try:
                result = original(*args, **kwargs)
            except TransactionBusy:
                collided.set()
                raise
            if collided.is_set():
                recovered.set()
            return result
        with self.case.session() as cap, patch.object(runtime, "PULSE_SECONDS", 0.02), patch.object(runtime, "pulse", side_effect=observed):
            with runtime.keep_alive(cap, lambda: fixture.AT) as require_healthy:
                with state_lock(self.case.path):
                    self.assertTrue(collided.wait(5), "The fixture did not exercise real lock contention")
                self.assertTrue(recovered.wait(5), "The executor did not recover its next heartbeat")
                require_healthy()
                self.assertEqual(self.health()["state"], "live")

    def test_real_child_process_can_monitor_without_a_foreman_model_turn(self):
        child = subprocess.Popen([sys.executable, "-c", CHILD, str(fixture.ROOT / "skills/herdr-foreman"),
            str(self.case.path), str(fixture.ROOT), fixture.AT], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            assert child.stdout is not None
            self.assertEqual(child.stdout.readline().strip(), "ready")
            self.assertEqual(self.health()["state"], "live")
            child.communicate("stop\n", timeout=10)
            self.assertEqual(child.returncode, 0)
            self.assertEqual(self.health()["state"], "lease_free")
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)

    def test_expired_or_future_pulse_never_reclaims_a_live_kernel_lease(self):
        with self.case.session() as cap:
            runtime.pulse(cap, fixture.AT)
            self.assertEqual(self.health(self.at(-1))["state"], "unresponsive")
            self.assertEqual(self.health(self.at(runtime.LIVE_GRACE_SECONDS + 1))["state"], "unresponsive")
            with self.assertRaises(ForemanError):
                with self.case.session():
                    self.fail("stale heartbeat reclaimed live authority")

    def test_free_lease_and_reused_pid_do_not_prove_continuation(self):
        with self.case.session() as cap:
            runtime.pulse(cap, fixture.AT)
            self.assertEqual(self.health(probe=lambda _pid: None)["state"], "process_lost")
            self.assertEqual(self.health(probe=lambda pid: {"pid": pid, "identity": "different-process"})["state"], "process_lost")
        self.assertEqual(self.health()["state"], "lease_free")

    def test_another_process_holding_the_path_cannot_revive_an_old_live_pid_row(self):
        with self.case.session() as cap:
            runtime.pulse(cap, fixture.AT)
        source = """
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR)
fcntl.flock(fd, fcntl.LOCK_EX)
print('ready', flush=True)
sys.stdin.readline()
"""
        child = subprocess.Popen([sys.executable, "-c", source, str(self.case.root / "service.lease")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            assert child.stdout is not None
            self.assertEqual(child.stdout.readline().strip(), "ready")
            self.assertEqual(self.health()["state"], "lease_owner_unproved")
            child.communicate("stop\n", timeout=10)
            self.assertEqual(child.returncode, 0)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)

    def test_foreground_watcher_health_does_not_borrow_a_task_executor(self):
        with self.case.session() as cap:
            runtime.pulse(cap, fixture.AT)
            self.assertEqual(supervision_runtime.health(supervision.load(self.case.path), fixture.AT)["state"], "absent")

    def test_generation_and_binding_changes_invalidate_only_delegated_proof(self):
        with self.case.session() as cap:
            runtime.pulse(cap, fixture.AT)
            state = self.case.state()
            state["recovery"]["tasks"]["one"]["authority"]["generation"] += 1
            self.assertEqual(runtime.health(state, supervision.load(self.case.path), "one", fixture.AT)["state"], "superseded")
            data = supervision.load(self.case.path)
            data["binding"]["generation"] += 1
            self.assertEqual(runtime.health(self.case.state(), data, "one", fixture.AT)["state"], "held_or_rebound")

    def test_stopped_executor_and_unknown_rows_do_not_become_live_proof(self):
        with self.case.session() as cap:
            runtime.pulse(cap, fixture.AT, stopped=True, reason="fixture_completed")
            self.assertEqual(self.health()["state"], "stopped")
        path = supervision.store_path(self.case.path)
        for change in ({"schema_version": 3}, {"process": {"pid": 0, "identity": "bad"}}, {"extra": "unowned"}):
            data = supervision.load(self.case.path)
            data["watchers"][0].update(change)
            original = path.read_bytes()
            path.write_text(json.dumps(data))
            corrupt = path.read_bytes()
            with self.assertRaises(ForemanError):
                supervision.load(self.case.path)
            self.assertEqual(path.read_bytes(), corrupt)
            path.write_bytes(original)

    def test_returned_authority_does_not_inherit_a_saved_process_claim(self):
        with self.case.session() as cap:
            runtime.pulse(cap, fixture.AT)
            state = copy.deepcopy(self.case.state())
            state["recovery"]["tasks"]["one"]["authority"]["mode"] = "legacy"
            self.assertEqual(runtime.health(state, supervision.load(self.case.path), "one", fixture.AT)["state"], "not_delegated")


if __name__ == "__main__":
    unittest.main()
