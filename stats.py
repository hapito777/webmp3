"""mp3 download statistics CLI.

Reads logs/history.log (plus rotated backups) and reports stats.

Usage:
    python stats.py summary
    python stats.py recent [-n 20]
    python stats.py top [-n 10]
    python stats.py ip
    python stats.py failures [-n 20]
"""
import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_LOG = os.environ.get("MP3_LOG", "logs/history.log")

LINE_RE = re.compile(r"^(\S+)\s+(\w+)\s+(.+)$")
FIELD_RE = re.compile(r"""(\w+)=(?:'([^']*)'|"([^"]*)"|(\S+))""")

EVENT_PREFIXES = [
    ("request rejected", "rejected"),
    ("request ", "request"),
    ("success ", "downloaded"),
    ("delivered", "delivered"),
    ("oversized", "oversized"),
    ("download failed", "failed"),
    ("unexpected error", "error"),
    ("mp3 not produced", "not_produced"),
]


def parse_fields(text):
    out = {}
    for m in FIELD_RE.finditer(text):
        key = m.group(1)
        val = m.group(2) if m.group(2) is not None else (m.group(3) if m.group(3) is not None else m.group(4))
        out[key] = val
    return out


def classify(msg):
    for prefix, name in EVENT_PREFIXES:
        if msg.startswith(prefix):
            return name
    return "other"


def iter_events(log_path):
    log_path = Path(log_path)
    parent = log_path.parent
    name = log_path.name
    if not parent.exists():
        return
    rotated = []
    for p in parent.glob(f"{name}.*"):
        suffix = p.suffix.lstrip(".")
        if suffix.isdigit():
            rotated.append((int(suffix), p))
    rotated.sort(reverse=True)
    files = [p for _, p in rotated]
    if log_path.exists():
        files.append(log_path)
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            m = LINE_RE.match(line)
            if not m:
                continue
            ts, level, msg = m.groups()
            yield {
                "ts": ts,
                "level": level,
                "event": classify(msg),
                "msg": msg,
                **parse_fields(msg),
            }


def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def cmd_summary(events):
    counts = Counter()
    total_size = 0
    total_duration = 0
    for e in events:
        counts[e["event"]] += 1
        if e["event"] == "downloaded":
            try:
                total_size += int(e.get("size", 0))
            except (ValueError, TypeError):
                pass
            try:
                total_duration += int(e.get("duration", 0))
            except (ValueError, TypeError):
                pass
    rows = [
        ("requests", counts.get("request", 0)),
        ("downloaded", counts.get("downloaded", 0)),
        ("delivered", counts.get("delivered", 0)),
        ("oversized", counts.get("oversized", 0)),
        ("failed", counts.get("failed", 0)),
        ("rejected", counts.get("rejected", 0)),
        ("errors", counts.get("error", 0)),
    ]
    width = max(len(k) for k, _ in rows)
    for k, v in rows:
        print(f"{k:<{width}}  {v}")
    print()
    print(f"total mp3 bytes:   {fmt_bytes(total_size)}")
    mins = total_duration // 60
    secs = total_duration % 60
    print(f"total audio time:  {mins}m {secs}s")


def cmd_recent(events, n):
    successes = [e for e in events if e["event"] == "downloaded"]
    if not successes:
        print("no successful downloads yet")
        return
    for e in successes[-n:]:
        title = e.get("title", "?")
        try:
            size_mb = int(e.get("size", 0)) / 1024 / 1024
        except (ValueError, TypeError):
            size_mb = 0.0
        duration = e.get("duration", "?")
        print(f"{e['ts']}  {size_mb:6.2f} MB  {duration:>4}s  {title}")


def cmd_top(events, n):
    titles = Counter()
    for e in events:
        if e["event"] == "downloaded" and "title" in e:
            titles[e["title"]] += 1
    if not titles:
        print("no successful downloads yet")
        return
    for title, count in titles.most_common(n):
        print(f"{count:>4}  {title}")


