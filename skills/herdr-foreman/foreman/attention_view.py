"""Bounded offline catch-up, with obligations ahead of saved progress."""

import copy

from . import attention, context_output, foreman_reset
from .chronology import timestamp
from .errors import UsageError


def _short(value, limit=600):
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _source_link(source):
    ref = source["ref"]
    label = source["kind"].replace("_", " ")
    if ref.startswith(("https://", "http://", "/")) and not any(char in ref for char in "\n\r"):
        target = ref.replace("<", "%3C").replace(">", "%3E")
        return "[{}](<{}>)".format(label, target)
    return "{}: {}".format(label, _short(ref, 2000))


def _useful_links(sources):
    rank = {"artifact": 0, "task_ledger": 1, "retrospective": 2, "other": 3, "user_message": 4}
    links = []
    for source in sorted(sources, key=lambda row: rank[row["kind"]]):
        ref = source["ref"]
        if ref.startswith(("https://", "http://", "/")) and not any(char in ref for char in "\n\r"):
            link = _source_link(source)
            if link not in links:
                links.append(link)
    return " · ".join(links[:3])


def _pagination(page, label):
    if not page["omitted"]:
        return []
    selector = "--section {} ".format(page["section"])
    next_page = "Continue with {}--offset {}.".format(selector, page["next_offset"]) if page["next_offset"] is not None else "Read earlier pages with {}--offset 0.".format(selector)
    return ["", "**{} {} are outside this page.** {}".format(page["omitted"], label, next_page)]


def _render(result):
    lines = ["# Needs your attention", ""]
    for reset in result["foreman_resets"]:
        lines.extend(["## Foreman reset {} needs you".format(reset["status"]), "",
                      _short(reset["needed"]), "", "Record: {}".format(reset["record"]), ""])
    lines.extend(_pagination(result["foreman_reset_page"], "foreman resets"))
    queue = result["attention"]
    needs_you = bool(queue["total"] or result["foreman_reset_page"]["total"])
    if not needs_you:
        lines.append("Nothing currently needs your attention in the saved queue.")
    for row in queue["items"]:
        lines.extend(["## {}".format(_short(row["title"], 300)), "",
                      _short(row["context"]), "", _short(row["consequence"]), ""])
        if row["options"]:
            lines.extend(["Choices: {}".format("; ".join(_short(value, 200) for value in row["options"])), ""])
        if row["recommendation"]:
            lines.extend(["Recommendation: {}".format(_short(row["recommendation"])), ""])
        lines.extend(["**Needed:** {}".format(_short(row["resolution_condition"])), ""])
        links = _useful_links(row["sources"])
        if links:
            lines.extend([links, ""])
        if row["resurfaced"]:
            lines.extend(["_Back for attention after {}._".format(row["deferred_until"]), ""])
        elif row["last_presented_at"]:
            cue = {"question": "Still awaiting your answer.", "decision": "Still awaiting your decision.",
                   "review": "Still awaiting your review."}.get(row["kind"], "Still open from the earlier update.")
            lines.extend(["_{}_".format(cue), ""])
    lines.extend(_pagination(queue, "actionable obligations"))
    result["attention_markdown"] = "\n".join(lines).rstrip() + "\n" if needs_you else ""
    deferred = result["deferred"]
    if deferred["total"]:
        lines.extend(["", "## Coming back later", ""])
        for row in deferred["items"]:
            lines.append("- {} — {}.".format(_short(row["title"], 300), row["deferred_until"]))
        lines.extend(_pagination(deferred, "deferred items"))
    lines.extend(["", "## Known progress", ""])
    assessments = {"verified": "Verified when recorded", "reported": "Reported; acceptance unverified", "unknown": "Acceptance unknown"}
    for row in result["progress"]["items"]:
        lines.extend(["**{}:** {}".format(_short(row["task"]), _short(row["summary"])), "",
                      "{} · {}".format(assessments[row["assessment"]], row["at"]), ""])
        links = _useful_links(row["sources"])
        if links:
            lines.extend([links, ""])
    if not result["progress"]["total"]:
        lines.append("No saved progress matches this view; completion is unknown.")
    lines.extend(_pagination(result["progress"], "progress records"))
    if result["closed"] is not None and result["closed"]["total"]:
        lines.extend(["", "## Resolved", ""])
        for row in result["closed"]["items"]:
            outcome = row["resolution"]["summary"] if row["resolution"] is not None else "Replaced by a later obligation."
            lines.append("- **{}:** {} ({})".format(_short(row["title"], 300), _short(outcome), row["updated_at"]))
        lines.extend(_pagination(result["closed"], "closed items"))
    return "\n".join(lines).rstrip() + "\n"


