# Paper download log

Attempted downloads from the previously recommended list. Access was not bypassed.

- `paper_list.tsv`: DOI and title list.
- `paper_downloads.json`: OpenAlex lookup/download results.
- `download_papers.py`: reproducible downloader.

Status meanings:

- `downloaded`: a PDF was retrieved and exceeded the minimum size check.
- `no_open_pdf`: metadata lookup found no open PDF.
- `download_failed`: an open-looking link rejected the request or was blocked.
- `metadata_failed`: publisher/metadata API returned an error.

Direct attempts found mixed access. MDPI and Hindawi endpoints returned HTTP 403 in this environment; the JZUS page was HTML rather than a PDF; the Elsevier DOI resolved to a small access page rather than a PDF. IEEE and most publisher papers require subscription or institutional access.

The list is intentionally retained so papers can be downloaded later from an authenticated institutional browser or manually from the DOI pages.
