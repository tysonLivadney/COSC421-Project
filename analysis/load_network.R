suppressPackageStartupMessages(library(igraph))

load_network <- function(dir = "data/processed/network",
                         types = "prereq",
                         simplify = TRUE) {
  paths <- file.path(dir, c("nodes.csv", "edges.csv"))
  missing <- paths[!file.exists(paths)]
  if (length(missing)) {
    stop("Missing ", paste(missing, collapse = ", "),
         " - run `python collection/build_network.py` from the repo root first.")
  }
  nodes <- read.csv(paths[1], stringsAsFactors = FALSE, na.strings = "")
  edges <- read.csv(paths[2], stringsAsFactors = FALSE)

  edges$alternatives <- as.vector(table(edges$group_id)[as.character(edges$group_id)])
  edges$required <- edges$alternatives == 1 & is.na(edges$alternative_year)
  edges <- edges[edges$type %in% types, ]

  nodes$label <- sub("_O ", " ", nodes$course_code)
  nodes$subject <- sub("_O$", "", nodes$subject_code)
  nodes$in_calendar <- as.logical(nodes$in_calendar)

  g <- graph_from_data_frame(edges, directed = TRUE, vertices = nodes)
  if (simplify) {
    # "Either" requirements put some pairs in several groups; keep the strictest.
    g <- simplify(g, remove.loops = TRUE, edge.attr.comb = list(
      alternatives = "min", required = "max", group_id = "first", type = "first", "ignore"))
  }
  g
}

PROGRAM_DIR <- "data/processed/academic_calendar/academic_programs"
ROLES <- c(course = "required", course_choice = "choice", elective = "elective list")

section_years <- function(section) {
  parts <- strsplit(tolower(section), " > ", fixed = TRUE)[[1]]
  parts <- parts[grepl("year", parts)]
  ordinals <- c(first = 1, second = 2, third = 3, fourth = 4, fifth = 5)
  found <- unlist(regmatches(parts, gregexpr("\\b(first|second|third|fourth|fifth)\\b", parts)))
  if (length(found)) range(ordinals[found]) else c(NA_real_, NA_real_)
}

find_program <- function(programs, program) {
  program <- as.character(program)
  hit <- programs$program_id == program | tolower(programs$name) == tolower(program)
  if (!any(hit)) hit <- grepl(tolower(program), tolower(programs$name), fixed = TRUE)
  if (sum(hit) == 1) return(programs$program_id[hit])
  if (!any(hit)) stop("No program matches '", program, "'")
  stop("'", program, "' matches several programs; use one of:\n  ",
       paste(programs$name[hit], collapse = "\n  "))
}

load_program <- function(program, g = load_network(), track = NULL, dir = PROGRAM_DIR) {
  paths <- file.path(dir, c("programs.csv", "requirements.csv"))
  missing <- paths[!file.exists(paths)]
  if (length(missing)) {
    stop("Missing ", paste(missing, collapse = ", "),
         " - run `python collection/parse_academic_programs.py` from the repo root first.")
  }
  programs <- read.csv(paths[1], colClasses = "character")
  program_id <- find_program(programs, program)

  reqs <- read.csv(paths[2], colClasses = "character", na.strings = "")
  reqs <- reqs[reqs$program_id == program_id & reqs$source_type == "table", ]
  if (!is.null(track)) reqs <- reqs[grepl(track, reqs$section, ignore.case = TRUE), ]
  if (!nrow(reqs)) stop("No requirement tables for program ", program_id)
  reqs$credits <- as.numeric(reqs$credits)
  reqs <- reqs[order(as.numeric(reqs$position)), ]
  years <- t(vapply(reqs$section, section_years, numeric(2), USE.NAMES = FALSE))
  # Some tables put year headings ("Second Year") in a row of their own; that year applies
  # to the rows after it in the same section.
  heading <- reqs$requirement_kind == "other" & grepl("^\\W*(\\w+ (and|to) )?\\w+ years?\\W*$",
                                                      tolower(reqs$requirement_text))
  for (i in seq_len(nrow(reqs))[-1]) {
    same_section <- reqs$section[i] == reqs$section[i - 1]
    if (heading[i]) years[i, ] <- section_years(paste("x >", reqs$requirement_text[i]))
    else if (same_section && is.na(years[i, 1])) years[i, ] <- years[i - 1, ]
  }
  reqs$year_min <- years[, 1]
  reqs$year_max <- years[, 2]

  codes <- strsplit(ifelse(is.na(reqs$course_codes), "", reqs$course_codes), "|", fixed = TRUE)
  rows <- rep(seq_len(nrow(reqs)), lengths(codes))
  listed <- data.frame(course = unlist(codes), kind = reqs$requirement_kind[rows],
                       requirement_id = reqs$requirement_id[rows],
                       year_min = reqs$year_min[rows], year_max = reqs$year_max[rows])
  listed <- listed[listed$kind %in% names(ROLES), ]
  # A course listed several times keeps its strongest role, then its earliest year.
  listed <- listed[order(match(listed$kind, names(ROLES)), listed$year_min), ]
  listed <- listed[!duplicated(listed$course), ]

  idx <- match(V(g)$name, listed$course)
  V(g)$role <- ifelse(is.na(idx), "not listed", ROLES[listed$kind[idx]])
  V(g)$requirement_id <- listed$requirement_id[idx]
  V(g)$program_year_min <- listed$year_min[idx]
  V(g)$program_year_max <- listed$year_max[idx]

  list(graph = g, requirements = reqs,
       name = programs$name[programs$program_id == program_id],
       missing = setdiff(listed$course, V(g)$name))
}