def catch_up(path, at, *, task=None, limit=context_output.DEFAULT_LIMIT, offset=0, since=None,
             include_closed=False, compact=False, section=None):
    context_output.validate_page(limit, offset)
    if section not in (None, "attention", "deferred", "progress", "closed", "resets"):
        raise UsageError("Select --section attention, deferred, progress, closed or resets.", {})
    include_closed = include_closed or section is not None
    now = timestamp(at, "Catch-up checkpoint")
    cutoff = timestamp(since, "Catch-up since") if since is not None else None
    document, entries, progress = attention.load(path)
    if document["events"] and timestamp(document["events"][-1]["at"], "Latest attention event") > now:
        raise UsageError("Catch-up checkpoint precedes saved events; use the current UTC checkpoint without rewriting history.", {})
    actionable, deferred, closed = [], [], []
    for value in entries.values():
        if task is not None and value["task"] != task:
            continue
        row = copy.deepcopy(value)
        row["resurfaced"] = row["status"] == "deferred" and timestamp(row["deferred_until"], "Resurface time") <= now
        row["effective_status"] = "open" if row["resurfaced"] else row["status"]
        if row["effective_status"] == "open":
            actionable.append(row)
        elif row["effective_status"] == "deferred":
            deferred.append(row)
        elif cutoff is None or timestamp(row["updated_at"], "Resolution time") >= cutoff:
            closed.append(row)
    actionable.sort(key=lambda row: (-row["priority"], row["created_at"], row["id"]))
    deferred.sort(key=lambda row: (row["deferred_until"], -row["priority"], row["id"]))
    closed.sort(key=lambda row: (row["updated_at"], row["id"]), reverse=True)
    progress = [row for row in progress if (task is None or row["task"] == task)
                and (cutoff is None or timestamp(row["at"], "Progress time") >= cutoff)]
    progress.sort(key=lambda row: (row["at"], row["id"]), reverse=True)
    # Reset obligations remain globally counted even in a task/section-specific view.
    resets = foreman_reset.outstanding(path)

    def build(effective):
        def selected(rows, name):
            page = context_output.section_page(rows, offset, effective, selected=section in (None, name))
            page["section"] = name
            return page

        reset_page = selected(resets, "resets")
        result = {"schema_version": attention.SCHEMA_VERSION, "state_path": str(attention.canonical_state(path)),
                  "attention_path": str(attention.storage_path(path)), "checked_at": attention._utc(at),
                  "task": task, "since": since, "section": section, "attention": selected(actionable, "attention"),
                  "deferred": selected(deferred, "deferred"),
                  "progress": selected(progress, "progress"),
                  "closed": selected(closed, "closed") if include_closed else None,
                  "retrospective_index": str(attention.canonical_state(path)) + ".retrospectives/index.json",
                  "foreman_resets": reset_page.pop("items"), "foreman_reset_page": reset_page,
                  "presentation_included": not compact}
        sections = [result[name] for name in ("attention", "deferred", "progress", "closed")
                    if result[name] is not None]
        result["context_complete"] = reset_page["omitted"] == 0 and all(page["omitted"] == 0 for page in sections)
        if not compact:
            sources = []
            for page in sections:
                for row in page["items"]:
                    for source in row["sources"]:
                        if source not in sources:
                            sources.append(copy.deepcopy(source))
            result["sources"] = sources
            result["markdown"] = _render(result)
        return result

    return context_output.fit_pages(build, limit, offset)
