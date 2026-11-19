"""Agent-side calls to the console server: the server proves itself before the agent token is sent."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import lifecycle

HELD_MARGIN = 20.0


class ClientError(Exception):
    """A console call failed. ``code`` is one of no-server, not-this-server, session-refused,
    session-replaced, transport, bad-request, or the server's own error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_json(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


def _server(home: Path | None) -> dict:
    info = lifecycle.read_server_json(home)
    if info is None:
        raise ClientError("no-server", "the console is not running; start it with `console start`")
    kind, _ = lifecycle.probe(info)
    if kind == "refused":
        raise ClientError("no-server", "the console is not running; start it with `console start`")
    if kind != "ok":
        raise ClientError("not-this-server", "the program on the console port did not prove itself")
    return info


def call(method: str, path: str, body: Any = None, *, timeout: float = 10.0, home: Path | None = None) -> Any:
    info = _server(home)
    try:
        status, data = lifecycle.request(int(info["port"]), method, path, token=str(info["agent_token"]),
                                         body=body, timeout=timeout)
    except (ConnectionRefusedError, lifecycle.NoAnswer) as exc:
        raise ClientError("transport", f"the console did not answer ({type(exc).__name__})") from None
    if status == 200:
        return data
    error = data.get("error", {}) if isinstance(data, dict) else {}
    code = error.get("code") or "transport"
    if status == 400:
        code = "bad-request" if code in ("bad-request", "transport") else code
    raise ClientError(code, error.get("message") or f"the console answered {status}")


def _held_timeout(timeout: float | None) -> float:
    return (timeout if timeout is not None else 100.0) + HELD_MARGIN


def wait(session: str, timeout: float | None = None, home: Path | None = None) -> dict:
    return call("POST", "/agent/wait", {"session": session, "timeout": timeout},
                timeout=_held_timeout(timeout), home=home)


def claim(job: str, session: str, home: Path | None = None) -> dict:
    return call("POST", f"/agent/jobs/{job}/claim", {"session": session}, home=home)


def progress(job: str, session: str, message: str, home: Path | None = None) -> dict:
    return call("POST", f"/agent/jobs/{job}/progress", {"session": session, "message": message}, home=home)


def ask(job: str, session: str, ask_obj: dict, timeout: float | None = None, home: Path | None = None) -> dict:
    return call("POST", f"/agent/jobs/{job}/ask", {"session": session, "ask": ask_obj, "timeout": timeout},
                timeout=_held_timeout(timeout), home=home)


def done(job: str, session: str, result: str, report: str | None = None, home: Path | None = None) -> dict:
    return call("POST", f"/agent/jobs/{job}/done", {"session": session, "result": result, "report": report},
                home=home)


def approval(job: str, session: str, home: Path | None = None) -> dict:
    return call("GET", f"/agent/jobs/{job}/approval?session={session}", home=home)


def queue(job: dict, home: Path | None = None) -> dict:
    """Queue a web test job from the chat; the console marks it ``queued_by: agent``."""
    return call("POST", "/agent/jobs", job, home=home)


def _q(value: str) -> str:
    return quote(str(value), safe="")


class Reader:
    """What the web test commands read from the console: job, review, sign-in and run answers."""

    def __init__(self, home: Path | None = None) -> None:
        self.home = home

    def job(self, job: str, session: str) -> dict:
        return call("GET", f"/agent/jobs/{_q(job)}/info?session={_q(session)}", home=self.home)

    def attach_run(self, job: str, session: str, run: str) -> dict:
        return call("POST", f"/agent/jobs/{_q(job)}/run", {"session": session, "run": run}, home=self.home)

    def review(self, job: str, session: str) -> dict | None:
        return call("GET", f"/agent/jobs/{_q(job)}/review?session={_q(session)}", home=self.home).get("review")

    def job_open(self, job: str) -> bool:
        try:
            return bool(call("GET", f"/agent/jobs/{_q(job)}/open", home=self.home).get("open"))
        except ClientError as exc:
            if exc.code == "no-server":
                return False  # no console, no open job
            raise

    def signed_in(self, job: str, session: str) -> dict | None:
        return call("GET", f"/agent/jobs/{_q(job)}/signed-in?session={_q(session)}",
                    home=self.home).get("signed_in")

    def pending(self, run: str, job: str, session: str, wait: float | None) -> dict:
        return call("POST", f"/agent/webtest/runs/{_q(run)}/pending",
                    {"session": session, "job": job, "wait": wait},
                    timeout=_held_timeout(wait) if wait else 10.0, home=self.home)

    def applied(self, run: str, job: str, session: str, ids: list[str]) -> dict:
        return call("POST", f"/agent/webtest/runs/{_q(run)}/applied", {"session": session, "job": job, "ids": ids},
                    home=self.home)


def read_json(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClientError("bad-request", f"cannot read {Path(path).name}: {type(exc).__name__}") from None


def ask_from_preview(preview: Any) -> dict:
    """Pack ``wiki-append-preview`` output as the ask the tester answers.

    API mode becomes ``confirm-diff`` (the tool's own diffs and approval hash); manual mode becomes
    ``paste-pages`` (the new page contents to paste by hand).
    """
    if not isinstance(preview, dict) or not isinstance(preview.get("pages"), list):
        raise ClientError("bad-request", "the preview file is not wiki-append-preview output")
    if preview.get("mode") == "manual":
        pages = [{"name": p.get("name"), "new_content": p.get("new_content")} for p in preview["pages"]]
        digest = hashlib.sha256(json.dumps(pages, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return {"type": "paste-pages", "id": f"paste-{digest[:12]}", "pages": pages}
    approval_hash = preview.get("approval")
    if not isinstance(approval_hash, str) or not approval_hash:
        raise ClientError("bad-request", "the preview has no approval hash")
    keep = ("pages", "added", "skipped", "superseded", "index_repaired", "approval")
    return {"type": "confirm-diff", "id": f"confirm-{approval_hash[:12]}",
            "preview": {k: preview.get(k) for k in keep if k in preview}}
