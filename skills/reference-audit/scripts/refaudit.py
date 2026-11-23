#!/usr/bin/env python3
"""Check a reference list against Crossref and OpenAlex.

Usage: refaudit.py FILE [--json] [--fail-on miss,retracted,warn]
FILE is a .txt, .md or .bib file, or - for standard input.
Only api.crossref.org and api.openalex.org are contacted.
"""
import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

UA = "reference-audit-cli/0.1 (+https://github.com/fanzemeng31-arch/reference-audit)"
TIMEOUT = 25
MIN_GAP = 1.0 / 3.0  # at most 3 requests a second per host
HOSTS = ("api.crossref.org", "api.openalex.org")
FAIL = object()  # lookup did not complete

LABEL = {"ok": "Found", "warn": "Check", "retracted": "Retracted",
         "miss": "No record", "error": "Lookup failed"}

# ---------- text handling ----------
STOP = set("a an the of in on and for to with by from at as is are".split())


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    s = re.sub(r"[\u0300-\u036f]", "", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def split_refs(text):
    text = text.replace("\r", "")
    if re.search(r"\n\s*\n", text.strip()):
        parts = [re.sub(r"\s*\n\s*", " ", p) for p in re.split(r"\n\s*\n", text)]
    else:
        parts = text.split("\n")
    parts = [re.sub(r"^\s*(\[\d+\]|\(\d+\)|\d+[.)])\s*", "", s).strip() for s in parts]
    return [s for s in parts if len(s) >= 15]


def find_doi(s):
    m = re.search(r"\b10\.\d{4,9}/[^\s\"<>]+", s, re.I)
    if not m:
        return None
    d = re.sub(r"[.,;]+$", "", m.group(0))
    while d.endswith(")") and len(d.split("(")) < len(d.split(")")):
        d = d[:-1]
    return re.sub(r"[.,;]+$", "", d)


def ref_years(ref):
    cleaned = re.sub(r"10\.\d{4,9}/\S+", " ", ref)
    return [int(m.group(1)) for m in re.finditer(r"(?<!\d)(1[5-9]\d\d|20\d\d)(?!\d)", cleaned)]


def guess_title(ref):
    cleaned = re.sub(r"https?://\S+|10\.\d{4,9}/\S+", " ", ref)
    segs = re.split(r"(?<=[.?!])\s+|['\"\u2018\u2019\u201c\u201d]", cleaned)
    segs = [s.strip() for s in segs if s is not None]
    segs = [s for s in segs if len(s.split()) >= 3]
    if not segs:
        return ref[:200]
    best = segs[0]
    for s in segs[1:]:
        if len(s) > len(best):
            best = s
    return best


def title_score(ref, title):
    r, t = norm(ref), norm(title)
    if not t:
        return 0
    tt = t.split(" ")
    if (" " + t + " ") in (" " + r + " "):
        return 1 if len(tt) >= 3 else 0.8
    rs = set(r.split(" "))
    content = [w for w in tt if w not in STOP]
    if not content:
        return 0
    cov = sum(1 for w in content if w in rs) / len(content)
    hit = sum(1 for i in range(len(tt) - 1) if (tt[i] + " " + tt[i + 1]) in r)
    big = hit / (len(tt) - 1) if len(tt) > 1 else cov
    return 0.5 * cov + 0.5 * big


# ---------- BibTeX ----------
def _clean_tex(s):
    s = re.sub(r"\\[`'^\"~=.]\{?(\w)\}?", r"\1", s)
    s = re.sub(r"\\&", "&", s)
    s = re.sub(r"\\[a-zA-Z]+\s*", "", s)
    s = s.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", s).strip()


def _read_braced(text, i):
    """text[i] is '{'. Return (content, index after the closing brace)."""
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
        j += 1
    return text[i + 1:], len(text)


def parse_bibtex(text):
    refs = []
    for m in re.finditer(r"@(\w+)\s*\{", text):
        kind = m.group(1).lower()
        if kind in ("comment", "string", "preamble"):
            continue
        body, _ = _read_braced(text, m.end() - 1)
        fields = {}
        pos = body.find(",") + 1  # skip the citation key
        while pos < len(body):
            fm = re.compile(r"\s*,?\s*([A-Za-z\-]+)\s*=\s*").match(body, pos)
            if not fm:
                break
            pos = fm.end()
            if pos >= len(body):
                break
            if body[pos] == "{":
                val, pos = _read_braced(body, pos)
            elif body[pos] == '"':
                end = pos + 1
                while end < len(body) and body[end] != '"':
                    end += 2 if body[end] == "\\" else 1
                val, pos = body[pos + 1:end], end + 1
            else:
                vm = re.compile(r"[^,\s}]+").match(body, pos)
                val, pos = (vm.group(0), vm.end()) if vm else ("", pos + 1)
            fields[fm.group(1).lower()] = _clean_tex(val)
        refs.append(bib_to_string(fields))
    return [r for r in refs if r]


def bib_to_string(f):
    author = f.get("author") or f.get("editor") or ""
    year = f.get("year") or (re.match(r"\d{4}", f.get("date", "")) or [""])[0]
    venue = f.get("journal") or f.get("journaltitle") or f.get("booktitle") or f.get("publisher") or ""
    parts = []
    head = author
    if year:
        head = (head + " (" + year + ")").strip()
    if head:
        parts.append(head)
    if f.get("title"):
        parts.append("'" + f["title"] + "'")
    if venue:
        parts.append(venue)
    s = ", ".join(parts)
    if f.get("doi"):
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", f["doi"], flags=re.I)
        s += ". doi:" + doi
    return s.strip()


def read_references(text, name):
    if re.search(r"@\w+\s*\{", text) and (name.lower().endswith(".bib") or re.search(r"^\s*@\w+\s*\{", text, re.M)):
        refs = parse_bibtex(text)
        if refs:
            return refs
    return split_refs(text)


# ---------- lookups ----------
_last = {}


def _throttle(host):
    wait = _last.get(host, 0) + MIN_GAP - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last[host] = time.monotonic()


def get_json(url, tries=3):
    """Return parsed JSON, None for 404, FAIL when the lookup did not complete."""
    host = urllib.parse.urlparse(url).hostname
    if host not in HOSTS:
        raise ValueError("refusing to contact " + str(host))
    for i in range(tries):
        _throttle(host)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 429 or e.code >= 500:
                time.sleep(1.5 * (i + 1))
                continue
            return FAIL
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.8 * (i + 1))
    return FAIL


