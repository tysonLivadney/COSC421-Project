# Analysis

R analysis of the prerequisite network. Run everything from the repository root.

## Building the network

Generate the network CSVs after the [collection steps](../collection/README.md):

```bash
python collection/build_network.py
```

This writes `data/processed/network/nodes.csv` and `edges.csv`.

## Loading the network

```r
source("analysis/load_network.R")
g <- load_network()                                   # prerequisites, one edge per pair
g <- load_network(types = c("prereq", "coreq"), simplify = FALSE)  # every raw edge
```

`Rscript analysis/load_network.R` runs a quick self-check: it confirms the graph
is acyclic and prints the top gateway courses.

Edges point from prerequisite to course, so out-degree is the "gateway" score.

### Vertex attributes

| Attribute | Meaning |
|---|---|
| `name` | Course code as in the Calendar data (`COSC_O 111`) |
| `label` | Display name (`COSC 111`) |
| `subject` | Subject without the campus suffix (`COSC`) |
| `year_level` | First digit of the course number |
| `credits`, `title` | From the Calendar |
| `in_calendar` | `FALSE` for prerequisites that are no longer listed in the Calendar |
| `unparsed_text` | Requirement text that isn't a UBC course (standing, permission, credit counts, high-school courses), for review |
| `min_standing` | Year standing the course strictly requires ("and third-year standing" → `3`), `NA` if none |

### Edge attributes

| Attribute | Meaning |
|---|---|
| `type` | `prereq` or `coreq` |
| `group_id` | Edges with the same `group_id` are alternatives ("one of"); a course needs every one of its groups |
| `alternatives` | Number of courses in the edge's group |
| `alternative_year` | If the group can also be satisfied without a course (standing, high school, permission, ...), the earliest year that option is available: `1` for high school/permission, `N` for N-year standing. `NA` if a course is the only way |
| `required` | `TRUE` when this exact course is the only way to satisfy its group (`alternatives == 1` and no `alternative_year`) |

## Loading a program

`load_program()` joins one program's requirements onto the network. Pass the program's
name as it appears in the Calendar (case doesn't matter). Any unique part of the name
also works. If a name matches several programs, it stops and lists them. Names are in
`data/processed/academic_calendar/academic_programs/programs.csv`, and that file's
`program_id` also works.

```r
p <- load_program("Computer Science (B.Sc.)")   # uses load_network() unless you pass `g`
p <- load_program("anthropology")
p <- load_program("Economics (B.A.)", track = "Major")   # page lists both Major and Honours
p$graph          # the network with program attributes added (below)
p$requirements   # the program's requirement table rows, with year_min / year_max
p$name           # "Computer Science (B.Sc.)"
p$missing        # listed courses that aren't in the network (e.g. retired courses)
```

Only rows from the Calendar's requirement *tables* are used. Paragraph and list rows mix
real requirements with notes like "COSC 101 is recommended". Some tables put year
headings ("Second Year") in a row of their own instead of in the section name; that year
is applied to the rows after it in the same section.

### Program vertex attributes

| Attribute | Meaning |
|---|---|
| `role` | `required`, `choice` (pick from a listed set), `elective list` (named in an elective/concentration row), or `not listed` |
| `program_year_min`, `program_year_max` | Year(s) of the section the course is listed under; `3`-`4` for "Third and Fourth Years", `NA` if the section names no year |
| `requirement_id` | Row in `requirements.csv` the role came from |

A course listed more than once keeps its strongest role (required > choice > elective
list) and the earliest year it's listed in.

## Figures

Pass one or more subject codes (at least one is required):

```bash
Rscript analysis/viz.R COSC
Rscript analysis/viz.R COSC ENGL STAT
Rscript analysis/viz.R COSC --program "Computer Science (B.Sc.)"
```

Pass any number of subjects and `--program "NAME"` options (program names work as in
`load_program()`); at least one of either is required. Each run writes the
calendar-wide figures to `figures/`, plus one folder per subject under
`figures/subjects/` and one per program under `figures/programs/`:

```
figures/
├── gateways.png, bridges.png, degree_distribution.png, subject_heatmap.png, program_comparison.png
├── subjects/cosc/                      gateways, chain
└── programs/computer-science-b-sc/     credits_by_year, slack, hidden_prerequisites, failure_impact
```

| File | Shows |
|---|---|
| `gateways.png` | Top 15 courses by out-degree, weighted by `1 / alternatives` |
| `bridges.png` | Top 15 courses by betweenness, whole calendar |
| `degree_distribution.png` | In- and out-degree distributions (log-log) |
| `subject_heatmap.png` | Prerequisite links between subjects (prerequisite subject → course subject) |
| `program_comparison.png` | Share of each program's credits that are required, chosen from a list, or electives |
| `subjects/<subject>/gateways.png` | The subject's courses plus all their prerequisites, node size = out-degree |
| `subjects/<subject>/chain.png` | Longest prerequisite chain in the subject, highlighted |
| `programs/<program>/credits_by_year.png` | Required / choose-from-a-list / elective credits in each year of the program |
| `programs/<program>/slack.png` | For each required course, the earliest and latest term it can start |
| `programs/<program>/hidden_prerequisites.png` | Courses the program lists that need a course it doesn't require |
| `programs/<program>/failure_impact.png` | For each required course: which required courses failing it pushes back, and whether graduation is delayed |

Dashed edges have alternatives; solid edges are required (the `required` attribute). The chosen
subject is always blue; the next two most common subjects get the other colours and
the rest are grey "Other", so the colours stay colour-blind safe.

In the network plots, interchangeable courses (same prerequisites, unlock the same
courses) are drawn as one node, e.g. "ENGL 109 (+8 alt.)". Metrics are computed
before merging.

### Credits by year

Credits come from the program's requirement tables. Electives are the year's "Total
Credits" minus required and choose-from-a-list credits, so alternative elective rows
(e.g. the four COSC concentrations) aren't double counted. Rows under a section that
names no year are shown as "Year not given" rather than dropped. B.A. programs only list
the major's requirements, so their totals are the major's credits, not the whole degree.

### Program comparison

Uses the same credit counts as credits by year, for every program whose requirement
tables are complete enough to compare. That means every year has a total, required +
choice doesn't exceed it, no credits fall under "Year not given", and the years add up
to 90–130 credits (one degree, not a major plus a separate whole-degree table). 14 of
the 49 programs with tables pass. Most B.A. pages fail the last check, and pages that
list alternative options in one table (e.g. Biochemistry) fail the total check.
Engineering programs start at second year and are labelled "(from year 2)".

Pages with several tracks are compared on their first Major (e.g. Economics' Major, not
its Honours); pages without a Major drop their Honours and Minor tracks.

### Slack

Terms are numbered Y1 T1 to Y4 T2 (two terms a year, no summer). A course can only start
in a winter term it had sections in, according to the course schedule data
(`load_offerings()`, 2025-26 and 2026-27; e.g. COSC 304 runs in Term 1 only). Courses
with no winter sections in that data are assumed to run every term. Starts snap
forward (earliest) or back (latest) to the nearest term the course runs.

- **Earliest start:** the term after the quickest way through each prerequisite group,
  and no earlier than the course's required standing. A non-course option (high
  school, standing) counts as a way through.
