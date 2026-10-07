#!/usr/bin/env python3
"""Task state operations over TASK.md's YAML frontmatter.

This is the single writer of a task's frontmatter: skills never edit the YAML
by hand. A task lives in ~/.claude/work/<KEY>/ (WORK_DIR overrides the root).
Every write takes the task's lock (flock on <task dir>/.task.lock, released
by the kernel however the process ends), writes a temporary file next to the
real file and renames it over it. The write goes to realpath(TASK.md), so a
`home: repo` symlink into the repo's docs/ survives (an os.replace over the
symlink itself would turn it into a regular file).

Subcommands (status.sh wraps this file):
  show [--json] [--no-live]      read-only: rows, live PR state against the
                                 .status/ snapshots, reports, lineage, a next
                                 action per row and the consistency check.
                                 Never writes anything, not even snapshots.
  show --all [--json] [--live]   read-only: one summary line per task under
                                 WORK_DIR (key, title, coordinator and its
                                 lineage state, row count by phase, most
                                 urgent next action, ranked CI red > new
                                 events/blocked workers > launchable >
                                 waits). Local state only unless --live.
  workers-in <worktree> [--json] read-only: who lives in a worktree (lineage
                                 records whose agent.worktree matches, herdr
                                 agents whose cwd is inside it). For adoption:
                                 fills `workers` on adopted rows.
  add-row <id> [k=v ...]         add a deliverable row (idempotent: an
                                 existing row is updated with the given keys)
  set <id> k=v [...]             set fields on one row
  set-root k=v [...]             set top-level fields
  promote <id>                   make the row its own child task. Idempotent,
                                 fixed order: create the child task dir, then
                                 point the parent row's `task:` at it; a
                                 re-run completes whatever is missing.
  ack <id>                       snapshot the row's live PR state into
                                 .status/<id>.json (its events are attended)
  gate <id> <name> done|open     mark one of the row's gates

k=v values parse as JSON when they can (lists, objects, numbers, booleans);
anything else is the literal string. The task directory is --dir when given,
else the closest directory upwards from the cwd holding a TASK.md, else the
task whose deliverables list the cwd's worktree or git branch.

Environment: WORK_DIR (tasks root, default ~/.claude/work), LINEAGE_DIR
(lineage records, default ~/.claude/agent-lineage), GH_BIN_PATH (the gh
binary, default gh), HERDR_BIN_PATH (the herdr binary, default herdr).
"""
import datetime
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

WORK_DIR = os.environ.get("WORK_DIR") or os.path.expanduser("~/.claude/work")
LINEAGE_DIR = os.environ.get("LINEAGE_DIR") or os.path.expanduser("~/.claude/agent-lineage")
GH = os.environ.get("GH_BIN_PATH") or "gh"
HERDR = os.environ.get("HERDR_BIN_PATH") or "herdr"

PHASES = ("planned", "launching", "creating-child", "implementing",
          "pr-draft", "in-review", "merged", "released", "dropped")
PHASE_ORDER = {p: i for i, p in enumerate(
    ("planned", "launching", "creating-child", "implementing",
     "pr-draft", "in-review", "closed", "merged", "released"))}
ROW_KEY_ORDER = ("id", "child", "task", "repo", "branch", "base", "base_sha",
                 "depends_on", "gates", "worktree", "workers", "pr",
                 "authority", "phase")
ROOT_KEY_ORDER = ("key", "title", "link", "parent", "home", "stack", "plan",
                  "coordinator", "legacy", "aliases", "authority",
                  "deliverables")


def die(msg):
    print(f"status: {msg}", file=sys.stderr)
    sys.exit(1)


def now():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- mini YAML
# Parser and emitter for the subset this script writes: a top-level map of
# scalars, flow lists/maps on one line, and a block list of block maps
# (deliverables). No anchors, no multiline scalars, no trailing comments.

class YamlError(Exception):
    pass


PLAIN = re.compile(r"[A-Za-z0-9_./@#+*<>=-]+$")


def parse_scalar(s):
    s = s.strip()
    if s == "":
        return ""
    if s[0] in "\"'":
        if len(s) < 2 or s[-1] != s[0]:
            raise YamlError(f"unterminated quote in {s!r}")
        return json.loads(s) if s[0] == '"' else s[1:-1].replace("''", "'")
    if s in ("true", "True"):
        return True
    if s in ("false", "False"):
        return False
    if s in ("null", "~"):
        return None
    for conv in (int, float):
        try:
            return conv(s)
        except ValueError:
            pass
    return s


def parse_flow(s, i):
    """Parse a flow value ([...], {...} or a scalar) in s starting at i.
    Returns (value, index after it)."""
    while i < len(s) and s[i] == " ":
        i += 1
    if i >= len(s):
        return "", i
    if s[i] == "[":
        out, i = [], i + 1
        while True:
            while i < len(s) and s[i] in " ,":
                i += 1
            if i >= len(s):
                raise YamlError(f"unterminated [ in {s!r}")
            if s[i] == "]":
                return out, i + 1
            v, i = parse_flow(s, i)
            out.append(v)
    if s[i] == "{":
        out, i = {}, i + 1
        while True:
            while i < len(s) and s[i] in " ,":
                i += 1
            if i >= len(s):
                raise YamlError(f"unterminated {{ in {s!r}")
            if s[i] == "}":
                return out, i + 1
            j = s.index(":", i)
            key = parse_scalar(s[i:j])
            v, i = parse_flow(s, j + 1)
            out[key] = v
    if s[i] in "\"'":
        q, j = s[i], i + 1
        while j < len(s):
            if s[j] == q and not (q == '"' and s[j - 1] == "\\"):
                break
            j += 1
        if j >= len(s):
            raise YamlError(f"unterminated quote in {s!r}")
        return parse_scalar(s[i:j + 1]), j + 1
    j = i
    while j < len(s) and s[j] not in ",]}":
        j += 1
    return parse_scalar(s[i:j]), j


