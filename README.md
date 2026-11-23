# Reference Audit

Paste a reference list and see which references exist.

Each entry is looked up in [Crossref](https://www.crossref.org/) and [OpenAlex](https://openalex.org/). The page then labels it:

- **Found**: a record with this title exists, and its first author and year agree with the reference.
- **Check**: a record exists, but the year, the first author, the DOI or part of the title differs.
- **Retracted**: the work exists and has been retracted.
- **No record**: neither index holds a matching record. Both indexes miss many books, reports and works not written in English, so these need a check by hand.

Use it at <https://fanzemeng31-arch.github.io/reference-audit/>. Lists of up to 15 references are free, and no account is needed. Longer lists on the web page need a £5 pass that lasts 30 days. The page accepts a reference list in any citation style, or the contents of a BibTeX file. The terminal script below is free for lists of any length.

## From the terminal

The same check is a single Python file with no dependencies (Python 3.9 or later).

```
curl -O https://raw.githubusercontent.com/fanzemeng31-arch/reference-audit/main/skills/reference-audit/scripts/refaudit.py
python3 refaudit.py references.bib
```

The input is a `.txt`, `.md` or `.bib` file, or `-` to read from standard input. The output is a Markdown report.

- `--json` prints the results as JSON.
- `--fail-on miss,retracted` ends with exit status 2 when any reference carries one of the named labels (`miss`, `retracted`, `warn`, `error`).

## In a build

To stop a build when the bibliography holds a retracted work or a reference without a record, add a step such as this one to a GitHub Actions workflow:

```yaml
- name: Check references
  run: |
    curl -sO https://raw.githubusercontent.com/fanzemeng31-arch/reference-audit/main/skills/reference-audit/scripts/refaudit.py
    python3 refaudit.py references.bib --fail-on miss,retracted
```

## As a skill for AI coding agents

The folder `skills/reference-audit` is an agent skill for Claude Code and other agents that read `SKILL.md` files. Install it with:

```
npx skills add fanzemeng31-arch/reference-audit
```

Then ask the agent to check the references of a draft.

## Guides

- [How to check whether a reference written by an AI tool is real](https://fanzemeng31-arch.github.io/reference-audit/guides/check-ai-references.html)
- [How to find out whether a paper you cite has been retracted](https://fanzemeng31-arch.github.io/reference-audit/guides/retracted-papers.html)

## Privacy

The web page is a single HTML file with no server behind it. The browser sends each reference straight to the two public indexes. Nothing is stored. The script does the same from your own computer and contacts no other host.

## Limits

The check covers whether a work exists and whether its details agree with the reference. It does not read the work, so it cannot say whether the work supports the sentence that cites it.

## Run the page locally

```
python3 -m http.server 8000
```

Then open <http://localhost:8000/>.

## Licence

MIT. See [LICENSE](LICENSE).