def cmd_ip(events):
    by_who = Counter()
    for e in events:
        if e["event"] == "request":
            who = e.get("who") or e.get("ip")
            if who:
                by_who[who] += 1
    if not by_who:
        print("no requests recorded")
        return
    for who, count in by_who.most_common():
        print(f"{count:>4}  {who}")


def cmd_sources(events):
    requests_by = Counter()
    downloaded_by = Counter()
    delivered_by = Counter()
    oversized_by = Counter()
    failures_by = Counter()
    bytes_by = Counter()
    for e in events:
        src = e.get("source") or "web"
        if e["event"] == "request":
            requests_by[src] += 1
        elif e["event"] == "downloaded":
            downloaded_by[src] += 1
            try:
                bytes_by[src] += int(e.get("size", 0))
            except (ValueError, TypeError):
                pass
        elif e["event"] == "delivered":
            delivered_by[src] += 1
        elif e["event"] == "oversized":
            oversized_by[src] += 1
        elif e["event"] in ("failed", "error", "not_produced", "rejected"):
            failures_by[src] += 1

    sources = sorted(
        set(requests_by) | set(downloaded_by) | set(delivered_by)
        | set(oversized_by) | set(failures_by)
    )
    if not sources:
        print("no events recorded")
        return

    header = (
        f"{'source':<10} {'requests':>9} {'downloaded':>11} {'delivered':>10} "
        f"{'oversized':>10} {'failures':>9} {'size':>12}"
    )
    print(header)
    print("-" * len(header))
    for src in sources:
        print(
            f"{src:<10} {requests_by[src]:>9} {downloaded_by[src]:>11} "
            f"{delivered_by[src]:>10} {oversized_by[src]:>10} "
            f"{failures_by[src]:>9} {fmt_bytes(bytes_by[src]):>12}"
        )


def cmd_failures(events, n):
    fails = [e for e in events if e["event"] in ("failed", "error", "not_produced", "rejected")]
    if not fails:
        print("no failures recorded")
        return
    for e in fails[-n:]:
        url = e.get("url", "")
        err = e.get("error", e.get("reason", ""))
        print(f"{e['ts']}  {e['event']:<12} {url}  {err}")


def main():
    ap = argparse.ArgumentParser(prog="mp3-stats", description="mp3 download stats")
    ap.add_argument("--log", default=DEFAULT_LOG, help=f"path to history.log (default: {DEFAULT_LOG})")
    ap.add_argument(
        "--source",
        choices=["all", "web", "telegram"],
        default="all",
        help="filter events by source (default: all)",
    )
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True

    sub.add_parser("summary", help="overall counts and totals")
    p_recent = sub.add_parser("recent", help="recent successful downloads")
    p_recent.add_argument("-n", type=int, default=20)
    p_top = sub.add_parser("top", help="most-downloaded titles")
    p_top.add_argument("-n", type=int, default=10)
    sub.add_parser("ip", help="requests grouped by client (IP / telegram user)")
    sub.add_parser("sources", help="breakdown by source (web vs telegram)")
    p_fail = sub.add_parser("failures", help="recent failures")
    p_fail.add_argument("-n", type=int, default=20)

    args = ap.parse_args()
    events = list(iter_events(Path(args.log)))
    if not events:
        print(f"no events in {args.log}", file=sys.stderr)
        return 1

    if args.source == "web":
        events = [e for e in events if e.get("source", "web") == "web"]
    elif args.source == "telegram":
        events = [e for e in events if e.get("source") == "telegram"]

    if args.cmd == "summary":
        cmd_summary(events)
    elif args.cmd == "recent":
        cmd_recent(events, args.n)
    elif args.cmd == "top":
        cmd_top(events, args.n)
    elif args.cmd == "ip":
        cmd_ip(events)
    elif args.cmd == "sources":
        cmd_sources(events)
    elif args.cmd == "failures":
        cmd_failures(events, args.n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