def parse_value(s):
    s = s.strip()
    if s and s[0] in "[{":
        v, i = parse_flow(s, 0)
        if s[i:].strip():
            raise YamlError(f"trailing text after flow value: {s!r}")
        return v
    return parse_scalar(s)


def indent_of(line):
    return len(line) - len(line.lstrip(" "))


def parse_block(lines, idx, indent):
    """Parse a block map or block list at exactly `indent`. Returns
    (value, next idx)."""
    items, mapping = None, None
    while idx < len(lines):
        line = lines[idx]
        if not line.strip() or line.lstrip().startswith("#"):
            idx += 1
            continue
        ind = indent_of(line)
        if ind < indent:
            break
        if ind > indent:
            raise YamlError(f"bad indent at line: {line!r}")
        stripped = line.strip()
        if stripped.startswith("- "):
            if mapping is not None:
                raise YamlError(f"list item inside a map: {line!r}")
            items = items if items is not None else []
            # a list item is a map whose first entry sits after "- "
            first = stripped[2:]
            item_indent = ind + 2
            if ":" not in first:
                items.append(parse_value(first))
                idx += 1
                continue
            k, _, rest = first.partition(":")
            entry = {}
            if rest.strip():
                entry[parse_scalar(k)] = parse_value(rest)
                idx += 1
            else:
                idx += 1
                sub, idx = parse_block(lines, idx, item_indent + 2)
                entry[parse_scalar(k)] = sub
            more, idx = parse_block(lines, idx, item_indent)
            if more:
                if not isinstance(more, dict):
                    raise YamlError(f"expected map entries after list item {first!r}")
                entry.update(more)
            items.append(entry)
            continue
        if mapping is None and items is not None:
            break
        mapping = mapping if mapping is not None else {}
        if ":" not in stripped:
            raise YamlError(f"expected 'key: value': {line!r}")
        k, _, rest = stripped.partition(":")
        key = parse_scalar(k)
        if rest.strip():
            mapping[key] = parse_value(rest)
            idx += 1
        else:
            sub_idx = idx + 1
            sub, sub_end = parse_block(lines, sub_idx, _next_indent(lines, sub_idx, indent))
            if sub is None or (sub_end == sub_idx):
                mapping[key], idx = "", idx + 1
            else:
                mapping[key], idx = sub, sub_end
    return (items if items is not None else mapping), idx


def _next_indent(lines, idx, parent_indent):
    for line in lines[idx:]:
        if line.strip() and not line.lstrip().startswith("#"):
            ind = indent_of(line)
            return ind if ind > parent_indent else parent_indent + 2
    return parent_indent + 2


def parse_frontmatter(text):
    value, _ = parse_block(text.splitlines(), 0, 0)
    return value or {}


