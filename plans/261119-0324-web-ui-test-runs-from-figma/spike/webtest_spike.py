"""Spike: can a fixed runner sign in to a dedicated test Chrome, and capture a page, with the
standard library only?

Run by the tester, not by the agent. Three modes:

  open     Start the test Chrome with the dedicated profile and leave it open, so the tester can
           install and sign in to the Claude extension there (once).
  probe    Start the test Chrome over the debug pipe, open a URL and print the structure of its
           form fields (tag, type, id, name). No value is read or typed.
  login    Start the test Chrome over the debug pipe, run a step list, save one screenshot and
           print the final URL. Field values come from a local file only the tester fills.

The debug pipe (--remote-debugging-pipe) is used: only this process can talk to that Chrome, and
no port is opened. macOS and Linux only; Windows needs inherited handles and is a separate item.

Nothing here prints, logs or returns a field value.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home() / ".testign-kit" / "webtest" / "spike"
PROFILE = HOME / "chrome-profile"
CHROME_MAC = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
COMMON = ["--no-first-run", "--no-default-browser-check", "--password-store=basic"]


class Pipe:
    """Chrome DevTools protocol over the debug pipe: JSON messages ended by a NUL byte."""

    def __init__(self, chrome: str, profile: Path, url: str) -> None:
        to_chrome_r, to_chrome_w = os.pipe()
        from_chrome_r, from_chrome_w = os.pipe()

        def wire() -> None:  # runs in the child before exec: Chrome reads fd 3 and writes fd 4
            a, b = os.dup(to_chrome_r), os.dup(from_chrome_w)
            os.dup2(a, 3)
            os.dup2(b, 4)

        self.proc = subprocess.Popen(
            [chrome, f"--user-data-dir={profile}", "--remote-debugging-pipe", *COMMON, url],
            preexec_fn=wire, pass_fds=(3, 4), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        os.close(to_chrome_r)
        os.close(from_chrome_w)
        self.w, self.r = to_chrome_w, from_chrome_r
        self.buf = b""
        self.next_id = 0

    def call(self, method: str, params: dict | None = None, session: str | None = None, timeout: float = 20) -> dict:
        self.next_id += 1
        msg = {"id": self.next_id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        os.write(self.w, json.dumps(msg).encode() + b"\0")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            while b"\0" not in self.buf:
                chunk = os.read(self.r, 65536)
                if not chunk:
                    raise SystemExit("the test Chrome closed the debug pipe")
                self.buf += chunk
            raw, self.buf = self.buf.split(b"\0", 1)
            reply = json.loads(raw)
            if reply.get("id") == self.next_id:
                if "error" in reply:
                    raise SystemExit(f"{method} failed: {reply['error'].get('message', 'error')}")
                return reply.get("result", {})
        raise SystemExit(f"{method} timed out")

    def page(self) -> tuple[str, str]:
        """Attach to the first page target; return (target id, session id)."""
        for _ in range(40):
            for info in self.call("Target.getTargets")["targetInfos"]:
                if info["type"] == "page":
                    sess = self.call("Target.attachToTarget", {"targetId": info["targetId"], "flatten": True})
                    return info["targetId"], sess["sessionId"]
            time.sleep(0.25)
        raise SystemExit("no page found in the test Chrome")

    def url(self, target: str) -> str:
        return self.call("Target.getTargetInfo", {"targetId": target})["targetInfo"]["url"]

    def close(self) -> None:
        try:
            self.call("Browser.close", timeout=5)
        except SystemExit:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.terminate()


def node(cdp: Pipe, sess: str, selector: str) -> int:
    root = cdp.call("DOM.getDocument", {"depth": 0}, sess)["root"]["nodeId"]
    found = cdp.call("DOM.querySelector", {"nodeId": root, "selector": selector}, sess)["nodeId"]
    if not found:
        raise SystemExit(f"no element matches {selector}")
    return found


def attrs(cdp: Pipe, sess: str, node_id: int) -> dict:
    flat = cdp.call("DOM.getAttributes", {"nodeId": node_id}, sess)["attributes"]
    return dict(zip(flat[0::2], flat[1::2]))


def run_steps(cdp: Pipe, target: str, sess: str, steps: list[dict], values: dict, secret: set[str]) -> None:
    for number, step in enumerate(steps, 1):
        kind = step["do"]
        print(f"step {number}: {kind}")
        if kind == "goto":
            cdp.call("Page.navigate", {"url": step["url"]}, sess)
            time.sleep(2)
        elif kind == "fill":
            field = step["field"]
            target_node = node(cdp, sess, step["selector"])
            if field in secret and attrs(cdp, sess, target_node).get("type") != "password":
                raise SystemExit(f"step {number}: a secret field may only go into a password input")
            cdp.call("DOM.focus", {"nodeId": target_node}, sess)
            cdp.call("Input.insertText", {"text": values[field]}, sess)
        elif kind == "click":
            quad = cdp.call("DOM.getBoxModel", {"nodeId": node(cdp, sess, step["selector"])}, sess)["model"]["content"]
            x, y = (quad[0] + quad[4]) / 2, (quad[1] + quad[5]) / 2
            for event in ("mousePressed", "mouseReleased"):
                cdp.call("Input.dispatchMouseEvent",
                         {"type": event, "x": x, "y": y, "button": "left", "clickCount": 1}, sess)
        elif kind == "wait":
            time.sleep(float(step.get("seconds", 1)))
        elif kind == "manual":
            input(f"  {step.get('note', 'Do this step by hand')} — press Enter when done ")
        elif kind == "expect":
            deadline = time.monotonic() + float(step.get("timeout", 20))
            while not cdp.url(target).startswith(step["url_prefix"]):
                if time.monotonic() > deadline:
                    raise SystemExit(f"step {number}: the page did not reach the expected address")
                time.sleep(0.5)
        else:
            raise SystemExit(f"step {number}: unknown step kind {kind}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["open", "probe", "login"])
    ap.add_argument("--url", default="about:blank", help="page to open (open, probe)")
    ap.add_argument("--scenario", help="scenario JSON with fields and steps (login)")
    ap.add_argument("--values", help="JSON file with the field values, filled by the tester (login)")
    ap.add_argument("--shot", help="where to save a PNG of the page after the steps (login)")
    ap.add_argument("--keep-open", action="store_true", help="leave the test Chrome open at the end (login)")
    ap.add_argument("--chrome", default=CHROME_MAC)
    args = ap.parse_args()

    if sys.platform == "win32":
        raise SystemExit("this spike script covers macOS and Linux; Windows is a separate item")
    PROFILE.mkdir(parents=True, exist_ok=True)
    os.chmod(HOME, 0o700)

    if args.mode == "open":
        subprocess.Popen([args.chrome, f"--user-data-dir={PROFILE}", *COMMON, args.url])
        print(f"test Chrome started with the profile {PROFILE}; close it yourself when done")
        return

    cdp = Pipe(args.chrome, PROFILE, args.url if args.mode == "probe" else "about:blank")
    keep = False
    try:
        target, sess = cdp.page()
        if args.mode == "probe":
            time.sleep(3)
            root = cdp.call("DOM.getDocument", {"depth": 0}, sess)["root"]["nodeId"]
            ids = cdp.call("DOM.querySelectorAll", {"nodeId": root, "selector": "input, button, select, textarea, form"}, sess)["nodeIds"]
            fields = []
            for node_id in ids:
                a = attrs(cdp, sess, node_id)
                tag = cdp.call("DOM.describeNode", {"nodeId": node_id}, sess)["node"]["nodeName"].lower()
                fields.append({"tag": tag, **{k: a[k] for k in ("type", "id", "name", "autocomplete", "action") if k in a}})
            print(json.dumps({"url": cdp.url(target), "fields": fields}, ensure_ascii=False, indent=2))
            return
        scenario = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
        values = json.loads(Path(args.values).read_text(encoding="utf-8"))
        secret = {f["name"] for f in scenario["fields"] if f.get("secret")}
        missing = [f["name"] for f in scenario["fields"] if not values.get(f["name"])]
        if missing:
            raise SystemExit("the values file has no value for: " + ", ".join(missing))
        run_steps(cdp, target, sess, scenario["steps"], values, secret)
        if args.shot:
            data = cdp.call("Page.captureScreenshot", {"format": "png"}, sess)["data"]
            Path(args.shot).write_bytes(base64.b64decode(data))
            print(f"screenshot saved: {args.shot}")
        print(json.dumps({"final_url": cdp.url(target), "result": "ok"}))
        keep = args.keep_open
    finally:
        if keep:
            print("the test Chrome stays open; note: it ends when its debug pipe closes with this script")
            input("press Enter to close the test Chrome ")
        cdp.close()


if __name__ == "__main__":
    main()
