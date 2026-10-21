"""Deterministic host scheduler double, including lost mutation responses."""

import copy
from typing import Callable

from foreman.codex_goals import unavailable


def goal(thread="old", *, budget: int | None = 1000, tokens=300, status="active", objective="Ship the authorized work"):
    return {"threadId": thread, "objective": objective, "status": status, "tokenBudget": budget,
            "tokensUsed": tokens, "timeUsedSeconds": 12, "createdAt": 100, "updatedAt": 101}


class GoalHost:
    def __init__(self, goals=None):
        self.goals = copy.deepcopy(goals or {})
        self.calls = []
        self.active = set()
        self.continuations = []
        self.lost: str | None = None
        self.before_clear: Callable[[], None] | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def connect(self, _path):
        return self

    def goal(self, thread):
        return copy.deepcopy(self.goals.get(thread))

    def call(self, method, params):
        self.calls.append((method, copy.deepcopy(params)))
        thread = params["threadId"]
        if method == "thread/goal/get":
            result = {"goal": self.goal(thread)}
        elif method == "thread/goal/clear":
            if self.before_clear:
                self.before_clear()
            result = {"cleared": self.goals.pop(thread, None) is not None}
        elif method == "thread/goal/set":
            self.goals[thread] = {**goal(thread, budget=params["tokenBudget"], tokens=0,
                                       status=params["status"], objective=params["objective"]),
                                  "createdAt": 200, "updatedAt": 200, "timeUsedSeconds": 0}
            result = {"goal": self.goal(thread)}
        elif method == "thread/read":
            result = {"thread": {"id": thread, "status": {"type": "active" if thread in self.active else "idle"}}}
        else:
            raise AssertionError("Unexpected host method: " + method)
        if self.lost == method:
            self.lost = None
            raise unavailable("fixture_lost_response")
        return result

    def end_turn(self, thread):
        self.active.discard(thread)
        current = self.goals.get(thread)
        if current and current["status"] == "active":
            self.continuations.append(thread)
