"""`POST /api/brains` of the local app: guards, validation, conflicts and a real creation in a temporary Work."""

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools/tasks-web"))

from tasksweb.server import TaskServer  # noqa: E402
from tasksweb.store import Store  # noqa: E402

LONG_NAME = "brain-" + "a" * 60


class NewBrainRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)  # last: the server is stopped first
        self.work = Path(self.temp.name).resolve() / "work"
        existing = self.work / "brain-initech"
        (existing / ".data").mkdir(parents=True)
        (existing / "projects").mkdir()
        (existing / "AGENTS.md").write_text("# Brain\n", encoding="utf-8")
        self.server = TaskServer(("127.0.0.1", 0), Store(existing), work=self.work)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.stop, thread)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def stop(self, thread: threading.Thread) -> None:
        self.server.shutdown()
        self.server.server_close()
        thread.join(timeout=2)

    def post(self, payload, token=True, origin=None, host=None, content_type="application/json", body=None):
        headers = {"Content-Type": content_type, "Origin": origin or self.base}
        if token:
            headers["X-Tasks-Token"] = self.server.token
        if host:
            headers["Host"] = host
        data = body if body is not None else json.dumps(payload).encode()
        request = Request(self.base + "/api/brains", data=data, method="POST", headers=headers)
        try:
            with urlopen(request, timeout=90) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            with error:
                return error.code, json.loads(error.read())

    def get_brains(self):
        with urlopen(Request(self.base + "/api/brains"), timeout=3) as response:
            return json.loads(response.read())

    def valid(self, **extra):
        return {"name": "brain-acme", "description": "Acme notes; never any employer content.", **extra}

    def assertRefusedAndNothingCreated(self, result, status):
        self.assertEqual(result[0], status, result)
        self.assertIn("error", result[1])
        self.assertEqual([p.name for p in self.work.iterdir()], ["brain-initech"])

    def test_the_write_rules_of_every_write_route_apply(self) -> None:
        self.assertRefusedAndNothingCreated(self.post(self.valid(), token=False), 403)
        self.assertRefusedAndNothingCreated(self.post(self.valid(), origin="http://evil.example"), 403)
        self.assertRefusedAndNothingCreated(self.post(self.valid(), host="evil.example"), 403)
        self.assertRefusedAndNothingCreated(self.post(self.valid(), content_type="text/plain"), 415)

    def test_a_bad_name_is_refused(self) -> None:
        for name in ("acme", "brain-", "brain-Acme", "brain-a b", "brain_acme", "../brain-acme", LONG_NAME, "", 5, None):
            self.assertRefusedAndNothingCreated(self.post({**self.valid(), "name": name}), 400)

    def test_a_bad_description_or_scope_or_key_is_refused(self) -> None:
        bad = [
            {"name": "brain-acme"},
            {"name": "brain-acme", "description": ""},
            {"name": "brain-acme", "description": "   "},
            {"name": "brain-acme", "description": "two\nlines"},
            {"name": "brain-acme", "description": "tab\there"},
            {"name": "brain-acme", "description": "x" * 301},
            {"name": "brain-acme", "description": 3},
            {"name": "brain-acme", "description": "ok", "scope": "a\nb"},
            {"name": "brain-acme", "description": "ok", "scope": "x" * 61},
            {"name": "brain-acme", "description": "ok", "scope": 4},
            {"name": "brain-acme", "description": "ok", "remote": "git@example.test:acme/*"},
            {"name": "brain-acme", "description": "ok", "email": "*@acme.test"},
        ]
        for payload in bad:
            self.assertRefusedAndNothingCreated(self.post(payload), 400)
        for body in (b"[]", b"not json", b'"brain-acme"'):
            self.assertRefusedAndNothingCreated(self.post(None, body=body), 400)

    def test_a_request_over_the_size_limit_is_refused(self) -> None:
        self.assertRefusedAndNothingCreated(self.post({**self.valid(), "scope": "x" * 3000}), 413)

    def test_an_existing_brain_or_file_is_a_conflict(self) -> None:
        status, data = self.post({**self.valid(), "name": "brain-initech"})
        self.assertEqual(status, 409, data)
        self.assertIn("error", data)
        (self.work / "brain-acme").write_text("a file", encoding="utf-8")
        self.assertEqual(self.post(self.valid())[0], 409)
        self.assertEqual((self.work / "brain-acme").read_text(encoding="utf-8"), "a file")

    def test_a_creation_already_running_is_a_conflict(self) -> None:
        from tasksweb import brains

        self.assertTrue(brains.BRAIN_LOCK.acquire(blocking=False))
        try:
            self.assertRefusedAndNothingCreated(self.post(self.valid()), 409)
        finally:
            brains.BRAIN_LOCK.release()

    def test_a_valid_request_creates_the_brain_with_its_repository_hooks_and_boundary(self) -> None:
        status, data = self.post(self.valid(scope="  Acme  "))
        self.assertEqual(status, 201, data)
        self.assertEqual(data, {"brain": {"name": "brain-acme", "label": "Acme", "scope": "Acme",
                                          "description": "Acme notes; never any employer content.", "default": False}})
        brain = self.work / "brain-acme"
        self.assertTrue((brain / ".git").is_dir())
        for hook in ("pre-commit", "commit-msg", "pre-push"):
            self.assertTrue((brain / ".git/hooks" / hook).is_file(), hook)
        self.assertEqual(subprocess.run(["git", "remote"], cwd=brain, capture_output=True, text=True).stdout, "")
        declared = json.loads((brain / ".data/brain.json").read_text(encoding="utf-8"))
        self.assertEqual((declared["scope"], declared["description"], declared["remote"], declared["email"]),
                         ("Acme", "Acme notes; never any employer content.", "", ""))
        listed = self.get_brains()
        self.assertEqual([b["name"] for b in listed["brains"]], ["brain-acme", "brain-initech"])
        self.assertEqual(self.post(self.valid())[0], 409)

    def test_a_creation_without_scope_leaves_it_empty(self) -> None:
        status, data = self.post({"name": "brain-globex", "description": "Globex notes."})
        self.assertEqual(status, 201, data)
        self.assertEqual(data["brain"]["scope"], "")
        self.assertTrue((self.work / "brain-globex/.git").is_dir())

    def test_a_value_starting_with_a_dash_stays_a_value(self) -> None:
        status, data = self.post({"name": "brain-globex", "description": "--no-git", "scope": "--remote=*"})
        self.assertEqual(status, 201, data)
        self.assertEqual((data["brain"]["description"], data["brain"]["scope"]), ("--no-git", "--remote=*"))
        self.assertTrue((self.work / "brain-globex/.git").is_dir())
        declared = json.loads((self.work / "brain-globex/.data/brain.json").read_text(encoding="utf-8"))
        self.assertEqual(declared["remote"], "")


if __name__ == "__main__":
    unittest.main()
