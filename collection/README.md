# Collection pipeline

Python tools for collecting and converting project data.

## Data setup

Download both snapshots from
[GitHub Releases](https://github.com/tysonLivadney/COSC421-Project/releases/latest)
and extract the run folders into:

- Course Schedule: `data/raw/course_schedule/`
- Academic Calendar: `data/raw/academic_calendar/course_descriptions/`

Generate the processed files:

```powershell
python collection/json_to_csv.py
python collection/parse_academic_calendar.py
```

Raw and processed data are not committed to Git. Processed files can always be
regenerated from the released raw snapshots.

## Academic Calendar collector

Download every course-description subject page:

```powershell
python collection/collect_academic_calendar.py
```

Download one subject while testing:

```powershell
python collection/collect_academic_calendar.py --subject COSC_O
```

## Course Schedule collector

Download all configured datasets:

```powershell
python collection/collect_course_schedule.py
```

Download one dataset:

```powershell
python collection/collect_course_schedule.py --dataset academic_periods
```

## JSON converter

`json_to_csv.py` reads the newest completed JSON:API collection from the
location in `config.json` and writes:

- `primary_resources.csv`
- `included_resources.csv`
- `resources.jsonl`

Run from the repository root:

```powershell
python collection/json_to_csv.py
```

Use a different configuration:

```powershell
python collection/json_to_csv.py --config path/to/config.json
```

Convert a specific run:

```powershell
python collection/json_to_csv.py --run-directory path/to/run
```

Run tests:

```powershell
python -m unittest discover -s collection/tests -t . -v
```
