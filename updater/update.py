#!/usr/bin/env python3
"""포트폴리오 수치·문단 후보 자동 갱신 프로그램 (표준 라이브러리만, 결정적 실행).

사용: python update.py --input <입력 폴더> --out <출력 폴더>

- AI 호출 없음, 난수·현재시각 미사용 -> 같은 입력이면 출력이 바이트 단위로 동일.
- 입력 원문을 출력 폴더에 통째로 복사하지 않는다(후보 문장 일부만 인용).
- 경고에는 값 대신 id/위치만 적는다.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import sys

ABILITIES = ["자기조절력", "대인관계력", "자기동기력"]

# 규칙 기반 키워드 사전 (부분 문자열 일치)
KEYWORDS = {
    "자기조절력": ["루틴", "계획", "시간", "일정", "습관", "집중", "꾸준", "정리", "기록",
                "감정", "침착", "컨디션", "조절", "규칙", "지키", "성실", "부지런",
                "돌아보", "돌아 보", "복습", "수면", "일찍", "차분", "점검", "확인"],
    "대인관계력": ["경청", "친절", "도와", "도움", "협력", "소통", "공유", "피드백", "조언",
                "설명", "함께", "같이", "팀", "질문", "대화", "배려", "나눠", "나누",
                "동료", "응원", "격려"],
    "자기동기력": ["도전", "목표", "끈기", "노력", "포기", "성장", "배우", "배운", "학습",
                "공부", "끝까지", "완수", "의지", "스스로", "새로", "해결", "다시",
                "극복", "동기", "열심", "시도", "완성", "마무리"],
}

# 후보에서 제외할 민감 주제
SENSITIVE = ["학자금", "대출", "등록금", "가족", "부모", "아버지", "어머니", "엄마", "아빠",
             "형제", "아내", "남편", "아들", "딸", "할머니", "할아버지", "건강", "병원",
             "질병", "아프", "아파", "두통", "감기", "수술", "통증", "우울", "약국", "진단"]

NAME_PATTERNS = [re.compile(r"\(이름 가림\)"), re.compile(r"[가-힣A-Za-z]{1,10}님")]

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{12,}"),
    re.compile(r"(?i)api[_\- ]?key\s*[:=]"),
    re.compile(r"(?i)(password|passwd|secret|token)\s*[:=]"),
    re.compile(r"(비밀번호|패스워드|암호)\s*(은|는|:|=)"),
]

# 입력 단계에서 제외하는 칸 (동료 이름이 들어가는 칸)
EXCLUDED_ITEM = re.compile(r"^(동료\s*\d+\s*(에게 말한|가 말해 준|가 나눈)|감사일기)")
# 분류 대상에서 빼는 메타 항목
SKIP_ITEMS = {"호흡", "강점 행동"}

DATE_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s*$")
SECTION_RE = re.compile(r"^\[(아침|마무리)\]\s*$")
ITEM_RE = re.compile(r"^-\s+([^:]+?):\s*(.*)$")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n")


def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")


def load_json(path, required=True):
    if not os.path.exists(path):
        if required:
            raise SystemExit("입력 파일이 없습니다: " + os.path.basename(path))
        return None
    return json.loads(read_text(path))


def scan_secrets(basename, text, warnings):
    for n, line in enumerate(text.split("\n"), 1):
        for pat in SECRET_PATTERNS:
            if pat.search(line):
                warnings.append("SECRET 의심 패턴: 파일=%s 줄=%d (값은 기록하지 않음)" % (basename, n))
                break


def parse_rituals(files, warnings):
    """리추얼 txt -> {date: {"아침": [(item, value)], "마무리": [...]}} (동료 이름 칸 제외)."""
    days = {}
    for path in files:
        text = read_text(path)
        scan_secrets(os.path.basename(path), text, warnings)
        date = None
        section = None
        for line in text.split("\n"):
            m = DATE_RE.match(line)
            if m:
                date = m.group(1)
                section = None
                days[date] = {}  # 뒤 파일이 같은 날짜를 덮어씀
                continue
            if date is None:
                continue
            m = SECTION_RE.match(line)
            if m:
                section = m.group(1)
                days[date].setdefault(section, [])
                continue
            m = ITEM_RE.match(line)
            if m and section:
                item, value = m.group(1).strip(), m.group(2).strip()
                if EXCLUDED_ITEM.match(item):
                    continue
                days[date][section].append((item, value))
    return days


def classify(sentence):
    best, best_n = None, 0
    for ab in ABILITIES:
        n = sum(1 for k in KEYWORDS[ab] if k in sentence)
        if n > best_n:
            best, best_n = ab, n
    return best


def make_candidates(days, warnings):
    cands, stats = [], {"name": 0, "sensitive": 0, "unclassified": 0}
    for date in sorted(days):
        for section in ("아침", "마무리"):
            for item, value in days[date].get(section, []):
                if item in SKIP_ITEMS:
                    continue
                for sent in SENT_SPLIT.split(value):
                    sent = re.sub(r"\s+", " ", sent).strip()
                    if len(sent) < 8:
                        continue
                    h = hashlib.sha256(sent.encode("utf-8")).hexdigest()[:8]
                    cid = "%s_%s_%s" % (date, item.replace(" ", ""), h)
                    if any(p.search(sent) for p in NAME_PATTERNS):
                        stats["name"] += 1
                        warnings.append("이름 의심으로 제외: id=%s" % cid)
                        continue
                    if any(k in sent for k in SENSITIVE):
                        stats["sensitive"] += 1
                        warnings.append("민감 주제로 제외: id=%s" % cid)
                        continue
                    if any(p.search(sent) for p in SECRET_PATTERNS):
                        warnings.append("SECRET 의심으로 제외: id=%s" % cid)
                        continue
                    ab = classify(sent)
                    if ab is None:
                        stats["unclassified"] += 1
                        continue
                    cands.append({"id": cid, "ability": ab, "date": date, "section": section,
                                  "item": item, "text": sent})
    return cands, stats


def compute_metrics(days, attendance, submissions):
    src_r, src_a, src_s = "리추얼 기록", "내 출석 기록", "내 제출 현황"
    m = {}
    m["ritual_record_days"] = {"value": len(days), "unit": "일", "source": src_r}
    m["ritual_morning_count"] = {"value": sum(1 for d in days.values() if "아침" in d),
                                 "unit": "회", "source": src_r}
    m["ritual_wrapup_count"] = {"value": sum(1 for d in days.values() if "마무리" in d),
                                "unit": "회", "source": src_r}
    td = int(attendance["training_days"])
    pr = int(attendance["present"])
    ab = int(attendance.get("absent", td - pr))
    m["attendance_training_days"] = {"value": td, "unit": "일", "source": src_a}
    m["attendance_present"] = {"value": pr, "unit": "일", "source": src_a}
    m["attendance_absent"] = {"value": ab, "unit": "일", "source": src_a}
    m["attendance_rate"] = {"value": int(pr * 100 / td + 0.5) if td else 0, "unit": "%",
                            "source": src_a}
    notes = {"기준일": attendance.get("as_of", ""),
             "확정 전 일수": attendance.get("unconfirmed_days", 0)}
    m["attendance_note"] = {"value": notes, "unit": "", "source": src_a}
    subs = submissions["submissions"]
    per_task = {}
    for s in subs:
        per_task[s["task"]] = per_task.get(s["task"], 0) + 1
    m["submission_count"] = {"value": len(subs), "unit": "건", "source": src_s}
    m["submission_task_count"] = {"value": len(per_task), "unit": "개", "source": src_s}
    m["resubmission_count"] = {"value": sum(c - 1 for c in per_task.values()),
                               "unit": "건", "source": src_s}
    m["resubmitted_tasks"] = {"value": sorted(t for t, c in per_task.items() if c > 1),
                              "unit": "", "source": src_s}
    return m


def write(path, text):
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_candidates(cands, approved_ids, stats):
    L = ["# 능력별 문단 후보", "",
         "규칙 기반(키워드 사전)으로 분류한 후보입니다. 사용하려면 id를 `approved.json`에 넣으세요.",
         "표시: `[x]` 승인됨, `[ ]` 미승인(사이트 데이터에 반영되지 않음).", ""]
    L.append("- 후보 %d개 / 이름 의심 제외 %d / 민감 주제 제외 %d / 분류 안 됨 %d"
             % (len(cands), stats["name"], stats["sensitive"], stats["unclassified"]))
    L.append("")
    for ab in ABILITIES:
        group = [c for c in cands if c["ability"] == ab]
        L.append("## %s (%d)" % (ab, len(group)))
        L.append("")
        for c in group:
            mark = "x" if c["id"] in approved_ids else " "
            L.append("- [%s] `%s`" % (mark, c["id"]))
            L.append("  - 문장: %s" % c["text"])
            L.append("  - 근거: %s · [%s] %s (리추얼 기록)" % (c["date"], c["section"], c["item"]))
        L.append("")
    return "\n".join(L)


def load_approved(path):
    data = load_json(path, required=False)
    if data is None:
        return []
    items = data.get("approved", []) if isinstance(data, dict) else data
    return [(i["id"] if isinstance(i, dict) else i) for i in items]


UPDATER_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLISH_FILES = ["metrics.json", "site_data.json"]


def publish_refusal(input_dir, ritual_files):
    """합성 샘플이 실사이트로 나가지 않도록 --publish-to 거부 사유를 돌려준다(없으면 None)."""
    real_in = os.path.normcase(os.path.realpath(input_dir))
    if "sample_input" in real_in:
        return "입력 폴더 경로에 sample_input이 포함되어 있습니다."
    upd = os.path.normcase(os.path.realpath(UPDATER_DIR))
    if real_in == upd or real_in.startswith(upd + os.sep):
        return "입력 폴더가 updater/ 폴더 안에 있습니다(샘플·예시 입력으로 간주)."
    for path in ritual_files:
        first = read_text(path).split("\n", 1)[0]
        if "합성" in first:
            return "리추얼 파일 첫 줄에 '합성' 표기가 있습니다: " + os.path.basename(path)
    return None


def publish(out_dir, dest):
    os.makedirs(dest, exist_ok=True)
    report = []
    for name in PUBLISH_FILES:
        src, dst = os.path.join(out_dir, name), os.path.join(dest, name)
        if os.path.exists(dst):
            with open(src, "rb") as a, open(dst, "rb") as b:
                new, old = a.read(), b.read()
            if new == old:
                report.append((name, "변경 없음"))
                continue
            if new == old.replace(b"\r\n", b"\n"):
                # git autocrlf로 체크아웃된 CRLF 사본: 내용이 같으므로 건드리지 않음
                report.append((name, "변경 없음(줄바꿈 형식만 다름)"))
                continue
            state = "덮어씀"
        else:
            state = "새로 만듦"
        shutil.copyfile(src, dst)
        report.append((name, state))
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="포트폴리오 수치·후보 자동 갱신")
    ap.add_argument("--input", required=True, help="입력 폴더")
    ap.add_argument("--out", required=True, help="출력 폴더")
    ap.add_argument("--publish-to", default=None,
                    help="사이트 data 폴더(예: site/data). 지정하면 metrics.json·site_data.json만 복사")
    args = ap.parse_args(argv)

    warnings = []
    files = sorted(glob.glob(os.path.join(args.input, "ritual-history-*.txt")))
    if not files:
        raise SystemExit("리추얼 파일(ritual-history-*.txt)이 없습니다.")
    if args.publish_to:
        reason = publish_refusal(args.input, files)
        if reason:
            print("--publish-to 거부: " + reason, file=sys.stderr)
            return 2
    days = parse_rituals(files, warnings)

    att_path = os.path.join(args.input, "attendance.json")
    sub_path = os.path.join(args.input, "submissions.json")
    for p in (att_path, sub_path):
        if os.path.exists(p):
            scan_secrets(os.path.basename(p), read_text(p), warnings)
    attendance = load_json(att_path)
    submissions = load_json(sub_path)
    approved_ids = load_approved(os.path.join(args.input, "approved.json"))

    metrics = compute_metrics(days, attendance, submissions)
    for k, v in metrics.items():
        assert v.get("source"), "source 누락: " + k

    cands, stats = make_candidates(days, warnings)
    by_id = {c["id"]: c for c in cands}
    approved_set = set(approved_ids)
    for aid in sorted(approved_set):
        if aid not in by_id:
            warnings.append("승인 id가 후보에 없음(제외되었거나 입력이 바뀜): id=%s" % aid)

    site = {"metrics": metrics,
            "paragraphs": {ab: [] for ab in ABILITIES}}
    for c in cands:
        if c["id"] in approved_set:
            site["paragraphs"][c["ability"]].append(
                {"id": c["id"], "date": c["date"], "item": c["item"],
                 "text": c["text"], "source": "리추얼 기록"})

    os.makedirs(args.out, exist_ok=True)
    write(os.path.join(args.out, "metrics.json"), dump(metrics))
    write(os.path.join(args.out, "candidates.md"), render_candidates(cands, approved_set, stats))
    write(os.path.join(args.out, "site_data.json"), dump(site))
    wtxt = "\n".join(sorted(set(warnings))) + "\n" if warnings else "경고 없음\n"
    write(os.path.join(args.out, "warnings.txt"), wtxt)

    print("기록일 %d, 후보 %d, 승인 반영 %d, 경고 %d"
          % (len(days), len(cands), sum(len(v) for v in site["paragraphs"].values()),
             len(set(warnings))))
    if args.publish_to:
        n_approved = sum(len(v) for v in site["paragraphs"].values())
        print("publish 대상: %s" % args.publish_to)
        print("승인 항목 %d개 / 후보 %d개" % (n_approved, len(cands)))
        for name, state in publish(args.out, args.publish_to):
            print("  %s: %s" % (name, state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