def emit_scalar(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s and PLAIN.match(s) and parse_scalar(s) == s:
        return s
    return json.dumps(s, ensure_ascii=False)


def emit_flow(v):
    if isinstance(v, list):
        return "[" + ", ".join(emit_flow(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{emit_scalar(k)}: {emit_flow(x)}" for k, x in v.items()) + "}"
    return emit_scalar(v)


def _ordered(d, order):
    keys = [k for k in order if k in d] + [k for k in d if k not in order]
    return [(k, d[k]) for k in keys]


def emit_frontmatter(data):
    out = []
    for k, v in _ordered(data, ROOT_KEY_ORDER):
        if k == "deliverables" and isinstance(v, list) and v:
            out.append("deliverables:")
            for row in v:
                first = True
                for rk, rv in _ordered(row, ROW_KEY_ORDER):
                    lead = "  - " if first else "    "
                    first = False
                    val = emit_flow(rv) if isinstance(rv, (list, dict)) else emit_scalar(rv)
                    out.append(f"{lead}{rk}: {val}")
        elif isinstance(v, (list, dict)):
            out.append(f"{k}: {emit_flow(v)}")
        else:
            out.append(f"{k}: {emit_scalar(v)}")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------ task file I/O

def split_task_md(text):
    if not text.startswith("---\n"):
        die("TASK.md has no YAML frontmatter (must start with ---)")
    end = text.find("\n---\n", 4)
    if end < 0:
        die("TASK.md frontmatter is not closed with ---")
    return text[4:end + 1], text[end + 5:]


def read_task(task_dir):
    path = os.path.join(task_dir, "TASK.md")
    if not os.path.exists(path):
        die(f"no TASK.md in {task_dir}")
    with open(path) as f:
        front_text, body = split_task_md(f.read())
    try:
        front = parse_frontmatter(front_text)
    except YamlError as e:
        die(f"{path}: {e}")
    if not isinstance(front, dict):
        die(f"{path}: frontmatter is not a map")
    front.setdefault("deliverables", [])
    if not isinstance(front["deliverables"], list):
        die(f"{path}: deliverables is not a list")
    return front, body


class LockedTask:
    """The task's lock, held while TASK.md is read, changed and renamed.
    Writes go to realpath so a `home: repo` symlink survives."""

    def __init__(self, task_dir):
        self.dir = task_dir
        self.path = os.path.join(task_dir, "TASK.md")
        self.lock = open(os.path.join(task_dir, ".task.lock"), "w")

    def __enter__(self):
        deadline = time.time() + 10
        while True:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.time() > deadline:
                    die(f"{self.path}: another writer holds the lock")
                time.sleep(0.1)

    def __exit__(self, *exc):
        fcntl.flock(self.lock, fcntl.LOCK_UN)
        self.lock.close()

    def read(self):
        return read_task(self.dir)

    def write(self, front, body):
        real = os.path.realpath(self.path)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(real), prefix=".task-")
        with os.fdopen(fd, "w") as f:
            f.write("---\n" + emit_frontmatter(front) + "---\n" + body)
        os.replace(tmp, real)


# ------------------------------------------------------------ task finding

def is_task_dir(path):
    return os.path.isfile(os.path.join(path, "TASK.md"))


def all_task_dirs():
    if not os.path.isdir(WORK_DIR):
        return []
    return sorted(os.path.join(WORK_DIR, d) for d in os.listdir(WORK_DIR)
                  if is_task_dir(os.path.join(WORK_DIR, d)))


def herdr_snapshot():
    """The herdr snapshot, or None (no herdr, not running, bad output)."""
    try:
        r = subprocess.run([HERDR, "api", "snapshot"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return None
        return json.loads(r.stdout)["result"]["snapshot"]
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        return None


def calling_agent_name():
    """The calling pane's herdr agent name, as lineage.sh resolves it:
    HERDR_PANE_ID matched against the snapshot's agents. None outside herdr
    or for an unnamed agent."""
    pane = os.environ.get("HERDR_PANE_ID")
    if not pane:
        return None
    snap = herdr_snapshot()
    agent = next((a for a in (snap or {}).get("agents", [])
                  if a.get("pane_id") == pane), None)
    return (agent or {}).get("name")


def git_out(args, cwd):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def find_task_dir(explicit):
    if explicit:
        path = os.path.abspath(explicit)
        if not is_task_dir(path):
            die(f"{path} has no TASK.md")
        return path
    # 1. the cwd or an ancestor is a task directory
    cur = os.getcwd()
    while True:
        if is_task_dir(cur):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    # 2. the cwd is a worktree listed in some task's deliverables (by
    #    worktree path or by branch)
    top = git_out(["rev-parse", "--show-toplevel"], os.getcwd())
    branch = git_out(["symbolic-ref", "--short", "HEAD"], os.getcwd())
    for task_dir in all_task_dirs():
        front, _ = read_task(task_dir)
        for row in front.get("deliverables", []):
            if top and row.get("worktree") == top:
                return task_dir
            if branch and row.get("branch") == branch:
                return task_dir
    # 3. the calling agent is some task's coordinator (its cwd need not be
    #    the task directory, e.g. a root task coordinated from the repo)
    name = calling_agent_name()
    if name:
        for task_dir in all_task_dirs():
            front, _ = read_task(task_dir)
            if front.get("coordinator") == name:
                return task_dir
    die("no task found: not inside a task directory, no deliverable matches "
        "this worktree or branch, and no task names this agent as its "
        f"coordinator (tasks root: {WORK_DIR})")


def find_row(front, row_id):
    for row in front.get("deliverables", []):
        if str(row.get("id")) == str(row_id):
            return row
    die(f"no deliverable with id {row_id!r} "
        f"(have: {', '.join(str(r.get('id')) for r in front.get('deliverables', [])) or 'none'})")


# ------------------------------------------------------------------ live PR

def gh_pr(url):
    """One PR's live state, summarized. Raises RuntimeError on any failure."""
    fields = ("state,isDraft,reviewDecision,baseRefName,headRefOid,"
              "mergedAt,url,statusCheckRollup,comments")
    try:
        r = subprocess.run([GH, "pr", "view", url, "--json", fields],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(str(e))
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip() or "gh failed")
    d = json.loads(r.stdout)
    ok = fail = pending = 0
    for c in d.get("statusCheckRollup") or []:
        concl = (c.get("conclusion") or c.get("state") or "").upper()
        status = (c.get("status") or "").upper()
        if concl in ("SUCCESS", "NEUTRAL", "SKIPPED"):
            ok += 1
        elif concl in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED",
                       "ACTION_REQUIRED", "STARTUP_FAILURE"):
            fail += 1
        elif status and status != "COMPLETED" or concl in ("PENDING", "EXPECTED"):
            pending += 1
    comments = d.get("comments") or []
    return {
        "state": d.get("state"), "is_draft": bool(d.get("isDraft")),
        "review_decision": d.get("reviewDecision") or "",
        "base": d.get("baseRefName"), "head": d.get("headRefOid"),
        "merged_at": d.get("mergedAt"), "url": d.get("url") or url,
        "checks": {"ok": ok, "fail": fail, "pending": pending},
        "comments": len(comments),
    }


def snapshot_path(task_dir, row_id):
    return os.path.join(task_dir, ".status", f"{row_id}.json")


def read_snapshot(task_dir, row_id):
    path = snapshot_path(task_dir, row_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except ValueError:
        return None


# ------------------------------------------------------------------ reports

REPORT_RE = re.compile(r"-r(\d+)\.md$")


def read_report(task_dir, row_id):
    """The latest report for a row: reports/<id>.md is round 1,
    reports/<id>-rN.md later rounds. Returns (round, frontmatter) or None."""
    rep_dir = os.path.join(task_dir, "reports")
    if not os.path.isdir(rep_dir):
        return None
    best = None
    for name in os.listdir(rep_dir):
        if name == f"{row_id}.md":
            rnd = 1
        else:
            m = REPORT_RE.search(name)
            if not (m and name == f"{row_id}-r{m.group(1)}.md"):
                continue
            rnd = int(m.group(1))
        if best and best[0] >= rnd:
            continue
        with open(os.path.join(rep_dir, name)) as f:
            text = f.read()
        if not text.startswith("---\n"):
            continue
        try:
            front, _ = split_task_md(text)
        except SystemExit:
            continue
        try:
            best = (rnd, parse_frontmatter(front))
        except YamlError:
            continue
    return best


def read_lineage(name):
    path = os.path.join(LINEAGE_DIR, f"{name}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            rec = json.load(f)
    except ValueError:
        return None
    return {"state": rec.get("state"), "summary": rec.get("summary", "")}


def plan_sha(front):
    plan = front.get("plan")
    if not plan or plan == "none" or not os.path.exists(plan):
        return None
    with open(plan, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ------------------------------------------------------------------- show

def norm_gates(row):
    out = []
    for g in row.get("gates") or []:
        if isinstance(g, dict):
            out.append({"name": g.get("name", ""), "done": bool(g.get("done"))})
        else:
            out.append({"name": str(g), "done": False})
    return out


def effective_phase(row, live, child_front):
    if child_front is not None:  # promoted: aggregate of the child task
        phases = [effective_phase(r, None, None)
                  for r in child_front.get("deliverables", [])
                  if r.get("phase") != "dropped"]
        phases = [p for p in phases if p in PHASE_ORDER]
        return min(phases, key=PHASE_ORDER.get) if phases else "planned"
    if live:
        if live["state"] == "MERGED":
            return "merged" if row.get("phase") != "released" else "released"
        if live["state"] == "CLOSED":
            return "closed"
        return "pr-draft" if live["is_draft"] else "in-review"
    return row.get("phase", "planned")


def dep_state(dep, rows_by_id, pr_cache, no_live):
    """One dependency's status: (met, description)."""
    until = dep.get("until", "merged")
    if "pr" in dep:
        label = dep["pr"]
        if no_live:
            return None, f"{label} until {until} (not checked: --no-live)"
        try:
            live = pr_cache(dep["pr"])
        except RuntimeError as e:
            return None, f"{label} until {until} (gh failed: {e})"
        met = live["state"] == "MERGED"
        return met, f"{label} until {until}: {'met' if met else live['state']}"
    target = rows_by_id.get(str(dep.get("id")))
    if target is None:
        return False, f"{dep.get('id')}: no such deliverable"
    if until == "stacked":
        # a stacked child starts right away on the other's branch
        return True, f"{dep['id']} stacked on {target.get('branch')}"
    phase = target.get("phase", "planned")
    met = phase in ("merged", "released")
    return met, f"{dep['id']} until merged: {'met' if met else phase}"


def diff_events(snap, live):
    if not snap or not live:
        return []
    old = snap.get("pr") or {}
    out = []
    if live["comments"] > old.get("comments", 0):
        out.append(f"{live['comments'] - old.get('comments', 0)} new comments")
    if old.get("head") and live["head"] != old["head"]:
        out.append("new commits")
    if live["review_decision"] != old.get("review_decision", ""):
        out.append(f"review: {live['review_decision'] or 'none'}")
    if live["checks"]["fail"] > 0 and old.get("checks", {}).get("fail", 0) == 0:
        out.append("checks went red")
    if live["state"] != old.get("state"):
        out.append(f"state: {live['state']}")
    return out


def urgent_signals(live, events):
    """What must never be hidden behind a wait: red CI, requested changes,
    new review comments."""
    out = []
    if live and live["checks"]["fail"]:
        out.append(f"CI red ({live['checks']['fail']})")
    if live and live["review_decision"] == "CHANGES_REQUESTED":
        out.append("changes requested")
    out.extend(e for e in events if "new comments" in e)
    return out


def next_action(row, phase, live, live_err, events, report, workers, deps_unmet, gates_pending):
    rid = row.get("id")
    if phase == "released":
        return "done"
    if phase == "merged":
        return f"merged (/task close {rid} only to verify a release)"
    if phase == "closed":
        return "PR closed without merge: decide (new round or drop)"
    if phase == "dropped":
        return "dropped"
    if deps_unmet:
        wait = "wait: " + "; ".join(desc for _, desc in deps_unmet)
        urgent = urgent_signals(live, events)
        if urgent:  # e.g. "CI red (2) · then wait: #8027 ..."
            return " · ".join(urgent) + " · then " + wait
        return wait
    if phase in ("launching", "creating-child"):
        return f"incomplete {phase}: re-run /task go {rid}"
    if phase == "planned":
        if gates_pending:
            return "gate: " + ", ".join(g["name"] for g in gates_pending) + \
                   f" (/task gate {rid} <name> done), then /task go {rid}"
        return f"launch: /task go {rid}"
    blocked = [w for w in workers if w.get("state") == "blocked-on-user"]
    if blocked:
        return f"answer {blocked[-1]['name']}: {blocked[-1]['summary'] or 'question in its pane'}"
    if phase in ("pr-draft", "in-review"):
        reasons = []
        if live and live["checks"]["fail"]:
            reasons.append(f"{live['checks']['fail']} checks failing")
        if live and live["review_decision"] == "CHANGES_REQUESTED":
            reasons.append("changes requested")
        reasons.extend(events)
        if reasons:
            return f"round: /task go {rid} ({'; '.join(dict.fromkeys(reasons))})"
        if live_err:
            return f"PR state unknown (gh failed: {live_err})"
        if gates_pending:
            return "gate: " + ", ".join(g["name"] for g in gates_pending) + \
                   f" (/task gate {rid} <name> done)"
        return "wait for review"
    # implementing
    if report and report.get("phase") == "awaiting-confirmation":
        return "worker awaits the '¿todo resuelto?' confirmation in its pane"
    if report and report.get("phase") == "blocked":
        return f"worker blocked: {report.get('summary', '')}"
    finished = [w for w in workers if w.get("state") == "finished"]
    if finished and all(w.get("state") == "finished" for w in workers if w):
        return f"read report: reports/{rid}.md"
    return "in progress" + (f" ({workers[-1]['name']})" if workers else "")


def consistency(front, task_dir, rows_info):
    key = front.get("key", "")
    findings = []
    lineage_names = set()
    if os.path.isdir(LINEAGE_DIR):
        lineage_names = {f[:-5] for f in os.listdir(LINEAGE_DIR) if f.endswith(".json")}
    known_workers = set()
    for info in rows_info:
        row = info["row"]
        rid = row.get("id")
        known_workers.update(row.get("workers") or [])
        wt = row.get("worktree")
        if wt and wt != "none" and not os.path.isdir(wt):
            findings.append(f"{rid}: worktree {wt} is gone; "
                            f"re-run /task go {rid} to recreate it")
        if wt and wt != "none" and os.path.isdir(wt) and not (row.get("workers") or []):
            findings.append(f"{rid}: worktree without a worker; "
                            f"launch one with /task go {rid}")
        for w in row.get("workers") or []:
            if w not in lineage_names:
                findings.append(f"{rid}: worker {w} has no lineage record; "
                                f"relaunch it or remove it with status.sh set")
        if row.get("task") and row.get("task") != "none":
            child_dir = os.path.join(WORK_DIR, str(row["task"]))
            if not is_task_dir(child_dir):
                findings.append(f"{rid}: promoted to {row['task']} but that task "
                                f"does not exist; re-run promote {rid}")
        if row.get("child") == "pending":
            keys = os.path.join(task_dir, "tickets", "keys.json")
            if os.path.exists(keys):
                findings.append(f"{rid}: children were created (tickets/keys.json) "
                                f"but the row still says child: pending; set it")
        if info.get("plan_stale"):
            findings.append(f"{rid}: its report validated an older plan.md "
                            f"(sha mismatch); the worker may be off-plan")
    # a child task pointing here that no row references
    for task_dir2 in all_task_dirs():
        if task_dir2 == task_dir:
            continue
        child_front, _ = read_task(task_dir2)
        if child_front.get("parent") == key:
            ck = child_front.get("key")
            if not any(i["row"].get("task") == ck for i in rows_info):
                findings.append(f"task {ck} says parent: {key} but no row points "
                                f"at it; finish its promote")
    # lineage records that claim this task but are in no row. A record whose
    # ref is the bare key (no #id) is task-level — the coordinator declared
    # with `lineage.sh self --ref <KEY>` — never a deliverable worker.
    coordinator = front.get("coordinator")
    for name in lineage_names - known_workers:
        if name == coordinator:
            continue
        rec_path = os.path.join(LINEAGE_DIR, f"{name}.json")
        try:
            with open(rec_path) as f:
                rec = json.load(f)
        except (OSError, ValueError):
            continue
        ref = (rec.get("task") or {}).get("ref") or ""
        if ref == key:
            continue
        if ref.split("#")[0] == key:
            findings.append(f"worker {name} claims this task but no row lists it; "
                            f"add it with status.sh set <id> workers=...")
    return findings


def collect_rows(task_dir, front, no_live):
    """Everything show needs per row: live PR state, events, report, lineage,
    deps, gates and the next action. Read-only."""
    rows_by_id = {str(r.get("id")): r for r in front.get("deliverables", [])}
    sha = plan_sha(front)
    cache = {}

    def pr_cache(url):
        if url not in cache:
            cache[url] = gh_pr(url)
        return cache[url]

    rows_info = []
    for row in front.get("deliverables", []):
        rid = row.get("id")
        live, live_err = None, None
        snap = read_snapshot(task_dir, rid)
        pr = row.get("pr")
        if pr and pr != "none" and not no_live:
            try:
                live = pr_cache(pr)
            except RuntimeError as e:
                live_err = str(e)
                live = (snap or {}).get("pr")  # fall back to the snapshot
        child_front = None
        if row.get("task") and row.get("task") != "none":
            child_dir = os.path.join(WORK_DIR, str(row["task"]))
            if is_task_dir(child_dir):
                child_front, _ = read_task(child_dir)
        rep = read_report(task_dir, rid)
        report = rep[1] if rep else None
        workers = []
        for w in row.get("workers") or []:
            lin = read_lineage(w) or {"state": "unknown", "summary": ""}
            workers.append({"name": w, **lin})
        deps = []
        for dep in row.get("depends_on") or []:
            met, desc = dep_state(dep, rows_by_id, pr_cache, no_live)
            deps.append({"met": met, "desc": desc})
        deps_unmet = [(d["met"], d["desc"]) for d in deps if d["met"] is False]
        gates = norm_gates(row)
        gates_pending = [g for g in gates if not g["done"]]
        events = diff_events(snap, live) if not live_err else []
        phase = effective_phase(row, live if not live_err else None, child_front)
        plan_stale = bool(sha and report and report.get("plan_sha256")
                          and report["plan_sha256"] not in ("none", sha))
        info = {
            "row": row, "phase": phase, "live": live, "live_error": live_err,
            "snapshot": snap, "events": events, "report": report,
            "report_round": rep[0] if rep else None, "workers": workers,
            "deps": deps, "gates": gates, "plan_stale": plan_stale,
        }
        info["next"] = next_action(row, phase, live, live_err, events, report,
                                   workers, deps_unmet, gates_pending)
        rows_info.append(info)
    return sha, rows_info


def cmd_show(task_dir, as_json, no_live):
    front, _ = read_task(task_dir)
    sha, rows_info = collect_rows(task_dir, front, no_live)
    findings = consistency(front, task_dir, rows_info)
    auth = front.get("authority") or {}
    result = {
        "dir": task_dir, "key": front.get("key"), "title": front.get("title"),
        "parent": front.get("parent"), "home": front.get("home"),
        "plan": front.get("plan"), "plan_sha256": sha,
        "authority": auth, "rows": rows_info, "consistency": findings,
    }
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    print(f"Task {front.get('key')} · {front.get('title')}")
    grants = ", ".join(auth.get("grants") or []) or "none"
    print(f"Dir: {task_dir}")
    print(f"Plan: {front.get('plan')}" +
          (f" (sha256 {sha[:8]})" if sha else "") +
          f" · Authority: {auth.get('mode', 'unset')} [{grants}]")
    print()
    headers = ("ID", "PHASE", "PR", "WORKER", "NEXT")
    table = []
    for info in rows_info:
        row = info["row"]
        live = info["live"]
        if live:
            c = live["checks"]
            pr_cell = (f"{live['state'].lower()}"
                       + (" draft" if live.get("is_draft") else "")
                       + (f" checks {c['fail']}F/{c['pending']}P/{c['ok']}O" if any(c.values()) else "")
                       + (" [stale]" if info["live_error"] else ""))
        elif row.get("pr") and row.get("pr") != "none":
            pr_cell = "error" if info["live_error"] else row["pr"]
        else:
            pr_cell = "-"
        w = info["workers"][-1] if info["workers"] else None
        worker_cell = f"{w['name']}: {w['state']}" if w else "-"
        stale = " plan-stale" if info["plan_stale"] else ""
        table.append((str(row.get("id")), info["phase"] + stale, pr_cell,
                      worker_cell, info["next"]))
    widths = [max(len(r[i]) for r in [headers, *table]) for i in range(5)]
    for r in [headers, *table]:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    if any(i["events"] for i in rows_info):
        print()
        for i in rows_info:
            if i["events"]:
                print(f"New since the {i['row'].get('id')} snapshot: "
                      + "; ".join(i["events"])
                      + f"  (attend or /task ack {i['row'].get('id')})")
    print()
    if findings:
        print("Consistency:")
        for f in findings:
            print(f"- {f}")
    else:
        print("Consistency: ok")


def urgency(info):
    """Rank for --all, lower first: red CI (live, or the local snapshot),
    new PR events or a worker blocked on the user, launchable/actionable
    rows, waits, everything else."""
    live = info["live"]
    snap_pr = (info["snapshot"] or {}).get("pr") or {}
    if ((live and live["checks"]["fail"])
            or snap_pr.get("checks", {}).get("fail")):
        return 0
    if (info["events"]
            or any(w.get("state") == "blocked-on-user" for w in info["workers"])):
        return 1
    if info["next"].startswith(("launch:", "round:", "gate:", "answer ",
                                "read report", "incomplete", "PR closed")):
        return 2
    if info["next"].startswith("wait") or " · then wait" in info["next"]:
        return 3
    if info["phase"] in ("merged", "released", "dropped"):
        return 5
    return 4


def cmd_show_all(as_json, live):
    tasks = []
    for task_dir in all_task_dirs():
        front, _ = read_task(task_dir)
        _, rows_info = collect_rows(task_dir, front, not live)
        coordinator = front.get("coordinator")
        has_coord = coordinator and coordinator != "none"
        lin = read_lineage(coordinator) if has_coord else None
        phases = {}
        for info in rows_info:
            phases[info["phase"]] = phases.get(info["phase"], 0) + 1
        urgent = None
        if rows_info:
            best = min(enumerate(rows_info),
                       key=lambda t: (urgency(t[1]), t[0]))[1]
            urgent = {"id": best["row"].get("id"), "next": best["next"]}
        tasks.append({
            "dir": task_dir, "key": front.get("key"),
            "title": front.get("title"), "coordinator": coordinator,
            "coordinator_state": (lin or {}).get("state") if has_coord else None,
            "phases": phases, "urgent": urgent,
        })
    if as_json:
        print(json.dumps({"work_dir": WORK_DIR, "live": live, "tasks": tasks},
                         indent=2, ensure_ascii=False))
        return
    headers = ("KEY", "TITLE", "COORD", "PHASES", "NEXT")
    table = []
    for t in tasks:
        title = t["title"] or ""
        if len(title) > 40:
            title = title[:39] + "…"
        if t["coordinator"] and t["coordinator"] != "none":
            coord = f"{t['coordinator']}: {t['coordinator_state'] or 'no record'}"
        else:
            coord = "-"
        ph = " ".join(f"{p}:{n}" for p, n in
                      sorted(t["phases"].items(),
                             key=lambda kv: PHASE_ORDER.get(kv[0], 99))) or "-"
        nxt = (f"{t['urgent']['id']}: {t['urgent']['next']}" if t["urgent"]
               else "no deliverables")
        table.append((t["key"] or "?", title, coord, ph, nxt))
    widths = [max(len(r[i]) for r in [headers, *table]) for i in range(5)]
    for r in [headers, *table]:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    if not live:
        print()
        print("Local state only (snapshots, lineage); --live asks gh.")


def cmd_workers_in(worktree, as_json):
    wt = os.path.realpath(os.path.expanduser(worktree))
    lineage = []
    if os.path.isdir(LINEAGE_DIR):
        for fn in sorted(os.listdir(LINEAGE_DIR)):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(LINEAGE_DIR, fn)) as f:
                    rec = json.load(f)
            except (OSError, ValueError):
                continue
            rec_wt = (rec.get("agent") or {}).get("worktree") or ""
            if rec_wt and os.path.realpath(os.path.expanduser(rec_wt)) == wt:
                lineage.append({"name": fn[:-5], "state": rec.get("state"),
                                "ref": (rec.get("task") or {}).get("ref", "")})
    herdr_agents = []
    for a in (herdr_snapshot() or {}).get("agents", []):
        cwd = a.get("cwd") or ""
        if cwd and os.path.realpath(cwd) == wt:
            herdr_agents.append({"name": a.get("name"),
                                 "pane_id": a.get("pane_id")})
    recorded = sorted(l["name"] for l in lineage)
    unrecorded = [h for h in herdr_agents if h["name"] not in recorded]
    result = {"worktree": wt, "workers": recorded, "lineage": lineage,
              "herdr": herdr_agents, "unrecorded": unrecorded}
    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return
    if not lineage and not herdr_agents:
        print(f"nobody found in {wt}")
        return
    for l in lineage:
        print(f"lineage: {l['name']} ({l['state']}, ref {l['ref'] or 'none'})")
    for h in herdr_agents:
        print(f"herdr: {h['name'] or '(unnamed)'} in pane {h['pane_id']}")
    print(f"workers value: {json.dumps(recorded)}")
    for h in unrecorded:
        who = f" ({h['name']})" if h["name"] else ""
        print(f"unrecorded agent in pane {h['pane_id']}{who}: name it and "
              f"record it (lineage.sh launch) before adding it to workers")


# ------------------------------------------------------------------ writes

def parse_kv(pairs):
    out = {}
    for pair in pairs:
        if "=" not in pair:
            die(f"expected k=v, got {pair!r}")
        k, _, v = pair.partition("=")
        try:
            out[k] = json.loads(v)
        except ValueError:
            out[k] = v
    return out


ROW_DEFAULTS = {"child": "none", "task": "none", "repo": "", "branch": "",
                "base": "", "depends_on": [], "gates": [], "worktree": "none",
                "workers": [], "pr": "none", "phase": "planned"}


def cmd_add_row(task_dir, row_id, kv):
    if "phase" in kv and kv["phase"] not in PHASES:
        die(f"phase must be one of {'|'.join(PHASES)}")
    with LockedTask(task_dir) as t:
        front, body = t.read()
        existing = next((r for r in front["deliverables"]
                         if str(r.get("id")) == str(row_id)), None)
        if existing is not None:
            existing.update(kv)
        else:
            row = {"id": row_id, **ROW_DEFAULTS, **kv}
            front["deliverables"].append(row)
        t.write(front, body)
    print(f"{'updated' if existing is not None else 'added'} row {row_id}")


def cmd_set(task_dir, row_id, kv):
    if not kv:
        die("set needs at least one k=v")
    if "phase" in kv and kv["phase"] not in PHASES:
        die(f"phase must be one of {'|'.join(PHASES)}")
    with LockedTask(task_dir) as t:
        front, body = t.read()
        row = find_row(front, row_id)
        row.update(kv)
        t.write(front, body)
    print(f"set {', '.join(kv)} on row {row_id}")


def cmd_set_root(task_dir, kv):
    if not kv:
        die("set-root needs at least one k=v")
    if "deliverables" in kv:
        die("deliverables is managed with add-row/set, not set-root")
    with LockedTask(task_dir) as t:
        front, body = t.read()
        front.update(kv)
        t.write(front, body)
    print(f"set {', '.join(kv)}")


def template(name):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "templates", name)
    with open(path) as f:
        return f.read()


def cmd_promote(task_dir, row_id):
    front, _ = read_task(task_dir)
    key = front.get("key")
    row = find_row(front, row_id)
    child = row.get("child")
    child_key = (row.get("task") if row.get("task") not in (None, "", "none")
                 else child if child not in (None, "", "none", "pending")
                 else f"{key}-{row_id}")
    child_dir = os.path.join(WORK_DIR, str(child_key))
    # step 1: the child task directory
    if is_task_dir(child_dir):
        child_front, _ = read_task(child_dir)
        if child_front.get("parent") != key:
            die(f"{child_dir} exists but its parent is "
            f"{child_front.get('parent')!r}, not {key!r}; not touching it")
        print(f"child task {child_key} already exists")
    else:
        os.makedirs(child_dir, exist_ok=True)
        _, tpl_body = split_task_md(template("TASK.md"))
        child_front = {
            "key": child_key, "title": f"{key} / {row_id}",
            "link": "none", "parent": key, "home": "work",
            "stack": front.get("stack", "none"), "plan": "none",
            "coordinator": "none", "aliases": [],
            "authority": {"mode": "task", "grants": []},
            "deliverables": [],
        }
        with LockedTask(child_dir) as t:
            # LockedTask.read needs the file; write it directly the first time
            t.write(child_front, tpl_body)
        dec = os.path.join(child_dir, "DECISIONS.md")
        if not os.path.exists(dec):
            with open(dec, "w") as f:
                f.write(template("DECISIONS.md").replace("<KEY>", str(child_key)))
        print(f"created child task {child_dir}")
    # step 2: point the parent row at it
    if row.get("task") == child_key:
        print(f"row {row_id} already points at {child_key}")
    else:
        cmd_set(task_dir, row_id, {"task": child_key})
    print(f"promoted {row_id} -> {child_key}")


def cmd_ack(task_dir, row_id):
    front, _ = read_task(task_dir)
    row = find_row(front, row_id)
    pr = row.get("pr")
    if not pr or pr == "none":
        die(f"row {row_id} has no PR to snapshot")
    try:
        live = gh_pr(pr)
    except RuntimeError as e:
        die(f"gh failed ({e}); keeping the previous snapshot")
    os.makedirs(os.path.join(task_dir, ".status"), exist_ok=True)
    path = snapshot_path(task_dir, row_id)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".snap-")
    with os.fdopen(fd, "w") as f:
        json.dump({"fetched_at": now(), "pr": live}, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    print(f"acked {row_id}: {path}")


def cmd_gate(task_dir, row_id, gate_name, verdict):
    if verdict not in ("done", "open"):
        die("gate wants done|open")
    with LockedTask(task_dir) as t:
        front, body = t.read()
        row = find_row(front, row_id)
        gates = norm_gates(row)
        hit = next((g for g in gates if g["name"] == gate_name), None)
        if hit is None:
            names = ", ".join(g["name"] for g in gates) or "none"
            die(f"row {row_id} has no gate {gate_name!r} (gates: {names})")
        hit["done"] = verdict == "done"
        row["gates"] = gates
        t.write(front, body)
    print(f"gate {gate_name!r} on {row_id}: {verdict}")


# --------------------------------------------------------------------- main

def main():
    args = sys.argv[1:]
    explicit_dir = None
    as_json = no_live = show_all = live = False
    rest = []
    i = 0
    while i < len(args):
        if args[i] == "--dir":
            if i + 1 >= len(args):
                die("--dir wants a path")
            explicit_dir, i = args[i + 1], i + 2
        elif args[i] == "--json":
            as_json, i = True, i + 1
        elif args[i] == "--no-live":
            no_live, i = True, i + 1
        elif args[i] == "--all":
            show_all, i = True, i + 1
        elif args[i] == "--live":
            live, i = True, i + 1
        else:
            rest.append(args[i])
            i += 1
    if not rest:
        die("usage: status.sh show|workers-in|add-row|set|set-root|promote|"
            "ack|gate ... (see the header of status.py)")
    cmd, args = rest[0], rest[1:]
    if show_all and cmd != "show":
        die("--all only applies to show")
    if cmd == "show" and show_all:
        if args:
            die("show takes no positional arguments")
        cmd_show_all(as_json, live)
        return
    if cmd == "workers-in":
        if len(args) != 1:
            die("workers-in needs exactly a worktree path")
        cmd_workers_in(args[0], as_json)
        return
    task_dir = find_task_dir(explicit_dir)
    if cmd == "show":
        if args:
            die("show takes no positional arguments")
        cmd_show(task_dir, as_json, no_live)
    elif cmd == "add-row":
        if not args:
            die("add-row needs an id")
        cmd_add_row(task_dir, args[0], parse_kv(args[1:]))
    elif cmd == "set":
        if not args:
            die("set needs an id")
        cmd_set(task_dir, args[0], parse_kv(args[1:]))
    elif cmd == "set-root":
        cmd_set_root(task_dir, parse_kv(args))
    elif cmd == "promote":
        if len(args) != 1:
            die("promote needs exactly an id")
        cmd_promote(task_dir, args[0])
    elif cmd == "ack":
        if len(args) != 1:
            die("ack needs exactly an id")
        cmd_ack(task_dir, args[0])
    elif cmd == "gate":
        if len(args) != 3:
            die("usage: gate <id> <name> done|open")
        cmd_gate(task_dir, args[0], args[1], args[2])
    else:
        die(f"unknown subcommand {cmd!r}")


if __name__ == "__main__":
    main()
