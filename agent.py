"""One agent image, three roles.

The suite watches the sibling fixtures rather than inventing work: it reads
the dashboards' own JSON APIs, so a run says something true about the install
it is running in. Deterministic on purpose -- a demo agent that needs a model
endpoint to answer costs money to idle and fails for reasons unrelated to the
thing being demonstrated.

Roles:
  triage     read each watched app's /health and /selftest, classify what it finds
  summarize  turn a triage result into a short brief
  review     render a decision for a human gate to approve or reject

Input arrives as ASTROLIFT_AGENT_INPUT (JSON) when a workflow stage passes the
prior stage's output; stdout is the result surface the dispatch layer captures.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROLE = os.environ.get("AGENT_ROLE", "triage")
# Comma-separated base URLs. Defaults to the two dashboards in this suite's
# own org, reachable in-cluster by service DNS.
WATCHED = [u.strip() for u in os.environ.get(
    "WATCHED_APPS",
    "http://web.conflict-conflict-quake-dash.svc.cluster.local:8080,"
    "http://web.conflict-conflict-exo-dash.svc.cluster.local:8080",
).split(",") if u.strip()]
TIMEOUT = int(os.environ.get("PROBE_TIMEOUT", "10"))

# Above this an event is worth a human's attention rather than a log line.
NOTABLE_MAGNITUDE = float(os.environ.get("NOTABLE_MAGNITUDE", "6.0"))


def stage_input() -> dict:
    raw = os.environ.get("ASTROLIFT_AGENT_INPUT", "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # A malformed hand-off is worth saying out loud, not swallowing.
        return {"_unparsed_input": raw[:500]}


def get_json(url: str) -> tuple[dict | None, str | None]:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:
        return None, str(exc)


def app_name(base: str) -> str:
    """A readable label for a watched base URL.

    In-cluster these are `http://web.<namespace>.svc.cluster.local:8080`, where
    the namespace is the interesting part. Anything else (an IP during local
    testing, an external hostname) falls back to the host, which is at least
    true -- splitting on "." unconditionally turns 127.0.0.1 into "0".
    """
    host = urllib.parse.urlparse(base).hostname or base
    parts = host.split(".")
    if len(parts) > 2 and parts[-1] == "local" and "svc" in parts:
        return parts[1]
    return host


def triage() -> dict:
    findings = []
    for base in WATCHED:
        name = app_name(base)
        health, herr = get_json(f"{base}/health")
        self_, serr = get_json(f"{base}/selftest")

        if herr:
            findings.append({"app": name, "verdict": "unreachable", "detail": herr,
                             "severity": "critical"})
            continue
        failed = [c for c in (self_ or {}).get("checks", []) if c.get("ok") is False]
        if failed:
            findings.append({
                "app": name, "verdict": "degraded", "severity": "warning",
                "detail": "; ".join(f"{c['service']}: {c.get('error') or 'failed'}" for c in failed),
            })
        else:
            findings.append({"app": name, "verdict": "healthy", "severity": "ok",
                             "detail": serr or "all checks passed"})

        summary, _ = get_json(f"{base}/api/summary")
        if summary and summary.get("max_mag") and summary["max_mag"] >= NOTABLE_MAGNITUDE:
            findings.append({
                "app": name, "verdict": "notable", "severity": "warning",
                "detail": f"M{summary['max_mag']} at {summary.get('strongest_place', 'unknown')}",
            })

    worst = "ok"
    for level in ("critical", "warning"):
        if any(f["severity"] == level for f in findings):
            worst = level
            break
    return {"role": "triage", "watched": len(WATCHED), "worst": worst, "findings": findings}


def summarize(prior: dict) -> dict:
    findings = prior.get("findings", [])
    if not findings:
        return {"role": "summarize", "headline": "Nothing to report: no findings in the input.",
                "lines": []}
    by = {}
    for f in findings:
        by.setdefault(f["verdict"], []).append(f["app"])
    headline = ", ".join(f"{len(apps)} {verdict}" for verdict, apps in sorted(by.items()))
    return {
        "role": "summarize",
        "headline": f"Across {prior.get('watched', 0)} watched apps: {headline}.",
        "lines": [f"[{f['severity']}] {f['app']}: {f['verdict']} — {f['detail']}" for f in findings],
        "worst": prior.get("worst", "ok"),
    }


def review(prior: dict) -> dict:
    """Render a recommendation. The decision itself belongs to the human_gate
    stage that follows -- this stage states a case, it does not approve."""
    worst = prior.get("worst", "ok")
    recommend = {"ok": "no action", "warning": "acknowledge",
                 "critical": "page someone"}.get(worst, "acknowledge")
    return {
        "role": "review",
        "recommendation": recommend,
        "rationale": prior.get("headline", "no summary supplied"),
        "detail": prior.get("lines", []),
        "requires_human": worst != "ok",
    }


ROLES = {"triage": lambda p: triage(), "summarize": summarize, "review": review}


def main() -> int:
    started = time.time()
    if ROLE not in ROLES:
        print(json.dumps({"error": f"unknown AGENT_ROLE {ROLE!r}",
                          "known": sorted(ROLES)}), flush=True)
        return 2

    prior = stage_input()
    result = ROLES[ROLE](prior)
    result.update({
        "app": "conflict-agent-suite",
        "pod": socket.gethostname(),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_s": round(time.time() - started, 2),
        "received_input": bool(prior),
    })
    print(json.dumps(result, indent=2), flush=True)
    # A triage that found something critical still exits 0: the finding is the
    # result, not a failure of the run. A stage failing on a real finding would
    # make on_failure=retry loop forever against a genuinely broken app.
    return 0


if __name__ == "__main__":
    sys.exit(main())
