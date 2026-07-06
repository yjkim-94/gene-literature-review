# Paywalled full text — exception path

Referenced from `SKILL.md` Phase 2 / Notes. Read this **only** when a specific paper's paywalled full text is genuinely needed; the default (abstract + PMC OA full text) is enough for almost every gene summary.

Use **only legal, free OA paths** — WAF bypass (insane-search, etc.) fails on the publisher's Cloudflare challenge and isn't needed anyway. Branch on the paper record's `pmcid`:

**Branch A — `pmcid` exists (already collected in Phase 2): efetch from PMC directly.**
No need to go through Unpaywall. A paper in PMC has a settled location.
```bash
curl -s "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=<PMC_number>&rettype=xml"
# <body> contains full INTRODUCTION/RESULTS/DISCUSSION sections
```

**Branch B — no `pmcid`: use Unpaywall (DOI) to find an OA location outside PMC.**
Only meaningful for finding a legal copy not in PMC (author repository, preprint (bioRxiv), publisher bronze OA).
```bash
curl -s "https://api.unpaywall.org/v2/<DOI>?email=<your-email>"
# check is_oa / oa_locations[]:
#   - host_type=repository with a PMC URL -> re-enter Branch A (efetch) with that PMCID
#   - otherwise (publisher PDF, preprint, etc.) -> use its url_for_pdf
```

If both fail (or there's no OA copy at all), proceed with the abstract only and mark it "(abstract only)" — do not fabricate.
