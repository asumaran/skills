#!/usr/bin/env python3
"""Fixture tests for skills/task/status.py.

Everything runs against temp dirs (WORK_DIR, LINEAGE_DIR) and a fake gh
(GH_BIN_PATH); nothing touches ~/.claude. Run: python3 tests/status_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS = os.path.join(REPO, "skills", "task", "status.sh")

FAKE_GH = """#!/usr/bin/env bash
# fake gh: `gh pr view <url> --json <fields>` -> $GH_FIXTURES/<basename>.json
url="$3"
f="$GH_FIXTURES/$(basename "$url").json"
if [ ! -f "$f" ]; then echo "GraphQL: Could not resolve PR" >&2; exit 1; fi
cat "$f"
"""

FAKE_HERDR = """#!/usr/bin/env bash
# fake herdr: `herdr api snapshot` -> $HERDR_SNAPSHOT_FILE
if [ "$1 $2" != "api snapshot" ]; then echo "unexpected: $*" >&2; exit 1; fi
if [ ! -f "$HERDR_SNAPSHOT_FILE" ]; then echo "no herdr" >&2; exit 1; fi
cat "$HERDR_SNAPSHOT_FILE"
"""


def pr_json(state="OPEN", draft=False, decision="", head="abc123",
            fail=0, ok=1, comments=0):
    rollup = [{"conclusion": "SUCCESS", "status": "COMPLETED"}] * ok + \
             [{"conclusion": "FAILURE", "status": "COMPLETED"}] * fail
    return {"state": state, "isDraft": draft, "reviewDecision": decision,
            "baseRefName": "main", "headRefOid": head, "mergedAt": None,
            "url": "x", "statusCheckRollup": rollup,
            "comments": [{"id": i} for i in range(comments)]}


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="status-test-")
        self.work = os.path.join(self.tmp, "work")
        self.lineage = os.path.join(self.tmp, "lineage")
        self.fixtures = os.path.join(self.tmp, "gh-fixtures")
        for d in (self.work, self.lineage, self.fixtures):
            os.makedirs(d)
        gh = os.path.join(self.tmp, "gh")
        with open(gh, "w") as f:
            f.write(FAKE_GH)
        os.chmod(gh, 0o755)
        herdr = os.path.join(self.tmp, "herdr")
        with open(herdr, "w") as f:
            f.write(FAKE_HERDR)
        os.chmod(herdr, 0o755)
        self.snapshot_file = os.path.join(self.tmp, "herdr-snapshot.json")
        self.env = {**os.environ, "WORK_DIR": self.work,
                    "LINEAGE_DIR": self.lineage, "GH_BIN_PATH": gh,
                    "GH_FIXTURES": self.fixtures, "HERDR_BIN_PATH": herdr,
                    "HERDR_SNAPSHOT_FILE": self.snapshot_file}
        self.env.pop("HERDR_PANE_ID", None)

    def set_snapshot(self, agents):
        with open(self.snapshot_file, "w") as f:
            json.dump({"result": {"snapshot": {"agents": agents,
                                               "workspaces": []}}}, f)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_st(self, *args, cwd=None, check=True):
        r = subprocess.run([STATUS, *args], capture_output=True, text=True,
                           env=self.env, cwd=cwd or self.tmp)
        if check and r.returncode != 0:
            self.fail(f"status.sh {' '.join(args)} failed: {r.stderr}")
        return r

    def make_task(self, key="ESHOP-1"):
        d = os.path.join(self.work, key)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "TASK.md"), "w") as f:
            f.write(f"""---
key: {key}
title: A test task
link: none
parent: none
home: work
stack: none
plan: none
coordinator: none
aliases: []
authority: {{mode: task, grants: [commit, push]}}
deliverables: []
---

## Goal

