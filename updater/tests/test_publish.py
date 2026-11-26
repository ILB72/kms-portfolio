import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import publish  # noqa: E402

SAMPLE = os.path.join(os.path.dirname(HERE), "sample_input")


def quiet(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        code = publish.main(argv)
    return code, buf.getvalue()


class PublishTest(unittest.TestCase):
    def test_describe_changes(self):
        old = {"metrics": {"a": {"value": 1}}, "paragraphs": {"x": [{"id": "1", "text": "옛"}]}}
        new = {"metrics": {"a": {"value": 2}}, "paragraphs": {"x": [{"id": "2", "text": "새"}]}}
        lines = publish.describe_changes(old, new)
        self.assertEqual(len(lines), 3)
        self.assertEqual(publish.describe_changes(new, new), [])

    def test_sample_input_refused_before_deploy(self):
        with mock.patch.object(publish, "deploy") as dep:
            code, text = quiet(["--input", SAMPLE, "--dry-run"])
        self.assertEqual(code, 2)
        self.assertIn("배포 거부", text)
        dep.assert_not_called()

    def test_answer_no_does_not_deploy(self):
        with tempfile.TemporaryDirectory() as out, \
                mock.patch.object(publish, "find_gh", return_value="gh"), \
                mock.patch.object(publish, "check_repo"), \
                mock.patch.object(publish, "deploy") as dep, \
                mock.patch.object(publish.update, "publish_refusal", return_value=None), \
                mock.patch.object(publish, "describe_changes", return_value=["x"]), \
                mock.patch("builtins.input", return_value=""):
            code, _ = quiet(["--input", SAMPLE, "--out", out])
        self.assertEqual(code, 0)
        dep.assert_not_called()

    def test_dirty_repo_stops(self):
        answers = {"branch": "master", "status": " M site/index.html"}
        with mock.patch.object(publish, "run", side_effect=lambda c, **k: answers[c[1]]):
            with self.assertRaises(publish.Stop):
                publish.check_repo()


if __name__ == "__main__":
    unittest.main()
