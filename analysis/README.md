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
| `unparsed_text` | Requirement text the parser ignored (standing, permission, credit counts, high-school courses) |

### Edge attributes

| Attribute | Meaning |
|---|---|
| `type` | `prereq` or `coreq` |
| `group_id` | Edges with the same `group_id` are alternatives ("one of"); a course needs every one of its groups |
| `alternatives` | Number of courses in the edge's group; `1` means that exact course is required |

## Known limitations

- Non-course alternatives are dropped. For "COSC 310 or fourth-year standing", COSC 310
  becomes a required edge, and the standing alternative is kept in `unparsed_text`.
- Courses that list many options ("one of ENGL 109, 112, 114, ...") have high raw
  out-degree. To weight each edge by how required it is, use
  `strength(g, mode = "out", weights = 1 / E(g)$alternatives)`.
- `diameter()` gives the longest *shortest* path. Longest prerequisite chains need a
  longest-path calculation on the DAG.
