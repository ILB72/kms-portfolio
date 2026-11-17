import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import update  # noqa: E402

SAMPLE = os.path.join(ROOT, "sample_input")
OUT_FILES = ["metrics.json", "candidates.md", "site_data.json", "warnings.txt"]


def run(inp, out):
    with open(os.devnull, "w") as dn:
        old = sys.stdout
        sys.stdout = dn
        try:
            update.main(["--input", inp, "--out", out])
        finally:
            sys.stdout = old


def run_publish(inp, out, dest):
    buf_out, buf_err = io.StringIO(), io.StringIO()
    old_o, old_e = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = buf_out, buf_err
    try:
        code = update.main(["--input", inp, "--out", out, "--publish-to", dest])
    finally:
        sys.stdout, sys.stderr = old_o, old_e
    return code, buf_out.getvalue(), buf_err.getvalue()


def real_like_input(tmp):
    """샘플을 updater/ 밖으로 복사하고 '합성' 표기를 지워 실데이터처럼 만든 입력."""
    inp = os.path.join(tmp, "real_in")
    shutil.copytree(SAMPLE, inp)
    p = os.path.join(inp, "ritual-history-2026-11-16.txt")
    with open(p, encoding="utf-8") as f:
        lines = f.read().split("\n")
    lines[0] = "# 리추얼 기록"
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    return inp


def read(p):
    with open(p, "rb") as f:
        return f.read()


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_deterministic(self):
        a, b = os.path.join(self.tmp, "a"), os.path.join(self.tmp, "b")
        run(SAMPLE, a)
        run(SAMPLE, b)
        for f in OUT_FILES:
            self.assertEqual(read(os.path.join(a, f)), read(os.path.join(b, f)), f)

    def test_names_excluded(self):
        out = os.path.join(self.tmp, "o")
        run(SAMPLE, out)
        for f in ["candidates.md", "site_data.json", "metrics.json"]:
            text = read(os.path.join(out, f)).decode("utf-8")
            self.assertNotIn("님", text, f)
            self.assertNotIn("이름 가림", text, f)
            self.assertNotIn("예시동료", text, f)
            self.assertNotIn("가족 모임", text, f)  # 민감 키워드 문장 제외
            self.assertNotIn("동료 1가", text, f)  # 동료 칸 내용 제외
        warn = read(os.path.join(out, "warnings.txt")).decode("utf-8")
        self.assertIn("이름 의심으로 제외: id=", warn)
        self.assertNotIn("예시동료", warn)  # 경고에는 값이 없어야 함

    def test_unapproved_not_in_site(self):
        out = os.path.join(self.tmp, "o")
        run(SAMPLE, out)
        site = json.loads(read(os.path.join(out, "site_data.json")))
        ids = [p["id"] for ps in site["paragraphs"].values() for p in ps]
        with open(os.path.join(SAMPLE, "approved.json"), encoding="utf-8") as f:
            approved = json.load(f)["approved"]
        self.assertEqual(sorted(ids), sorted(approved))
        md = read(os.path.join(out, "candidates.md")).decode("utf-8")
        self.assertGreater(md.count("- [ ] `"), 0)  # 미승인 후보는 md에만

    def test_no_approved_file_means_empty_site(self):
        inp = os.path.join(self.tmp, "in")
        shutil.copytree(SAMPLE, inp)
        os.remove(os.path.join(inp, "approved.json"))
        out = os.path.join(self.tmp, "o")
        run(inp, out)
        site = json.loads(read(os.path.join(out, "site_data.json")))
        self.assertTrue(all(len(v) == 0 for v in site["paragraphs"].values()))

    def test_metrics_have_source(self):
        out = os.path.join(self.tmp, "o")
        run(SAMPLE, out)
        m = json.loads(read(os.path.join(out, "metrics.json")))
        allowed = {"내 출석 기록", "리추얼 기록", "내 제출 현황"}
        for k, v in m.items():
            self.assertIn(v.get("source"), allowed, k)
        self.assertEqual(m["ritual_record_days"]["value"], 5)
        self.assertEqual(m["ritual_wrapup_count"]["value"], 4)
        self.assertEqual(m["attendance_rate"]["value"], 95)
        self.assertEqual(m["submission_count"]["value"], 18)
        self.assertEqual(m["submission_task_count"]["value"], 11)

    def test_secret_warning(self):
        inp = os.path.join(self.tmp, "in")
        shutil.copytree(SAMPLE, inp)
        p = os.path.join(inp, "ritual-history-2026-11-16.txt")
        with open(p, "a", encoding="utf-8") as f:
            f.write("- 오늘의 첫 행동: password = hunter2example 를 목표로 기록\n")
        out = os.path.join(self.tmp, "o")
        run(inp, out)
        warn = read(os.path.join(out, "warnings.txt")).decode("utf-8")
        self.assertIn("SECRET", warn)
        self.assertNotIn("hunter2", warn)
        self.assertNotIn("hunter2", read(os.path.join(out, "candidates.md")).decode("utf-8"))


    def test_publish_copies_two_files(self):
        inp = real_like_input(self.tmp)
        out, dest = os.path.join(self.tmp, "o"), os.path.join(self.tmp, "site_data_dir")
        code, so, _ = run_publish(inp, out, dest)
        self.assertEqual(code, 0)
        self.assertEqual(sorted(os.listdir(dest)), ["metrics.json", "site_data.json"])
        for f in ("metrics.json", "site_data.json"):
            self.assertEqual(read(os.path.join(dest, f)), read(os.path.join(out, f)))
        self.assertIn("승인 항목 3개 / 후보 32개", so)
        self.assertIn("새로 만듦", so)
        code, so, _ = run_publish(inp, out, dest)
        self.assertEqual(code, 0)
        self.assertEqual(so.count("변경 없음"), 2)

    def test_publish_refused_for_sample_input(self):
        dest = os.path.join(self.tmp, "site_data_dir")
        code, _, err = run_publish(SAMPLE, os.path.join(self.tmp, "o"), dest)
        self.assertNotEqual(code, 0)
        self.assertIn("거부", err)
        self.assertFalse(os.path.exists(dest))

    def test_publish_refused_for_synthetic_first_line(self):
        inp = os.path.join(self.tmp, "copied_in")
        shutil.copytree(SAMPLE, inp)  # updater/ 밖이지만 첫 줄에 '합성'
        dest = os.path.join(self.tmp, "site_data_dir")
        code, _, err = run_publish(inp, os.path.join(self.tmp, "o"), dest)
        self.assertNotEqual(code, 0)
        self.assertIn("합성", err)
        self.assertFalse(os.path.exists(dest))

    def test_no_publish_means_no_copy(self):
        inp = real_like_input(self.tmp)
        out = os.path.join(self.tmp, "o")
        run(inp, out)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["o", "real_in"])


if __name__ == "__main__":
    unittest.main()
