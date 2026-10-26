"""Goal RPC against an existing Codex app-server, never a second server.

The local control socket speaks WebSocket over Unix, not JSONL. Only the
goal methods, bounded thread metadata and exact-turn interruption are used.
Errors contain bounded
local reasons, never server payloads or goal text. Protocol compatibility:
Codex 0.163 app-server schema; recheck with each Codex compatibility update.
The supported ThreadGoalClearParams accepts threadId and origin, with no
conditional generation or compare-and-clear transaction. Callers can recheck
observed goals before clearing but cannot exclude unrelated host-client edits.
"""

import base64
import hashlib
import json
import os
import random
import socket
import stat
import struct
import subprocess
import time

from .errors import StateError

RPC_BUDGET_SEC = 10
# Fit the whole hook handshake inside the reset owner's acceptance allowance.
SESSION_BUDGET_SEC = 45
MAX_MESSAGE_BYTES = 1024 * 1024
MAX_HEADER_BYTES = 16384
MAX_NOTIFICATIONS = 128
SUPPORTED_CODEX_VERSIONS = ("0.163.0", "0.164.0")
# An explicit ingress rejection proves the request was not admitted. Never
# replay a transport failure or any other response with uncertain effects.
OVERLOAD_CODE = -32001
OVERLOAD_DELAY_SEC = 0.1
OVERLOAD_MAX_DELAY_SEC = 1


class GoalError(StateError):
    code = "reset_host_goal"


def unavailable(reason):
    return GoalError("Host goal handoff could not be verified ({}). Preserve the reset and current goals; restore the existing Codex app-server connection, then reconcile this reset. Do not mark the objective complete or invent a pause.".format(reason),
                     {"reason": reason})


def control_socket():
    """Discover the running daemon without starting, updating or restarting it."""
    try:
        result = subprocess.run(["codex", "app-server", "daemon", "version"], capture_output=True,
                                timeout=RPC_BUDGET_SEC, check=False)
        value = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError, UnicodeDecodeError):
        raise unavailable("daemon_unavailable") from None
    if (result.returncode or not isinstance(value, dict) or value.get("status") != "running"
            or not isinstance(value.get("socketPath"), str) or not os.path.isabs(value["socketPath"])):
        raise unavailable("daemon_unavailable")
    if value.get("appServerVersion") not in SUPPORTED_CODEX_VERSIONS:
        raise unavailable("unsupported_goal_protocol")
    return value["socketPath"]