SCHEDULE_DIR <- "data/processed/course_schedule"

# Which winter terms each course had sections in, across the collected years:
# a logical matrix with columns T1 and T2, one row per course that had any. Summer
# sections are ignored.
load_offerings <- function(dir = SCHEDULE_DIR) {
  paths <- file.path(dir, c("primary_resources.csv", "included_resources.csv"))
  missing <- paths[!file.exists(paths)]
  if (length(missing)) {
    stop("Missing ", paste(missing, collapse = ", "),
         " - run `python collection/json_to_csv.py` from the repo root first.")
  }
  read_columns <- function(path, keep) {
    header <- names(read.csv(path, nrows = 1, check.names = FALSE))
    read.csv(path, check.names = FALSE,
             colClasses = ifelse(header %in% keep, "character", "NULL"))
  }
  sections <- read_columns(paths[1], c("resource_type", "source_file", "relationship.field_course.ids"))
  courses <- read_columns(paths[2], c("resource_type", "resource_id", "attribute.field_course_code"))
  sections <- sections[sections$resource_type == "node--section", ]
  courses <- courses[courses$resource_type == "node--course", ]

  ids <- regmatches(sections$relationship.field_course.ids,
                    gregexpr("[0-9a-f-]{36}", sections$relationship.field_course.ids))
  term <- sub(".*winter_term_([12])_sections.*", "T\\1", sections$source_file)
  rows <- rep(seq_len(nrow(sections)), lengths(ids))
  offered <- data.frame(
    course = courses$attribute.field_course_code[match(unlist(ids), courses$resource_id)],
    term = term[rows])
  offered <- offered[!is.na(offered$course) & offered$term %in% c("T1", "T2"), ]
  unclass(table(offered$course, factor(offered$term, c("T1", "T2")))) > 0
}

if (sys.nframe() == 0) {
  g <- load_network()
  stopifnot(is_dag(g), vcount(g) > 0, ecount(g) > 0, !any_multiple(g))
  cat(vcount(g), "courses,", ecount(g), "prerequisite edges, acyclic\n")
  top <- head(sort(degree(g, mode = "out"), decreasing = TRUE), 5)
  cat("Top gateways:", paste0(V(g)[names(top)]$label, " (", top, ")"), sep = "\n  ")

  if (file.exists(file.path(PROGRAM_DIR, "requirements.csv"))) {
    p <- load_program("Computer Science (B.Sc.)", g)
    v <- V(p$graph)
    role <- setNames(v$role, v$name)
    year <- setNames(v$program_year_min, v$name)
    stopifnot(role[["COSC_O 121"]] == "required", year[["COSC_O 121"]] == 1,
              role[["COSC_O 111"]] == "choice", role[["COSC_O 499"]] == "required",
              year[["COSC_O 499"]] == 3, role[["COSC_O 360"]] == "elective list",
              role[["ANTH_O 100"]] == "not listed")
    cat("\n", p$name, ": ", sep = "")
    print(table(role[role != "not listed"]))
  }
}
