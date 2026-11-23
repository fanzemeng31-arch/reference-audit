---
name: reference-audit
description: Check whether the references in a document exist and are cited correctly. Use when the user asks to check, verify or audit references, a bibliography or citations, or when a draft with a reference list was written with AI help and the references have not been checked.
---

# Reference audit

This skill looks up each reference in Crossref and OpenAlex and reports whether a matching work exists and whether the details agree. It needs Python 3.9 or later and an internet connection. It uses only the standard library.

## How to run it

Put the references in a file, one per line or one per paragraph. A `.txt`, `.md` or `.bib` file works. Then run:

```
python3 scripts/refaudit.py references.txt
```

Use `-` in place of the file name to read from standard input. The default output is a Markdown report: a summary line with the counts, then one block per reference. Add `--json` to get a JSON list instead.

To make a script or CI job fail when the list has problems, add `--fail-on miss,retracted,warn`. The exit status is 2 if any reference carries one of the named labels, and 0 otherwise.

A list of 50 references takes about one to two minutes, because the script keeps to three requests a second.

## What the labels mean

- **Found**: a record matches the title, and the first author, year and DOI agree with the reference.
- **Check**: a record exists, but something differs. The problems line says what: a different title, a different first author, a different year, or a DOI that belongs to another work. Read the record before deciding which side is wrong.
- **Retracted**: the matching record has been retracted by the publisher.
- **No record**: neither index holds a matching work. For a book, report, thesis or a work in a non-Latin script, this is common and proves little. For a journal article, treat the reference as doubtful until it is found by hand.
- **Lookup failed**: a service did not answer. Run the check again later.

## What the check cannot do

It confirms that a work exists and that its details agree with the reference. It does not read the work. It does not confirm that the work says what the sentence citing it claims.

## Rules for the agent

1. Report the results to the user as they are. Do not soften a label, drop a reference from the list, or say a reference is fine when the report says Check or No record.
2. Never repair a reference by guessing a detail. If a correction is needed, copy it from the matched record in the report, and tell the user which detail was changed and that it came from that record. If there is no matched record, leave the reference as it is and say so.
