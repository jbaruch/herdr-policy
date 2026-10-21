"""Exercise the real Unix WebSocket/RPC client against a local protocol peer."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/herdr-foreman"))

import base64
import hashlib
import json
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from foreman.codex_goals import AppServer, GoalError, control_socket
from foreman import host_goals
from tests.goal_fakes import GoalHost, goal


class SocketHost:
    def __init__(self, *, fragment=False, invalid_upgrade=False, response=None):
        self.directory = tempfile.TemporaryDirectory(prefix="goal-rpc-", dir="/tmp")
        self.path = str(Path(self.directory.name) / "control.sock")
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(self.path)
        self.socket.listen()
        self.socket.settimeout(0.1)
        self.stopped = threading.Event()
        self.errors = []
        self.host = GoalHost({"old": goal()})
        self.fragment = fragment
        self.invalid_upgrade = invalid_upgrade
        self.response = response
        self.worker = threading.Thread(target=self.serve)
        self.worker.start()

    @staticmethod
    def frame(data, opcode=1, final=True):
        first = (0x80 if final else 0) | opcode
        n = len(data)
        header = bytes([first, n]) if n < 126 else (
            bytes([first, 126]) + struct.pack("!H", n) if n < 65536 else bytes([first, 127]) + struct.pack("!Q", n))
        return header + data

    @staticmethod
    def read_frame(reader):
        header = reader.read(2)
        if not header:
            raise EOFError()
        first, second = header
        size = second & 127
        if size == 126:
            size = struct.unpack("!H", reader.read(2))[0]
        elif size == 127:
            size = struct.unpack("!Q", reader.read(8))[0]
        if not second & 128:
            raise ValueError("client frame was not masked")
        mask, data = reader.read(4), reader.read(size)
        return first & 15, bytes(value ^ mask[i % 4] for i, value in enumerate(data))

    def connection(self, stream):
        stream.settimeout(3)
        with stream, stream.makefile("rb") as reader:
            lines = []
            while True:
                line = reader.readline(16384)
                if line == b"\r\n":
                    break
                if not line:
                    raise EOFError()
                lines.append(line.decode("ascii").strip())
            key = next(line.split(":", 1)[1].strip() for line in lines if line.startswith("Sec-WebSocket-Key:"))
            accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            if self.invalid_upgrade:
                accept = "wrong-accept"
            stream.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + "\r\n\r\n").encode())
            if self.invalid_upgrade:
                return
            while True:
                opcode, data = self.read_frame(reader)
                if opcode == 10:
                    continue
                message = json.loads(data)
                if "id" not in message:
                    continue
                if message["method"] == "initialize":
                    result = {"id": message["id"], "result": {}}
                elif self.response is not None:
                    result = {"id": message["id"], **self.response}
                else:
                    result = {"id": message["id"], "result": self.host.call(message["method"], message["params"])}
                encoded = json.dumps(result).encode()
                if self.fragment:
                    mid = len(encoded) // 2
                    stream.sendall(self.frame(encoded[:mid], final=False) + self.frame(b"probe", opcode=9)
                                   + self.frame(encoded[mid:], opcode=0))
                else:
                    stream.sendall(self.frame(encoded))

    def serve(self):
        try:
            while not self.stopped.is_set():
                try:
                    stream, _ = self.socket.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self.stopped.is_set():
                        return
                    raise
                try:
                    self.connection(stream)
                except EOFError:
                    continue  # A client closes its owned connection after the RPC.
        except (OSError, ValueError, KeyError, StopIteration, struct.error) as exc:
            self.errors.append(exc)

    def close(self):
        self.stopped.set()
        self.socket.close()
        self.worker.join(5)
        self.directory.cleanup()
        if self.worker.is_alive():
            raise AssertionError("protocol fixture did not stop")
        if self.errors:
            raise AssertionError(self.errors)


class CodexGoalRPCTest(unittest.TestCase):
    def peer(self, **options):
        peer = SocketHost(**options)
        self.addCleanup(peer.close)
        self.enterContext(patch("foreman.codex_goals.control_socket", return_value=peer.path))
        return peer

    def test_real_socket_transfer_preserves_budget_and_one_continuing_executor(self):
        peer = self.peer()
        receipt = host_goals.prepare("codex", {"kind": "id", "value": "old"}, discover=lambda: peer.path)
        saved = []
        host_goals.transfer(receipt, "new", lambda: saved.append(receipt["phase"]))
        peer.host.end_turn("old")
        peer.host.end_turn("new")
        self.assertEqual(peer.host.continuations, ["new"])
        self.assertEqual(peer.host.goals["new"]["tokenBudget"], 700)
        self.assertEqual(saved[-1], "verified")

    def test_fragmented_rpc_and_ping_are_handled_without_losing_goal_data(self):
        peer = self.peer(fragment=True)
        with AppServer(peer.path) as client:
            self.assertEqual(client.goal("old"), goal())

    def test_running_outgoing_continuation_is_interrupted_over_the_actual_rpc_protocol(self):
        peer = self.peer()
        peer.host.active.add("old")
        receipt = host_goals.prepare("codex", {"kind": "id", "value": "old"}, discover=lambda: peer.path)
        host_goals.transfer(receipt, "new", lambda: None)
        self.assertNotIn("old", peer.host.active)
        self.assertEqual(peer.host.goals["new"]["status"], "active")
        self.assertIsNone(peer.host.goal("old"))
        self.assertEqual(receipt["retiring_turn"], "outgoing-turn")

    def test_64_bit_frame_length_is_supported_within_the_message_budget(self):
        peer = self.peer(response={"result": {"padding": "x" * 70000}})
        with AppServer(peer.path) as client:
            self.assertEqual(len(client.call("probe", {})["padding"]), 70000)

    def test_a_daemon_owned_control_socket_alias_is_supported(self):
        peer = self.peer()
        alias = Path(peer.directory.name) / "stable.sock"
        alias.symlink_to(peer.path)
        with AppServer(str(alias)) as client:
            self.assertEqual(client.goal("old"), goal())

    def test_bad_upgrade_and_missing_goal_shape_refuse(self):
        peer = self.peer(invalid_upgrade=True)
        with self.assertRaises(GoalError):
            with AppServer(peer.path):
                self.fail("invalid upgrade admitted")
        peer2 = self.peer(response={"result": {}})
        with AppServer(peer2.path) as client:
            with self.assertRaises(GoalError):
                client.goal("old")

    def test_provider_error_does_not_leak_its_payload(self):
        peer = self.peer(response={"error": {"code": -1, "message": "fixture-sensitive-provider-text"}})
        with AppServer(peer.path) as client:
            with self.assertRaises(GoalError) as caught:
                client.goal("old")
        self.assertNotIn("fixture-sensitive-provider-text", str(caught.exception))

    def test_unavailable_socket_refuses_without_starting_a_server(self):
        with tempfile.TemporaryDirectory(prefix="goal-rpc-", dir="/tmp") as directory:
            with self.assertRaises(GoalError):
                with AppServer(str(Path(directory) / "missing.sock")):
                    self.fail("missing server admitted")

    def test_a_changed_daemon_socket_refuses_before_sending_any_rpc(self):
        first = self.peer()
        second = self.peer()
        with self.assertRaisesRegex(GoalError, "daemon_socket_changed"):
            with AppServer(first.path):
                self.fail("different daemon admitted")
        self.assertEqual(first.host.calls + second.host.calls, [])

    def test_discovery_uses_only_daemon_version_and_rejects_stopped_or_bad_output(self):
        class Result:
            returncode = 0
            stdout = b'{"status":"running","socketPath":"/fixture/codex.sock","appServerVersion":"0.163.0"}'
        with patch("foreman.codex_goals.subprocess.run", return_value=Result()) as run:
            self.assertEqual(control_socket(), "/fixture/codex.sock")
            self.assertEqual(run.call_args.args[0], ["codex", "app-server", "daemon", "version"])
        for data in (b'{"status":"stopped"}', b'not-json'):
            result = Result()
            result.stdout = data
            with patch("foreman.codex_goals.subprocess.run", return_value=result), self.assertRaises(GoalError):
                control_socket()

    def test_unknown_or_incompatible_protocol_version_refuses_during_read_only_discovery(self):
        for version in (None, "0.162.0", "0.164.0", [], True):
            with self.subTest(version=version):
                class Result:
                    returncode = 0
                    stdout = json.dumps({"status": "running", "socketPath": "/fixture/codex.sock",
                                         "appServerVersion": version}).encode()
                with patch("foreman.codex_goals.subprocess.run", return_value=Result()) as run:
                    with self.assertRaisesRegex(GoalError, "unsupported_goal_protocol"):
                        control_socket()
                    self.assertEqual(run.call_args.args[0], ["codex", "app-server", "daemon", "version"])


if __name__ == "__main__":
    unittest.main()