class AppServer:
    """Bounded JSON-RPC client for the daemon's existing Unix WebSocket."""

    def __init__(self, path):
        self.path = path
        self.stream = None
        self.buffer = b""
        self.sequence = 0
        self.deadline = 0
        self.operation_deadline = 0

    def __enter__(self):
        try:
            if not os.path.samefile(control_socket(), self.path):
                raise unavailable("daemon_socket_changed")
            # Codex's stable control path may link to its current daemon socket.
            info = os.stat(self.path)
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise unavailable("untrusted_control_socket")
            self.stream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.operation_deadline = time.monotonic() + SESSION_BUDGET_SEC
            self.deadline = min(self.operation_deadline, time.monotonic() + RPC_BUDGET_SEC)
            self.stream.settimeout(RPC_BUDGET_SEC)
            self.stream.connect(self.path)
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            self.stream.sendall(("GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                                 "Sec-WebSocket-Key: {}\r\nSec-WebSocket-Version: 13\r\n\r\n".format(key)).encode("ascii"))
            while b"\r\n\r\n" not in self.buffer:
                self.buffer += self._recv()
                if len(self.buffer) > MAX_HEADER_BYTES:
                    raise unavailable("invalid_websocket_upgrade")
            header, self.buffer = self.buffer.split(b"\r\n\r\n", 1)
            lines = header.decode("ascii").split("\r\n")
            fields = {name.lower(): value.strip() for line in lines[1:] if ":" in line
                      for name, value in [line.split(":", 1)]}
            # SHA-1 is mandated by the WebSocket upgrade protocol, not used for authentication.
            expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
            if (lines[0] != "HTTP/1.1 101 Switching Protocols"
                    or fields.get("sec-websocket-accept") != expected
                    or fields.get("upgrade", "").lower() != "websocket"):
                raise unavailable("invalid_websocket_upgrade")
            self.call("initialize", {"clientInfo": {"name": "herdr_goal_handoff", "version": "1"},
                                     "capabilities": {"experimentalApi": True}})
            self._send({"method": "initialized", "params": {}})
            return self
        except (OSError, ValueError, UnicodeDecodeError):
            self.__exit__(None, None, None)
            raise unavailable("connection_failed") from None
        except GoalError:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_args):
        if self.stream is not None:
            self.stream.close()
            self.stream = None

    def _recv(self):
        if self.stream is None:
            raise unavailable("connection_closed")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise unavailable("rpc_timeout")
        self.stream.settimeout(remaining)
        chunk = self.stream.recv(65536)
        if not chunk:
            raise unavailable("connection_closed")
        return chunk

    def _read(self, count):
        while len(self.buffer) < count:
            self.buffer += self._recv()
        result, self.buffer = self.buffer[:count], self.buffer[count:]
        return result

    def _frame(self, payload, opcode=1):
        if self.stream is None:
            raise unavailable("connection_closed")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise unavailable("rpc_timeout")
        self.stream.settimeout(remaining)
        length = len(payload)
        header = bytes([0x80 | opcode, 0x80 | length]) if length < 126 else (
            bytes([0x80 | opcode, 0xfe]) + struct.pack("!H", length) if length < 65536 else
            bytes([0x80 | opcode, 0xff]) + struct.pack("!Q", length))
        mask = os.urandom(4)
        self.stream.sendall(header + mask + bytes(value ^ mask[i % 4] for i, value in enumerate(payload)))

    def _send(self, message):
        self._frame(json.dumps(message).encode("utf-8"))

    def _message(self):
        payload = b""
        started = False
        for _ in range(MAX_NOTIFICATIONS):
            first, second = self._read(2)
            opcode, size = first & 15, second & 127
            if first & 0x70 or second & 0x80:
                raise unavailable("invalid_websocket_frame")
            if size == 126:
                size = struct.unpack("!H", self._read(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self._read(8))[0]
            if size + len(payload) > MAX_MESSAGE_BYTES:
                raise unavailable("oversized_rpc_message")
            if opcode >= 8 and (not first & 0x80 or size > 125):
                raise unavailable("invalid_websocket_control")
            data = self._read(size)
            if opcode == 8:
                raise unavailable("connection_closed")
            if opcode == 9:
                self._frame(data, 10)
                continue
            if opcode == 10:
                continue
            if opcode not in (0, 1) or (opcode == 1) == started:
                raise unavailable("invalid_websocket_fragment")
            started = True
            payload += data
            if first & 0x80:
                return json.loads(payload)
        raise unavailable("excessive_rpc_frames")

    def call(self, method, params):
        self.deadline = min(self.operation_deadline, time.monotonic() + RPC_BUDGET_SEC)
        delay = OVERLOAD_DELAY_SEC
        try:
            while True:
                self.sequence += 1
                self._send({"id": self.sequence, "method": method, "params": params})
                for _ in range(MAX_NOTIFICATIONS):
                    message = self._message()
                    if not isinstance(message, dict):
                        raise unavailable("invalid_rpc_response")
                    if message.get("id") != self.sequence:
                        continue
                    error = message.get("error")
                    if ("result" not in message and isinstance(error, dict)
                            and type(error.get("code")) is int and error["code"] == OVERLOAD_CODE):
                        pause = random.uniform(delay / 2, delay)
                        if pause >= self.deadline - time.monotonic():
                            raise unavailable("rpc_overloaded")
                        time.sleep(pause)
                        delay = min(delay * 2, OVERLOAD_MAX_DELAY_SEC)
                        break
                    if "error" in message or not isinstance(message.get("result"), dict):
                        raise unavailable("rpc_rejected")
                    return message["result"]
                else:
                    raise unavailable("excessive_rpc_notifications")
        except (OSError, ValueError, UnicodeDecodeError):
            raise unavailable("rpc_failed") from None

    def goal(self, thread):
        result = self.call("thread/goal/get", {"threadId": thread})
        if "goal" not in result:
            raise unavailable("invalid_goal_response")
        value = result.get("goal")
        if value is not None and not valid_goal(value, thread):
            raise unavailable("invalid_goal_response")
        return value


def valid_goal(value, thread=None):
    return (isinstance(value, dict) and isinstance(value.get("threadId"), str)
            and (thread is None or value["threadId"] == thread)
            and isinstance(value.get("objective"), str) and bool(value["objective"])
            and isinstance(value.get("status"), str)
            and value["status"] in {"active", "paused", "blocked", "usageLimited", "budgetLimited", "complete"}
            and all(type(value.get(key)) is int and value[key] >= 0
                    for key in ("tokensUsed", "timeUsedSeconds", "createdAt", "updatedAt"))
            and "tokenBudget" in value and (value["tokenBudget"] is None
                or type(value["tokenBudget"]) is int and value["tokenBudget"] >= 0))