- **Latest start:** the end of the program year the course is listed in, moved earlier
  for any later required course that strictly needs it. This follows the program's year
  plan, which is a recommendation rather than a hard deadline.
- 6+ credit courses (e.g. COSC 499) run September to April, so they take two terms and
  start in term 1.

"No slack" courses have to be taken in exactly that term to stay on the program's plan.
Whether failing one actually delays graduation is what the failure impact figure shows.

### Program failure impact

Each required course is failed once in its planned term (its earliest start, but not
before the first term of the year the program lists it in) and retaken the next time
it's offered. Every other course still starts as early as its prerequisites allow.
"Pushes back" lists the required courses whose earliest start moves later. Graduation
is delayed when any required course is pushed past the latest start that still
finishes the degree on time. That's the slack chart's latest start, but measured
against the end of the degree instead of the program's year plan. It doesn't model how
many courses fit in one term, so it shows the best case for catching up.

For B.Sc. Computer Science only COSC 304 (Term 1 only, needed for COSC 499) and COSC 499
itself delay graduation if failed, each by a year. Failing COSC 121, 221 or 222 pushes
later courses back, but they can be caught up.

### Hidden prerequisites

For each course the program lists (required, choice or elective), this shows what else it
needs that the program doesn't cover:

- **Only option:** a prerequisite with no alternative, followed further back (e.g. COSC 444
  needs COSC 344).
- **One of these:** a "one of" group where the program lists none of the options (e.g.
  COSC 344 needs APSC 248 or MATH 200).

Required courses are checked against the other required courses. Choices and electives
are checked against everything a student is already forced to take. A listed choice can
show up as a need: COSC 270 needs COSC 111, which fixes the program's "COSC 111 or 123"
choice.

Programs with no requirement tables in the Calendar (24 of 73) have no program figures.

From R, pick the chain's end course or plot any subgraph:

```r
source("analysis/viz.R")
g <- load_network()
subject_figures(g, "COSC", target = "COSC_O 499")
plot_network(focus_subgraph(g, c("MATH", "STAT")), ...)
longest_path(g, "COSC_O 499")
```

## Degree planning across programs

```bash
Rscript analysis/degree_planning.R
```

Runs the slack and failure-impact calculations above for every program that passes the
program comparison's completeness check (14 programs) and writes to `figures/planning/`:

| File | Shows |
|---|---|
| `bottleneck_courses.png` | Grid of required courses that delay graduation if failed, by program, with the terms each course runs |
| `program_fragility.png` | Programs ranked by how many required courses delay graduation if failed |
| `program_summary.csv` | One row per program: required courses, no-slack courses, courses that delay graduation, and share of fixed credits |
| `bottleneck_courses.csv` | One row per required course across programs |
| `required_courses.csv` | One row per required course per program |

This analysis covers the 14 programs whose requirement tables have complete year-by-year
information, the same programs shown in `program_comparison.png`. Programs whose Calendar
pages are structured differently, such as those that list course options in a single
table or describe several pathways on the same page, are outside the scope of this
analysis.

## Known limitations

- Non-course requirements other than standing (permission, credit counts like "6
  credits of HIST", grades) aren't modelled beyond `alternative_year`. Their text is
  kept in `unparsed_text`.
- Some program pages file later years under a section with no year (e.g. Mathematics
  (B.Sc.)), and engineering programs start at second year (first year is a common
  program on another page).
- Courses that list many options ("one of ENGL 109, 112, 114, ...") have high raw
  out-degree. To weight each edge by how required it is, use
  `strength(g, mode = "out", weights = 1 / E(g)$alternatives)`.
- `diameter()` gives the longest *shortest* path. Longest prerequisite chains need a
  longest-path calculation on the DAG.