CR = "https://api.crossref.org/works"
SEL = "DOI,title,subtitle,author,issued,published-print,published-online,container-title,type,updated-by"


def _yr(d):
    try:
        return d["date-parts"][0][0]
    except (KeyError, IndexError, TypeError):
        return None


def cr_rec(it):
    title = (it.get("title") or [""])[0] or ""
    sub = (it.get("subtitle") or [""])[0] or ""
    years = []
    for k in ("issued", "published-print", "published-online"):
        y = _yr(it.get(k))
        if y and y not in years:
            years.append(y)
    retracted = any(isinstance(u, dict) and u.get("type") == "retraction" for u in (it.get("updated-by") or []))
    retracted = retracted or title.strip().upper().startswith("RETRACTED")
    return {"src": "Crossref", "doi": it.get("DOI"), "title": title,
            "full": (title + " " + sub) if sub else title, "years": years,
            "authors": [a.get("family") or a.get("name") for a in (it.get("author") or [])
                        if a.get("family") or a.get("name")],
            "journal": (it.get("container-title") or [""])[0] or "", "retracted": retracted}


def oa_rec(w):
    doi = w.get("doi")
    names = []
    for a in w.get("authorships") or []:
        n = ((a.get("author") or {}).get("display_name") or "").strip().split()
        if n:
            names.append(n[-1])
    src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
    return {"src": "OpenAlex", "doi": re.sub(r"^https?://doi\.org/", "", doi, flags=re.I) if doi else None,
            "title": w.get("title") or "", "full": w.get("title") or "",
            "years": [w["publication_year"]] if w.get("publication_year") else [],
            "authors": names, "journal": src, "retracted": bool(w.get("is_retracted"))}


def cr_by_doi(doi):
    j = get_json(CR + "/" + urllib.parse.quote(doi, safe=""))
    if j is None:
        return None
    if j is FAIL or not isinstance(j, dict) or "message" not in j:
        return FAIL
    return cr_rec(j["message"])


def cr_search(ref):
    q = re.sub(r"https?://\S+", " ", ref)[:400]
    j = get_json(CR + "?query.bibliographic=" + urllib.parse.quote(q, safe="") + "&rows=5&select=" + SEL)
    if j is None or j is FAIL or not isinstance(j, dict) or "message" not in j:
        return FAIL
    return [cr_rec(x) for x in j["message"].get("items", [])]


