# Collection pipeline

The collection layer is intentionally separate from the R analysis. Raw source
responses are immutable inputs; generated CSV files are disposable views that
can always be rebuilt.

## Current converter

The `collection/` directory is a self-contained Python service. Its source,
configuration, dependency file, tests, and fixtures all live here so the R
analysis does not depend on its internal implementation.

`json_to_csv.py` converts saved JSON:API documents, including paginated UBC
Course Schedule responses, into:

- `primary_resources.csv`: resources in each response's `data` member;
- `included_resources.csv`: related resources from `included`;
- `resources.jsonl`: a lossless copy of every resource plus its source file and
  role in the response.

Nested attribute values are retained as compact JSON cells. Relationships are
flattened into resource IDs, resource types, and Drupal target IDs. The raw
response remains the authoritative source.

Configuration lives in `config.json`. All configured paths are relative to the
repository root unless an absolute path is supplied.

Run the converter from the repository root:

```powershell
python collection/json_to_csv.py
```

Or provide another configuration:

```powershell
python collection/json_to_csv.py --config path/to/config.json
```

Run the collection-service tests from the repository root:

```powershell
python -m unittest discover -s collection/tests -t . -v
```

The converter overwrites its generated outputs atomically. It never changes or
deletes raw input files.

Network construction and all analytical decisions remain outside this layer
and will be implemented in R.

## Planned sources

The project needs two complementary UBC sources; neither is sufficient alone:

- **Course Schedule JSON:API:** actual sections and observed offerings by
  academic period.
- **UBC Okanagan Academic Calendar:** the broader course catalogue,
  prerequisite and corequisite text, and formal program/degree requirements.

Calendar program requirements are necessary to distinguish courses that are
explicitly required by a program from courses that appear only as indirect
prerequisites or electives. Future collectors should therefore store Calendar
course descriptions and program requirements separately under
`data/raw/academic_calendar/`, while preserving the source URL, Calendar year,
collection time, and original HTML or JSON response.
