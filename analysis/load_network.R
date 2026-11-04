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
  edges <- edges[edges$type %in% types, ]

  nodes$label <- sub("_O ", " ", nodes$course_code)
  nodes$subject <- sub("_O$", "", nodes$subject_code)
  nodes$in_calendar <- as.logical(nodes$in_calendar)

  g <- graph_from_data_frame(edges, directed = TRUE, vertices = nodes)
  if (simplify) {
    # "Either" requirements put some pairs in several groups; keep the strictest.
    g <- simplify(g, remove.loops = TRUE, edge.attr.comb = list(
      alternatives = "min", group_id = "first", type = "first", "ignore"))
  }
  g
}

if (sys.nframe() == 0) {
  g <- load_network()
  stopifnot(is_dag(g), vcount(g) > 0, ecount(g) > 0, !any_multiple(g))
  cat(vcount(g), "courses,", ecount(g), "prerequisite edges, acyclic\n")
  top <- head(sort(degree(g, mode = "out"), decreasing = TRUE), 5)
  cat("Top gateways:", paste0(V(g)[names(top)]$label, " (", top, ")"), sep = "\n  ")
}