def oa_search(ref):
    j = get_json("https://api.openalex.org/works?search=" + urllib.parse.quote(guess_title(ref)[:200], safe="")
                 + "&per-page=5&select=id,doi,title,publication_year,authorships,primary_location,is_retracted", 1)
    if j is None or j is FAIL or not isinstance(j, dict) or "results" not in j:
        return FAIL
    return [oa_rec(x) for x in j["results"]]


# ---------- judging one reference ----------
def weigh(ref, rec):
    r = " " + norm(ref) + " "

    def has(a):
        return (" " + norm(a) + " ") in r

    ys = ref_years(ref)
    year = "none"
    if ys and rec["years"]:
        if any(y in ys for y in rec["years"]):
            year = "match"
        elif any(abs(x - y) == 1 for y in rec["years"] for x in ys):
            year = "near"
        else:
            year = "mismatch"
    first = has(rec["authors"][0]) if rec["authors"] else None
    score = max(title_score(ref, rec["title"]), title_score(ref, rec["full"]))
    rank = score + (0.05 if first else 0) + (0.05 if year == "match" else 0)
    return {"rec": rec, "score": score, "year": year, "first": first, "rank": rank}


def pick(ref, recs):
    ws = sorted((weigh(ref, x) for x in recs), key=lambda w: -w["rank"])
    return ws[0] if ws else None


PUBLISHER_RE = re.compile(r"\b(press|publishers?|publishing|books|routledge|palgrave|springer|wiley|sage|verlag)\b", re.I)
BOOKISH_RE = re.compile(r"\b(press|publishers?|publishing|books|routledge|palgrave|springer|wiley|sage|verlag|elsevier|working paper|report|thesis|dissertation)\b", re.I)
NON_LATIN_RE = re.compile("[Ѐ-ӿ֐-ۿ฀-๿぀-ヿ一-鿿가-힯]")


def miss_text(ref):
    if NON_LATIN_RE.search(ref):
        return ("No matching record in Crossref or OpenAlex. This reference is not written in Latin script, and the two "
                "indexes hold few such works, so the missing record tells you little. Check it in the index for its own "
                "language, such as CNKI for Chinese journals.")
    if BOOKISH_RE.search(ref):
        return ("No matching record in Crossref or OpenAlex. This looks like a book, report or thesis, which the two "
                "indexes often miss. Check it in a library catalogue.")
    return ("No matching record in Crossref or OpenAlex. If this is a journal article, treat it as doubtful until you "
            "have found it yourself.")


def audit(ref):
    out = {"ref": ref, "verdict": "miss", "rec": None, "issues": [], "notes": []}
    doi = find_doi(ref)
    best, failed, doi_wrong = None, False, False
    if doi:
        d = cr_by_doi(doi)
        if d is None:
            out["notes"].append("The DOI in this reference is not registered with Crossref.")
        elif d is FAIL:
            failed = True
        else:
            w = weigh(ref, d)
            if w["score"] >= 0.6:
                best = w
            else:
                doi_wrong = True
                out["issues"].append("The DOI in this reference belongs to a different work: “" + d["title"] + "”.")
    if not best:
        c = cr_search(ref)
        if c is FAIL:
            failed = True
        else:
            best = pick(ref, c)
    if not best or best["score"] < 0.85 or best["first"] is False or best["year"] == "mismatch":
        o = oa_search(ref)
        if o is not FAIL and o:
            b2 = pick(ref, o)
            if b2 and (not best or b2["rank"] > best["rank"]):
                best = b2
    if (best and best["score"] >= 0.85 and best["first"] is False and best["rec"]["journal"]
            and PUBLISHER_RE.search(ref)):
        out["notes"].append("The closest record is an item in " + best["rec"]["journal"]
                            + " that carries the same title. It may be a review of this book.")
        return out
    if not best or best["score"] < 0.6:
        out["verdict"] = "error" if failed else ("warn" if out["issues"] else "miss")
        if failed:
            out["notes"].append("The lookup did not complete. Run the check again in a minute.")
        return out
    rec = out["rec"] = best["rec"]
    if best["score"] < 0.85:
        out["issues"].append("The closest record has a different title: “" + rec["title"] + "”.")
    else:
        if best["first"] is False:
            out["issues"].append("The record gives " + rec["authors"][0]
                                 + " as first author, a name that does not appear in your reference.")
        if best["year"] == "mismatch":
            out["issues"].append("The record gives the year " + " or ".join(str(y) for y in rec["years"])
                                 + "; your reference gives " + ", ".join(str(y) for y in dict.fromkeys(ref_years(ref))) + ".")
        if best["year"] == "near":
            out["notes"].append("The record gives the year " + " or ".join(str(y) for y in rec["years"])
                                + ", one year away from yours. Online and print years often differ by one.")
        if doi and not doi_wrong and rec["doi"] and doi.lower() != rec["doi"].lower():
            out["issues"].append("The DOI in your reference differs from the DOI of the record.")
        if rec["journal"] and norm(rec["journal"]) not in norm(ref):
            out["notes"].append("The record names the journal or publisher series as " + rec["journal"] + ".")
        if rec["retracted"]:
            out["verdict"] = "retracted"
            out["issues"].insert(0, "This work has been retracted.")
            return out
    out["verdict"] = "warn" if out["issues"] else "ok"
    return out


