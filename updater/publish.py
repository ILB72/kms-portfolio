#!/usr/bin/env python3
"""새 기록 폴더를 넣고 한 번 실행하면 수치 재집계 → 사이트 data 교체 → 커밋·PR·병합(배포)까지 진행한다.

표준 라이브러리만 쓴다. git과 GitHub CLI(gh, 로그인 상태)가 필요하다.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

import update

REPO = os.path.dirname(update.UPDATER_DIR)
DATA_REL = ["site/data/" + n for n in update.PUBLISH_FILES]


class Stop(Exception):
    """더 진행하면 안 되는 상태. 메시지를 보여 주고 종료한다."""


def run(cmd, cwd=REPO):
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise Stop("명령 실패: %s\n%s" % (" ".join(cmd), (p.stderr or p.stdout).strip()))
    return p.stdout.strip()


def find_gh():
    found = shutil.which("gh")
    if found:
        return found
    fallback = os.path.join(os.environ.get("ProgramFiles", ""), "GitHub CLI", "gh.exe")
    if os.path.exists(fallback):
        return fallback
    raise Stop("GitHub CLI(gh)를 찾지 못했습니다. 설치 후 'gh auth login'을 하세요.")


def read_json(path):
    if not os.path.exists(path):
        return {}
    return update.load_json(path)


def describe_changes(old, new):
    """사이트에 반영될 차이를 사람이 읽을 줄 목록으로 돌려준다(없으면 빈 목록)."""
    lines = []
    om, nm = old.get("metrics", {}), new.get("metrics", {})
    for key in sorted(set(om) | set(nm)):
        a, b = om.get(key, {}).get("value"), nm.get(key, {}).get("value")
        if a != b:
            show = lambda v: "(없음)" if v is None else json.dumps(v, ensure_ascii=False)
            lines.append("수치 %s: %s → %s" % (key, show(a), show(b)))

    def texts(site):
        return {p["id"]: p["text"] for items in site.get("paragraphs", {}).values() for p in items}

    op, np_ = texts(old), texts(new)
    for pid in sorted(set(np_) - set(op)):
        lines.append("승인 문장 추가: %s" % np_[pid])
    for pid in sorted(set(op) - set(np_)):
        lines.append("승인 문장 삭제(주의): %s" % op[pid])
    for pid in sorted(set(op) & set(np_)):
        if op[pid] != np_[pid]:
            lines.append("승인 문장 변경: %s → %s" % (op[pid], np_[pid]))
    return lines


def check_repo():
    if run(["git", "branch", "--show-current"]) != "master":
        raise Stop("master 브랜치에서 실행하세요: git checkout master")
    if run(["git", "status", "--porcelain", "--untracked-files=no"]):
        raise Stop("커밋하지 않은 변경이 있습니다. 먼저 정리하세요(git status).")
    run(["git", "fetch", "--quiet", "origin"])
    run(["git", "merge", "--ff-only", "--quiet", "origin/master"])
    if run(["git", "rev-parse", "HEAD"]) != run(["git", "rev-parse", "origin/master"]):
        raise Stop("push하지 않은 커밋이 master에 있습니다.")
    if run(["git", "diff", "--name-only", "origin/main", "origin/master"]):
        raise Stop("master에 아직 배포하지 않은 변경이 있습니다. 함께 배포되지 않도록 먼저 처리하세요.")


def deploy(out_dir, branch, title, gh):
    run(["git", "checkout", "--quiet", "-b", branch])
    try:
        update.publish(out_dir, os.path.join(REPO, "site", "data"))
        run(["git", "add", "--"] + DATA_REL)
        run(["git", "commit", "--quiet", "-m", title])
    except Exception:
        run(["git", "checkout", "--quiet", "HEAD", "--"] + DATA_REL)
        run(["git", "checkout", "--quiet", "master"])
        run(["git", "branch", "--quiet", "-D", branch])
        raise
    run(["git", "push", "--quiet", "-u", "origin", branch])
    for base, head in (("master", branch), ("main", "master")):
        url = run([gh, "pr", "create", "--base", base, "--head", head,
                   "--title", title, "--body", "updater/publish.py 자동 생성"]).split()[-1]
        run([gh, "pr", "merge", url, "--merge"])
        print("병합: %s → %s (%s)" % (head, base, url))
    run(["git", "checkout", "--quiet", "master"])
    run(["git", "pull", "--quiet", "--ff-only"])


def main(argv=None):
    ap = argparse.ArgumentParser(description="한 번 실행으로 사이트 갱신·배포")
    ap.add_argument("--input", required=True, help="실제 기록 폴더")
    ap.add_argument("--out", default=None, help="출력 폴더(기본: 임시 폴더)")
    ap.add_argument("--dry-run", action="store_true", help="바뀌는 내용만 보여 주고 끝냄")
    ap.add_argument("--yes", action="store_true", help="확인 질문 없이 배포")
    args = ap.parse_args(argv)
    try:
        gh = None
        if not args.dry_run:
            gh = find_gh()
            check_repo()
        out = args.out or tempfile.mkdtemp(prefix="portfolio_out_")
        files = sorted(update.glob.glob(os.path.join(args.input, "ritual-history-*.txt")))
        reason = update.publish_refusal(args.input, files)
        if reason:
            raise Stop("배포 거부: " + reason)
        if update.main(["--input", args.input, "--out", out]) != 0:
            raise Stop("갱신 계산에 실패했습니다.")
        print("후보 문장·경고 확인: %s" % out)

        new = read_json(os.path.join(out, "site_data.json"))
        old = read_json(os.path.join(REPO, "site", "data", "site_data.json"))
        changes = describe_changes(old, new)
        if not changes:
            print("변경 없음: 배포하지 않습니다.")
            return 0
        print("\n사이트에 반영될 변경 %d건" % len(changes))
        for line in changes:
            print("  - " + line)
        if args.dry_run:
            print("\n--dry-run: 파일을 바꾸지 않았습니다.")
            return 0
        if not args.yes and input("\n공개 사이트에 배포할까요? [y/N] ").strip().lower() != "y":
            print("취소했습니다. 파일을 바꾸지 않았습니다.")
            return 0

        as_of = new["metrics"]["attendance_note"]["value"]["기준일"]
        with open(os.path.join(out, "site_data.json"), "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()[:8]
        deploy(out, "data/update-%s-%s" % (as_of, digest),
               "data: 기록 갱신(기준일 %s)" % as_of, gh)
        print("\n완료. 1~2분 뒤 https://kms-portfolio-site.vercel.app/ 에 반영됩니다.")
        return 0
    except Stop as e:
        print("중단: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