Body prose that must survive every write.
""")
        return d

    def fixture_pr(self, name, **kw):
        with open(os.path.join(self.fixtures, f"{name}.json"), "w") as f:
            json.dump(pr_json(**kw), f)
        return f"https://github.com/o/r/pull/{name}"

    def show(self, d, *extra):
        r = self.run_st("show", "--json", "--dir", d, *extra)
        return json.loads(r.stdout)

    # ------------------------------------------------------------ writes

    def test_add_row_set_and_preservation(self):
        d = self.make_task()
        self.run_st("add-row", "F", "repo=/r", "branch=feat/x", "base=origin/main",
                    "--dir", d)
        self.run_st("set", "F", 'depends_on=[{"id":"B","until":"merged"}]',
                    "pr=https://github.com/o/r/pull/9", "--dir", d)
        self.run_st("set-root", "plan=/abs/plan.md", "--dir", d)
        data = self.show(d, "--no-live")
        row = data["rows"][0]["row"]
        self.assertEqual(row["branch"], "feat/x")
        self.assertEqual(row["depends_on"], [{"id": "B", "until": "merged"}])
        self.assertEqual(data["plan"], "/abs/plan.md")
        text = open(os.path.join(d, "TASK.md")).read()
        self.assertIn("Body prose that must survive every write.", text)
        self.assertIn("authority: {mode: task, grants: [commit, push]}", text)
        # add-row is idempotent: updates, never duplicates
        self.run_st("add-row", "F", "branch=feat/y", "--dir", d)
        data = self.show(d, "--no-live")
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0]["row"]["branch"], "feat/y")
        self.assertEqual(data["rows"][0]["row"]["depends_on"],
                         [{"id": "B", "until": "merged"}])

    def test_set_rejects_bad_phase_and_unknown_row(self):
        d = self.make_task()
        self.run_st("add-row", "F", "--dir", d)
        r = self.run_st("set", "F", "phase=bogus", "--dir", d, check=False)
        self.assertNotEqual(r.returncode, 0)
        r = self.run_st("set", "Z", "phase=merged", "--dir", d, check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no deliverable", r.stderr)

    def test_symlink_survives_write(self):
        d = self.make_task("repo-task")
        docs = os.path.join(self.tmp, "repo", "docs")
        os.makedirs(docs)
        real = os.path.join(docs, "TASK.md")
        os.replace(os.path.join(d, "TASK.md"), real)
        os.symlink(real, os.path.join(d, "TASK.md"))
        self.run_st("add-row", "A", "--dir", d)
        self.assertTrue(os.path.islink(os.path.join(d, "TASK.md")))
        self.assertIn("- id: A", open(real).read())

    # ------------------------------------------------------------- show

    def test_phases_and_next_action(self):
        d = self.make_task()
        self.run_st("add-row", "A", "phase=planned", "--dir", d)
        self.run_st("add-row", "B", "phase=launching", "--dir", d)
        merged = self.fixture_pr("10", state="MERGED")
        self.run_st("add-row", "C", "phase=in-review", f"pr={merged}", "--dir", d)
        draft = self.fixture_pr("11", state="OPEN", draft=True)
        self.run_st("add-row", "D", "phase=implementing", f"pr={draft}", "--dir", d)
        red = self.fixture_pr("12", state="OPEN", fail=2)
        self.run_st("add-row", "E", "phase=in-review", f"pr={red}", "--dir", d)
        data = self.show(d)
        by_id = {r["row"]["id"]: r for r in data["rows"]}
        self.assertEqual(by_id["A"]["next"], "launch: /task go A")
        self.assertIn("re-run /task go B", by_id["B"]["next"])
        self.assertEqual(by_id["C"]["phase"], "merged")
        self.assertIn("/task close C", by_id["C"]["next"])
        self.assertEqual(by_id["D"]["phase"], "pr-draft")
        self.assertEqual(by_id["E"]["phase"], "in-review")
        self.assertIn("round: /task go E", by_id["E"]["next"])
        self.assertIn("2 checks failing", by_id["E"]["next"])

    def test_missing_pr_falls_back_to_snapshot(self):
        d = self.make_task()
        url = self.fixture_pr("20", state="OPEN")
        self.run_st("add-row", "A", "phase=in-review", f"pr={url}", "--dir", d)
        self.run_st("ack", "A", "--dir", d)
        os.remove(os.path.join(self.fixtures, "20.json"))  # the PR "disappears"
        data = self.show(d)
        info = data["rows"][0]
        self.assertTrue(info["live_error"])
        self.assertEqual(info["live"]["state"], "OPEN")  # from the snapshot
        self.assertEqual(info["phase"], "in-review")  # row phase, live unusable

    def test_depends_on_merged_blocks_and_stacked_does_not(self):
        d = self.make_task()
        self.run_st("add-row", "A", "branch=feat/a", "phase=implementing", "--dir", d)
        self.run_st("add-row", "B", 'depends_on=[{"id":"A","until":"merged"}]',
                    "--dir", d)
        self.run_st("add-row", "C", 'depends_on=[{"id":"A","until":"stacked"}]',
                    "--dir", d)
        data = self.show(d, "--no-live")
        by_id = {r["row"]["id"]: r for r in data["rows"]}
        self.assertIn("wait:", by_id["B"]["next"])
        self.assertEqual(by_id["C"]["next"], "launch: /task go C")
        self.assertIn("stacked on feat/a", by_id["C"]["deps"][0]["desc"])
        self.run_st("set", "A", "phase=merged", "--dir", d)
        data = self.show(d, "--no-live")
        by_id = {r["row"]["id"]: r for r in data["rows"]}
        self.assertEqual(by_id["B"]["next"], "launch: /task go B")

    def test_gates_and_report_and_lineage(self):
        d = self.make_task()
        self.run_st("add-row", "A",
                    'gates=[{"name":"CORS deployed","done":false}]', "--dir", d)
        data = self.show(d, "--no-live")
        self.assertIn("gate: CORS deployed", data["rows"][0]["next"])
        self.run_st("gate", "A", "CORS deployed", "done", "--dir", d)
        data = self.show(d, "--no-live")
        self.assertEqual(data["rows"][0]["next"], "launch: /task go A")
        r = self.run_st("gate", "A", "nope", "done", "--dir", d, check=False)
        self.assertNotEqual(r.returncode, 0)
        # a worker blocked-on-user wins over everything else
        self.run_st("set", "A", "phase=implementing", 'workers=["w-a"]', "--dir", d)
        with open(os.path.join(self.lineage, "w-a.json"), "w") as f:
            json.dump({"state": "blocked-on-user", "summary": "which env?"}, f)
        data = self.show(d, "--no-live")
        self.assertIn("answer w-a", data["rows"][0]["next"])
        # report missing is fine; a finished worker points at the report
        with open(os.path.join(self.lineage, "w-a.json"), "w") as f:
            json.dump({"state": "finished", "summary": "done"}, f)
        data = self.show(d, "--no-live")
        self.assertIn("read report", data["rows"][0]["next"])

    def test_plan_sha_staleness(self):
        d = self.make_task()
        plan = os.path.join(d, "plan.md")
        with open(plan, "w") as f:
            f.write("the plan v2\n")
        self.run_st("set-root", f"plan={plan}", "--dir", d)
        self.run_st("add-row", "A", "phase=implementing", "--dir", d)
        os.makedirs(os.path.join(d, "reports"))
        with open(os.path.join(d, "reports", "A.md"), "w") as f:
            f.write("---\ndeliverable: A\nplan_sha256: 0000beef\n"
                    "phase: implementing\nsummary: ok\n---\n\nbody\n")
        data = self.show(d, "--no-live")
        self.assertTrue(data["rows"][0]["plan_stale"])
        self.assertTrue(any("older plan.md" in c for c in data["consistency"]))

    def test_events_vs_snapshot_and_ack(self):
        d = self.make_task()
        url = self.fixture_pr("30", comments=1)
        self.run_st("add-row", "A", "phase=in-review", f"pr={url}", "--dir", d)
        self.run_st("ack", "A", "--dir", d)
        data = self.show(d)
        self.assertEqual(data["rows"][0]["events"], [])
        self.fixture_pr("30", comments=3, head="def456")
        data = self.show(d)
        self.assertIn("2 new comments", data["rows"][0]["events"])
        self.assertIn("new commits", data["rows"][0]["events"])
        self.assertIn("round: /task go A", data["rows"][0]["next"])
        self.run_st("ack", "A", "--dir", d)
        data = self.show(d)
        self.assertEqual(data["rows"][0]["events"], [])

    # ------------------------------------------------------- detection

    def test_detect_by_cwd_and_branch(self):
        d = self.make_task("ESHOP-7")
        r = self.run_st("show", "--json", "--no-live", cwd=d)
        self.assertEqual(json.loads(r.stdout)["key"], "ESHOP-7")
        # by branch of a git worktree named in a row
        wt = os.path.join(self.tmp, "wt")
        subprocess.run(["git", "init", "-q", "-b", "feat/seven", wt], check=True)
        subprocess.run(["git", "-C", wt, "commit", "--allow-empty", "-q",
                        "-m", "x"], check=True,
                       env={**self.env, "GIT_AUTHOR_NAME": "t",
                            "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                            "GIT_COMMITTER_EMAIL": "t@t"})
        self.run_st("add-row", "A", "branch=feat/seven", "--dir", d)
        r = self.run_st("show", "--json", "--no-live", cwd=wt)
        self.assertEqual(json.loads(r.stdout)["key"], "ESHOP-7")
        # nothing matches: a clear error
        r = self.run_st("show", cwd=self.tmp, check=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no task found", r.stderr)

    def test_detect_by_coordinator(self):
        d = self.make_task("ESHOP-8")
        self.run_st("set-root", "coordinator=coord-x", "--dir", d)
        self.set_snapshot([{"pane_id": "w1:p1", "name": "coord-x",
                            "cwd": self.tmp}])
        env = {**self.env, "HERDR_PANE_ID": "w1:p1"}
        r = subprocess.run([STATUS, "show", "--json", "--no-live"],
                           capture_output=True, text=True, env=env,
                           cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["key"], "ESHOP-8")
        # an unnamed agent, or no herdr at all, still fails clearly
        self.set_snapshot([{"pane_id": "w1:p1", "name": None,
                            "cwd": self.tmp}])
        r = subprocess.run([STATUS, "show"], capture_output=True, text=True,
                           env=env, cwd=self.tmp)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no task found", r.stderr)

    # -------------------------------------------------- red CI vs wait

    def test_red_ci_and_comments_not_hidden_behind_wait(self):
        d = self.make_task()
        dep = self.fixture_pr("40", state="OPEN")
        red = self.fixture_pr("41", fail=2, comments=2)
        self.run_st("add-row", "F", "phase=in-review", f"pr={red}",
                    f'depends_on=[{{"pr":"{dep}","until":"merged"}}]',
                    "--dir", d)
        # ack with a clean PR, then the checks go red and comments arrive
        self.fixture_pr("41", fail=0, comments=0)
        self.run_st("ack", "F", "--dir", d)
        self.fixture_pr("41", fail=2, comments=2)
        data = self.show(d)
        nxt = data["rows"][0]["next"]
        self.assertIn("CI red (2)", nxt)
        self.assertIn("2 new comments", nxt)
        self.assertIn("then wait:", nxt)
        # without urgent signals the wait stands alone
        self.fixture_pr("41", fail=0, comments=0)
        data = self.show(d)
        self.assertTrue(data["rows"][0]["next"].startswith("wait:"))

    # ------------------------------------------------------ show --all

    def all_tasks(self, *extra):
        r = self.run_st("show", "--all", "--json", *extra)
        return {t["key"]: t for t in json.loads(r.stdout)["tasks"]}

    def test_show_all_summarizes_and_ranks(self):
        a = self.make_task("A-TASK")
        red = self.fixture_pr("50", fail=1)
        self.run_st("add-row", "X", "phase=merged", "--dir", a)
        self.run_st("add-row", "Y", "phase=in-review", f"pr={red}", "--dir", a)
        b = self.make_task("B-TASK")
        self.run_st("set-root", "coordinator=coord-b", "--dir", b)
        with open(os.path.join(self.lineage, "coord-b.json"), "w") as f:
            json.dump({"state": "running", "summary": ""}, f)
        self.run_st("add-row", "L", "phase=planned", "--dir", b)
        self.run_st("add-row", "W", "phase=implementing",
                    'depends_on=[{"id":"L","until":"merged"}]', "--dir", b)
        tasks = self.all_tasks("--live")
        self.assertEqual(set(tasks), {"A-TASK", "B-TASK"})
        self.assertEqual(tasks["A-TASK"]["phases"],
                         {"merged": 1, "in-review": 1})
        # red CI outranks the merged row
        self.assertEqual(tasks["A-TASK"]["urgent"]["id"], "Y")
        self.assertIn("1 checks failing", tasks["A-TASK"]["urgent"]["next"])
        self.assertIsNone(tasks["A-TASK"]["coordinator_state"])
        self.assertEqual(tasks["B-TASK"]["coordinator"], "coord-b")
        self.assertEqual(tasks["B-TASK"]["coordinator_state"], "running")
        # a launchable row outranks a waiting one
        self.assertEqual(tasks["B-TASK"]["urgent"]["id"], "L")

    def test_show_all_local_ranks_by_snapshot(self):
        d = self.make_task("C-TASK")
        red = self.fixture_pr("60", fail=3)
        self.run_st("add-row", "P", "phase=planned", "--dir", d)
        self.run_st("add-row", "R", "phase=in-review", f"pr={red}", "--dir", d)
        self.run_st("ack", "R", "--dir", d)
        os.remove(os.path.join(self.fixtures, "60.json"))
        tasks = self.all_tasks()  # no --live: must not touch gh at all
        self.assertEqual(tasks["C-TASK"]["urgent"]["id"], "R")

    # ------------------------------------------------------ workers-in

    def test_workers_in(self):
        wt = os.path.join(self.tmp, "wt-adopt")
        os.makedirs(wt)
        with open(os.path.join(self.lineage, "old-worker.json"), "w") as f:
            json.dump({"state": "finished", "summary": "done",
                       "agent": {"worktree": wt},
                       "task": {"ref": "LEG-1#A"}}, f)
        self.set_snapshot([
            {"pane_id": "w2:p1", "name": "old-worker", "cwd": wt},
            {"pane_id": "w2:p2", "name": None, "cwd": wt},
            {"pane_id": "w3:p1", "name": "other", "cwd": self.tmp},
        ])
        r = self.run_st("workers-in", wt, "--json")
        data = json.loads(r.stdout)
        self.assertEqual(data["workers"], ["old-worker"])
        self.assertEqual([l["name"] for l in data["lineage"]], ["old-worker"])
        self.assertEqual([h["pane_id"] for h in data["herdr"]],
                         ["w2:p1", "w2:p2"])
        self.assertEqual([h["pane_id"] for h in data["unrecorded"]],
                         ["w2:p2"])
        # an empty worktree reports nobody and exits 0
        empty = os.path.join(self.tmp, "wt-empty")
        os.makedirs(empty)
        r = self.run_st("workers-in", empty)
        self.assertIn("nobody found", r.stdout)

    # -------------------------------------------------------- promote

    def test_promote_idempotent_and_resumable(self):
        d = self.make_task("ESHOP-9")
        self.run_st("add-row", "F", "--dir", d)
        self.run_st("promote", "F", "--dir", d)
        child = os.path.join(self.work, "ESHOP-9-F")
        self.assertTrue(os.path.isfile(os.path.join(child, "TASK.md")))
        self.assertTrue(os.path.isfile(os.path.join(child, "DECISIONS.md")))
        data = self.show(d, "--no-live")
        self.assertEqual(data["rows"][0]["row"]["task"], "ESHOP-9-F")
        before = open(os.path.join(child, "TASK.md")).read()
        self.run_st("promote", "F", "--dir", d)  # re-run changes nothing
        self.assertEqual(before, open(os.path.join(child, "TASK.md")).read())
        # interrupted promote: child exists, parent pointer missing
        self.run_st("set", "F", "task=none", "--dir", d)
        data = self.show(d, "--no-live")
        self.assertTrue(any("finish its promote" in c for c in data["consistency"]))
        self.run_st("promote", "F", "--dir", d)
        data = self.show(d, "--no-live")
        self.assertEqual(data["rows"][0]["row"]["task"], "ESHOP-9-F")
        self.assertEqual(data["consistency"], [])
        # the parent row aggregates the child's least-advanced deliverable
        self.run_st("add-row", "X", "phase=merged", "--dir", child)
        self.run_st("add-row", "Y", "phase=implementing", "--dir", child)
        data = self.show(d, "--no-live")
        self.assertEqual(data["rows"][0]["phase"], "implementing")

    def test_promote_uses_child_ticket_key(self):
        d = self.make_task("ESHOP-9")
        self.run_st("add-row", "G", "child=ESHOP-2900", "--dir", d)
        self.run_st("promote", "G", "--dir", d)
        self.assertTrue(os.path.isdir(os.path.join(self.work, "ESHOP-2900")))
        data = self.show(d, "--no-live")
        self.assertEqual(data["rows"][0]["row"]["task"], "ESHOP-2900")

    # ---------------------------------------------------- consistency

    def test_consistency_findings(self):
        d = self.make_task()
        self.run_st("add-row", "A", "worktree=/nope/gone", 'workers=["w-x"]',
                    "phase=implementing", "--dir", d)
        data = self.show(d, "--no-live")
        self.assertTrue(any("is gone" in c for c in data["consistency"]))
        self.assertTrue(any("no lineage record" in c for c in data["consistency"]))
        # a lineage record claiming this task but absent from every row
        with open(os.path.join(self.lineage, "w-stray.json"), "w") as f:
            json.dump({"state": "running", "summary": "",
                       "task": {"ref": "ESHOP-1#B"}}, f)
        data = self.show(d, "--no-live")
        self.assertTrue(any("w-stray" in c for c in data["consistency"]))

    def test_consistency_ignores_coordinator_records(self):
        d = self.make_task()
        self.run_st("add-row", "A", 'workers=["w-a"]', "phase=implementing",
                    "--dir", d)
        with open(os.path.join(self.lineage, "w-a.json"), "w") as f:
            json.dump({"state": "running", "summary": "",
                       "task": {"ref": "ESHOP-1#A"}}, f)
        # the named coordinator, and any task-level record (bare key, no #id),
        # are not deliverable workers: neither may be flagged
        self.run_st("set-root", "coordinator=coord-x", "--dir", d)
        with open(os.path.join(self.lineage, "coord-x.json"), "w") as f:
            json.dump({"state": "running", "summary": "",
                       "task": {"ref": "ESHOP-1#A"}}, f)
        with open(os.path.join(self.lineage, "coord-anon.json"), "w") as f:
            json.dump({"state": "running", "summary": "",
                       "task": {"ref": "ESHOP-1"}}, f)
        data = self.show(d, "--no-live")
        self.assertFalse(any("coord-x" in c for c in data["consistency"]),
                         data["consistency"])
        self.assertFalse(any("coord-anon" in c for c in data["consistency"]),
                         data["consistency"])
        # a stray worker record (KEY#id) is still flagged
        with open(os.path.join(self.lineage, "w-stray.json"), "w") as f:
            json.dump({"state": "running", "summary": "",
                       "task": {"ref": "ESHOP-1#B"}}, f)
        data = self.show(d, "--no-live")
        self.assertTrue(any("w-stray" in c for c in data["consistency"]))

    def test_merged_next_action_is_not_close(self):
        d = self.make_task()
        self.run_st("add-row", "A", "phase=merged", "--dir", d)
        data = self.show(d, "--no-live")
        nxt = data["rows"][0]["next"]
        self.assertNotIn("close: /task close", nxt)
        self.assertIn("merged", nxt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
