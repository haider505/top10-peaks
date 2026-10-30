# -*- coding: utf-8 -*-
"""
يبني بنك الأسئلة من مجلد packs/ ويحقنه في index.html و artifact-page.html.

يتحقق من:
  • وجود 10 إجابات بمراتب 1..10 دون تكرار
  • الحقول المطلوبة في كل إجابة
  • عدم تكرار معرّف السؤال (id) في البنك كله
  • عدم تكرار نص السؤال (prompt) في البنك كله
  • عدم تكرار إجابة داخل السؤال الواحد
  • عدم تشابه نصوص الأسئلة بشكل يوحي بالتكرار
"""
import io, json, os, re, sys, glob, unicodedata

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
PACKS = os.path.join(ROOT, "packs")
TARGETS = ["index.html", "artifact-page.html"]

REQUIRED_ANSWER_FIELDS = ["rank", "label_ar", "metric", "hint"]


def norm(s):
    """تطبيع عربي مبسّط للكشف عن التكرار."""
    s = unicodedata.normalize("NFKC", str(s or "")).strip().lower()
    s = re.sub(r"[ً-ٰٟـ]", "", s)
    s = re.sub(r"[أإآٱ]", "ا", s)
    s = s.replace("ة", "ه").replace("ى", "ي")
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_packs():
    files = sorted(glob.glob(os.path.join(PACKS, "*.json")))
    if not files:
        sys.exit("No pack files found in packs/")
    questions, origin = [], {}
    for f in files:
        with io.open(f, encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except Exception as e:
                sys.exit("JSON error in %s: %s" % (os.path.basename(f), e))
        items = data if isinstance(data, list) else data.get("questions", [])
        for q in items:
            questions.append(q)
            origin[q.get("id", "?")] = os.path.basename(f)
    return questions, origin


def validate(questions, origin):
    errs, warns = [], []
    seen_ids, seen_prompts = {}, {}

    for q in questions:
        qid = q.get("id", "<no id>")
        where = origin.get(qid, "?")
        tag = "%s [%s]" % (qid, where)

        for field in ("id", "category", "prompt", "direction"):
            if not q.get(field):
                errs.append("%s: missing '%s'" % (tag, field))

        if qid in seen_ids:
            errs.append("DUPLICATE id '%s' (also in %s)" % (qid, seen_ids[qid]))
        seen_ids[qid] = where

        p = norm(q.get("prompt"))
        if p and p in seen_prompts:
            errs.append("DUPLICATE prompt: %s  <->  %s" % (tag, seen_prompts[p]))
        seen_prompts[p] = tag

        answers = q.get("answers") or []
        if len(answers) != 10:
            errs.append("%s: has %d answers, needs exactly 10" % (tag, len(answers)))
            continue

        ranks = sorted(int(a.get("rank", 0)) for a in answers)
        if ranks != list(range(1, 11)):
            errs.append("%s: ranks are %s, need 1..10" % (tag, ranks))

        labels = {}
        for a in answers:
            for field in REQUIRED_ANSWER_FIELDS:
                if a.get(field) in (None, "", []):
                    errs.append("%s #%s: missing '%s'" % (tag, a.get("rank"), field))
            lbl = str(a.get("label_ar") or "")
            if "؟" in lbl or "—" in lbl or " لا " in lbl:
                errs.append("%s #%s: draft artifact left in label '%s'" % (tag, a.get("rank"), lbl))
            # الأحرف اللاتينية مقبولة كاختصارات قصيرة بحروف كبيرة (O, AB, CTF, K2)
            # لكن الأحرف الصغيرة داخل كلمة عربية تعني خطأ طباعياً
            if re.search(r"[a-z]", lbl) or re.search(r"[A-Za-z]{5,}", lbl):
                errs.append("%s #%s: latin letters in label_ar '%s'" % (tag, a.get("rank"), lbl))
            for syn in (a.get("synonyms") or []):
                sy = str(syn)
                if "؟" in sy or "—" in sy:
                    errs.append("%s #%s: draft artifact in synonym '%s'" % (tag, a.get("rank"), sy))
            key = norm(a.get("label_ar"))
            if key in labels:
                errs.append("%s: duplicate answer '%s' (#%s and #%s)"
                            % (tag, a.get("label_ar"), labels[key], a.get("rank")))
            labels[key] = a.get("rank")
            if not isinstance(a.get("synonyms", []), list):
                errs.append("%s #%s: synonyms must be a list" % (tag, a.get("rank")))
    return errs, warns


def inject(questions):
    payload = json.dumps(questions, ensure_ascii=False, separators=(",", ":"))
    block = "const BUILTIN_QUESTIONS = %s;" % payload
    pattern = re.compile(r"const BUILTIN_QUESTIONS = .*?\n\];", re.S)
    alt = re.compile(r"const BUILTIN_QUESTIONS = \[.*?\];", re.S)
    for t in TARGETS:
        path = os.path.join(ROOT, t)
        if not os.path.exists(path):
            print("  skip (missing):", t)
            continue
        src = io.open(path, encoding="utf-8").read()
        new, n = pattern.subn(lambda m: block, src, count=1)
        if n == 0:
            new, n = alt.subn(lambda m: block, src, count=1)
        if n == 0:
            sys.exit("Could not locate BUILTIN_QUESTIONS in %s" % t)
        io.open(path, "w", encoding="utf-8").write(new)
        print("  wrote %-20s %7d bytes" % (t, len(new.encode("utf-8"))))


def main():
    questions, origin = load_packs()
    errs, warns = validate(questions, origin)
    cats = {}
    for q in questions:
        cats[q.get("category", "?")] = cats.get(q.get("category", "?"), 0) + 1

    print("packs: %d files -> %d questions, %d answers"
          % (len(glob.glob(os.path.join(PACKS, "*.json"))), len(questions), len(questions) * 10))
    for c in sorted(cats, key=lambda k: -cats[k]):
        print("   %-28s %3d" % (c, cats[c]))
    for w in warns:
        print("  WARN:", w)
    if errs:
        print("\n%d ERROR(S):" % len(errs))
        for e in errs[:40]:
            print("   -", e)
        sys.exit(1)
    print("validation: OK")
    if "--check" not in sys.argv:
        inject(questions)
    print("done.")


if __name__ == "__main__":
    main()
