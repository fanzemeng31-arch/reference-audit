# Reference Audit

Paste a reference list and see which references exist.

Each entry is looked up in [Crossref](https://www.crossref.org/) and [OpenAlex](https://openalex.org/). The page then labels it:

- **Found**: a record with this title exists, and its first author and year agree with the reference.
- **Check**: a record exists, but the year, the first author, the DOI or part of the title differs.
- **Retracted**: the work exists and has been retracted.
- **No record**: neither index holds a matching record. Both indexes miss many books, reports and works not written in English, so these need a check by hand.

Use it at <https://fanzemeng31-arch.github.io/reference-audit/>.

## Privacy

The page is a single HTML file with no server behind it. The browser sends each reference straight to the two public indexes. Nothing is stored.

## Limits

The check covers whether a work exists and whether its details agree with the reference. It does not read the work, so it cannot say whether the work supports the sentence that cites it.

## Run it locally

```
python3 -m http.server 8000
```

Then open <http://localhost:8000/>.