# ---------- output ----------
def record_line(rec):
    au = ", ".join(rec["authors"][:3]) + (" et al." if len(rec["authors"]) > 3 else "")
    yr = min(rec["years"]) if rec["years"] else "no year"
    s = "Record in " + rec["src"] + ": " + au + " (" + str(yr) + ") " + rec["title"]
    if rec["journal"]:
        s += ". " + rec["journal"]
    if rec["doi"]:
        s += ". DOI: https://doi.org/" + urllib.parse.quote(rec["doi"], safe="/:()+;,@=~*'!$&")
    return s


def markdown(results):
    counts = {}
    for o in results:
        counts[o["verdict"]] = counts.get(o["verdict"], 0) + 1
    order = ["ok", "warn", "retracted", "miss", "error"]
    summary = ", ".join(str(counts[v]) + " " + LABEL[v] for v in order if counts.get(v))
    lines = ["# Reference audit", "", "Checked " + str(len(results)) + " references: " + (summary or "none") + ".", ""]
    for i, o in enumerate(results, 1):
        lines += ["## " + str(i) + ". " + LABEL[o["verdict"]], "", "Reference: " + o["ref"], ""]
        problems = list(o["issues"])
        if o["verdict"] == "miss":
            problems.append(miss_text(o["ref"]))
        if problems:
            lines.append("Problems:")
            lines += ["- " + p for p in problems]
            lines.append("")
        if o["notes"]:
            lines.append("Notes:")
            lines += ["- " + n for n in o["notes"]]
            lines.append("")
        if o["rec"]:
            lines += [record_line(o["rec"]), ""]
    return "\n".join(lines).rstrip() + "\n"


def to_json(results):
    rows = []
    for i, o in enumerate(results, 1):
        r = o["rec"]
        problems = list(o["issues"]) + ([miss_text(o["ref"])] if o["verdict"] == "miss" else [])
        rows.append({"no": i, "label": LABEL[o["verdict"]], "verdict": o["verdict"], "reference": o["ref"],
                     "problems": problems, "notes": o["notes"],
                     "record": None if not r else {"source": r["src"], "title": r["title"], "authors": r["authors"],
                                                   "years": r["years"], "journal": r["journal"], "doi": r["doi"]}})
    return json.dumps(rows, ensure_ascii=False, indent=2)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check a reference list against Crossref and OpenAlex.")
    ap.add_argument("file", help=".txt, .md or .bib file, or - for standard input")
    ap.add_argument("--json", action="store_true", help="print a JSON list instead of Markdown")
    ap.add_argument("--fail-on", default="", help="comma list of labels (miss, retracted, warn, error) that give exit status 2")
    a = ap.parse_args(argv)
    if a.file == "-":
        text, name = sys.stdin.read(), "-"
    else:
        with open(a.file, encoding="utf-8-sig") as fh:
            text, name = fh.read(), a.file
    refs = read_references(text, name)
    if not refs:
        sys.stderr.write("No references found in the input.\n")
        return 1
    results = []
    for n, ref in enumerate(refs, 1):
        sys.stderr.write("Checking " + str(n) + " of " + str(len(refs)) + "\r")
        try:
            results.append(audit(ref))
        except Exception:
            results.append({"ref": ref, "verdict": "error", "rec": None, "issues": [],
                            "notes": ["The lookup did not complete. Run the check again in a minute."]})
    sys.stderr.write("\n")
    sys.stdout.write((to_json(results) if a.json else markdown(results)) + ("\n" if a.json else ""))
    wanted = {x.strip().lower() for x in a.fail_on.split(",") if x.strip()}
    alias = {"found": "ok", "check": "warn", "no record": "miss"}
    wanted = {alias.get(x, x) for x in wanted}
    return 2 if any(o["verdict"] in wanted for o in results) else 0


if __name__ == "__main__":
    sys.exit(main())
