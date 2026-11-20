source("analysis/load_network.R")
suppressPackageStartupMessages(library(ggplot2))

PALETTE <- c("#2a78d6", "#eb6834", "#1baf7a")
OTHER <- "#b5b4ae"
INK <- "#0b0b0b"
MUTED <- "#52514e"

theme_net <- function() {
  theme_minimal(base_size = 12) +
    theme(
      text = element_text(colour = INK),
      axis.text = element_text(colour = MUTED),
      plot.subtitle = element_text(colour = MUTED),
      panel.grid.minor = element_blank(),
      panel.grid.major = element_line(colour = "#e6e5e1", linewidth = 0.3),
      plot.background = element_rect(fill = "#fcfcfb", colour = NA)
    )
}

focus_subgraph <- function(g, subjects = "COSC") {
  courses <- V(g)[subject %in% subjects]
  keep <- unique(unlist(ego(g, order = vcount(g), nodes = courses, mode = "in")))
  induced_subgraph(g, keep)
}

# The palette only stays colour-blind safe with up to 3 hues, so the rest are "Other".
subject_palette <- function(g, first = NULL) {
  top <- head(unique(c(first, names(sort(table(V(g)$subject), decreasing = TRUE)))),
              length(PALETTE))
  c(setNames(PALETTE[seq_along(top)], top), Other = OTHER)
}

longest_path <- function(g, to = NULL) {
  order <- as_ids(topo_sort(g))
  length_to <- setNames(rep(0, vcount(g)), V(g)$name)
  previous <- setNames(rep(NA_character_, vcount(g)), V(g)$name)
  for (v in order) {
    preds <- as_ids(neighbors(g, v, mode = "in"))
    if (length(preds)) {
      best <- preds[which.max(length_to[preds])]
      length_to[v] <- length_to[best] + 1
      previous[v] <- best
    }
  }
  v <- if (is.null(to)) names(which.max(length_to)) else to
  path <- v
  while (!is.na(previous[v])) {
    v <- previous[v]
    path <- c(v, path)
  }
  unname(path)
}

plot_top <- function(g, values, title, subtitle, file, n = 15) {
  top <- head(sort(setNames(values, V(g)$label), decreasing = TRUE), n)
  df <- data.frame(course = factor(names(top), rev(names(top))), value = as.numeric(top))
  p <- ggplot(df, aes(value, course)) +
    geom_col(fill = PALETTE[1], width = 0.7) +
    geom_text(aes(label = round(value, 1)), hjust = -0.2, colour = MUTED, size = 3.3) +
    scale_x_continuous(expand = expansion(mult = c(0, 0.1))) +
    labs(title = title, subtitle = subtitle, x = NULL, y = NULL) +
    theme_net() +
    theme(panel.grid.major.y = element_blank())
  ggsave(file, p, width = 8, height = 5, dpi = 200)
}

plot_degree_distribution <- function(g, file) {
  df <- rbind(
    data.frame(direction = "In-degree (direct prerequisites)", degree = degree(g, mode = "in")),
    data.frame(direction = "Out-degree (courses unlocked)", degree = degree(g, mode = "out"))
  )
  counts <- aggregate(list(courses = df$degree), df[c("direction", "degree")], length)
  counts <- counts[counts$degree > 0, ]
  p <- ggplot(counts, aes(degree, courses)) +
    geom_point(colour = PALETTE[1], size = 2.5) +
    scale_x_log10() +
    scale_y_log10() +
    facet_wrap(~direction) +
    labs(
      title = "Degree distribution",
      subtitle = sprintf("%d courses; courses with degree 0 not shown (log-log)", vcount(g)),
      x = "Degree", y = "Number of courses"
    ) +
    theme_net()
  ggsave(file, p, width = 9, height = 4.5, dpi = 200)
}

plot_network <- function(g, size_by, title, file, layout = layout_with_kk(g), n_labels = 12,
                         highlight = NULL, palette = subject_palette(g)) {
  nodes <- data.frame(
    x = layout[, 1], y = layout[, 2], label = V(g)$label,
    group = ifelse(V(g)$subject %in% names(palette), V(g)$subject, "Other"),
    size = 2 + 8 * sqrt(size_by / max(size_by, 1))
  )
  nodes$labelled <- if (is.null(highlight)) rank(-size_by, ties.method = "first") <= n_labels else
    V(g)$name %in% highlight

  ends <- ends(g, E(g), names = FALSE)
  edges <- data.frame(
    x = nodes$x[ends[, 1]], y = nodes$y[ends[, 1]],
    xend = nodes$x[ends[, 2]], yend = nodes$y[ends[, 2]],
    kind = ifelse(E(g)$required, "required", "has alternatives"),
    on_path = if (is.null(highlight)) FALSE else E(g) %in% E(g, path = highlight)
  )
  # Stop each edge just outside its target node. Point sizes are in mm, so convert
  # through the approximate panel size (in mm) of the 12 x 9 inch figure.
  panel_mm <- c(296, 202) / 1.1
  span <- c(diff(range(nodes$x)), diff(range(nodes$y)))
  span[span == 0] <- 1
  mm_per_unit <- panel_mm / span
  dx <- (edges$xend - edges$x) * mm_per_unit[1]
  dy <- (edges$yend - edges$y) * mm_per_unit[2]
  len <- pmax(sqrt(dx^2 + dy^2), 1e-9)
  radius <- 0.375 * nodes$size[ends[, 2]] + 0.8
  stop_at <- pmax(1 - radius / len, 0)
  head_from <- pmax(stop_at - 0.5 / len, 0)
  edges$xstop <- edges$x + stop_at * (edges$xend - edges$x)
  edges$ystop <- edges$y + stop_at * (edges$yend - edges$y)
  edges$xhead <- edges$x + head_from * (edges$xend - edges$x)
  edges$yhead <- edges$y + head_from * (edges$yend - edges$y)
  arrow_head <- arrow(length = unit(1.8, "mm"), type = "closed")

  p <- ggplot() +
    geom_segment(data = edges, aes(x, y, xend = xhead, yend = yhead, linetype = kind,
                                   colour = on_path, linewidth = on_path)) +
    geom_segment(data = edges, aes(xhead, yhead, xend = xstop, yend = ystop,
                                   colour = on_path, linewidth = on_path),
                 arrow = arrow_head, linetype = "solid") +
    geom_point(data = nodes, aes(x, y, fill = group, size = size),
               shape = 21, colour = "#fcfcfb", stroke = 0.6) +
    ggrepel::geom_label_repel(
      data = nodes[nodes$labelled, ], aes(x, y, label = label, point.size = size),
      size = 3, colour = INK, fill = alpha("#fcfcfb", 0.85), label.size = NA,
      box.padding = 0.4, min.segment.length = 0, segment.colour = MUTED,
      max.overlaps = Inf, seed = 1
    ) +
    scale_fill_manual(values = palette, breaks = names(palette), name = NULL) +
    scale_size_identity() +
    scale_colour_manual(values = c(`FALSE` = alpha(MUTED, 0.4), `TRUE` = INK), guide = "none") +
    scale_linewidth_manual(values = c(`FALSE` = 0.3, `TRUE` = 1.1), guide = "none") +
    scale_linetype_manual(values = c(required = "solid", `has alternatives` = "22"), name = NULL) +
    guides(fill = guide_legend(override.aes = list(size = 4))) +
    labs(title = title) +
    theme_void(base_size = 12) +
    theme(plot.background = element_rect(fill = "#fcfcfb", colour = NA),
          plot.margin = margin(12, 12, 12, 12), legend.position = "bottom")
  ggsave(file, p, width = 12, height = 9, dpi = 200)
}

plot_chain <- function(g, to, file, palette = NULL) {
  path <- longest_path(g, to)
  sub <- induced_subgraph(g, subcomponent(g, to, mode = "in"))
  if (is.null(palette)) palette <- subject_palette(sub)
  layout <- layout_with_sugiyama(sub)$layout
  plot_network(
    sub, size_by = rep(1, vcount(sub)), layout = layout, highlight = path,
    title = sprintf("Longest prerequisite chain to %s (%d courses), rows = prerequisite depth",
                    sub("_O ", " ", to), length(path)),
    file = file, palette = palette
  )
}

# Plotting only: courses with identical prerequisites and identical dependants
# (e.g. ENGL 109/112/114/...) become one node, keeping the largest value.
merge_equivalent <- function(g, values) {
  key <- sapply(V(g), function(v) {
    out <- sort(as_ids(neighbors(g, v, "out")))
    if (!length(out)) return(V(g)$name[v])
    paste(paste(sort(as_ids(neighbors(g, v, "in"))), collapse = ","), paste(out, collapse = ","))
  })
  groups <- match(key, unique(key))
  first <- !duplicated(groups)
  extra <- tabulate(groups) - 1
  merged <- contract(g, groups, vertex.attr.comb = "first")
  merged <- simplify(merged, edge.attr.comb = list(alternatives = "min", required = "max", "first"))
  V(merged)$label <- ifelse(extra > 0, sprintf("%s (+%d alt.)", V(merged)$label, extra),
                            V(merged)$label)
  list(graph = merged, values = as.vector(tapply(values, groups, max)))
}

plot_merged <- function(g, values, title, file, palette) {
  m <- merge_equivalent(g, values)
  plot_network(m$graph, m$values, title, file, palette = palette)
}

plot_subject_heatmap <- function(g, file, n = 15) {
  ends <- ends(g, E(g))
  df <- data.frame(from = V(g)[ends[, 1]]$subject, to = V(g)[ends[, 2]]$subject)
  df <- df[df$from != df$to, ]
  top_from <- head(names(sort(table(df$from), decreasing = TRUE)), n)
  top_to <- head(names(sort(table(df$to), decreasing = TRUE)), n)
  counts <- as.data.frame(table(from = factor(df$from, top_from), to = factor(df$to, top_to)))
  counts$Freq[counts$Freq == 0] <- NA
  p <- ggplot(counts, aes(to, from, fill = Freq)) +
    geom_tile(colour = "#fcfcfb", linewidth = 0.6) +
    geom_text(aes(label = Freq, colour = Freq > max(Freq, na.rm = TRUE) / 2),
              size = 3, na.rm = TRUE) +
    scale_fill_gradient(low = "#cde2fb", high = "#104281", na.value = "#f1f0ed",
                        name = "Edges") +
    scale_colour_manual(values = c(`FALSE` = INK, `TRUE` = "#fcfcfb"), guide = "none") +
    scale_y_discrete(limits = rev) +
    labs(title = "Prerequisite links between subjects",
         subtitle = sprintf("Top %d subjects each way by cross-subject links; same-subject links excluded", n),
         x = "Course subject", y = "Prerequisite subject") +
    theme_net() +
    theme(panel.grid = element_blank(), axis.text.x = element_text(angle = 45, hjust = 1))
  ggsave(file, p, width = 9, height = 8, dpi = 200)
}

prereq_groups <- function(g_raw) {
  e <- as_data_frame(g_raw)
  lapply(split(e, e$to), function(d) lapply(split(d, d$group_id), function(x)
    list(courses = x$from, alternative_year = x$alternative_year[1])))
}

# A course is blocked when every option in one of its groups is blocked; a group that
# also accepts something other than a course (standing, high school, ...) never blocks.
failure_impact <- function(g_raw, courses) {
  groups <- prereq_groups(g_raw)
  order <- as_ids(topo_sort(g_raw))
  do.call(rbind, lapply(courses, function(course) {
    downstream <- setdiff(as_ids(subcomponent(g_raw, course, mode = "out")), course)
    blocked <- course
    for (v in order[order %in% downstream]) {
      if (any(vapply(groups[[v]], function(grp)
        is.na(grp$alternative_year) && all(grp$courses %in% blocked), logical(1)))) {
        blocked <- c(blocked, v)
      }
    }
    data.frame(course = course, downstream = length(downstream), blocked = length(blocked) - 1)
  }))
}

plot_failure_impact <- function(g_raw, subject, file, n = 15) {
  courses <- V(g_raw)[subject == .env$subject & degree(g_raw, mode = "out") > 0]$name
  impact <- failure_impact(g_raw, courses)
  stopifnot(all(impact$blocked <= impact$downstream))
  impact <- head(impact[order(-impact$blocked, -impact$downstream), ], n)
  impact$label <- factor(sub("_O ", " ", impact$course), rev(sub("_O ", " ", impact$course)))
  long <- rbind(
    data.frame(label = impact$label, value = impact$downstream, kind = "Downstream (any route)"),
    data.frame(label = impact$label, value = impact$blocked, kind = "Blocked (no alternative)")
  )
  long$kind <- factor(long$kind, c("Downstream (any route)", "Blocked (no alternative)"))
  p <- ggplot(long, aes(value, label, fill = kind)) +
    geom_col(position = position_identity(), width = 0.7) +
    geom_text(data = long[long$kind == "Blocked (no alternative)", ],
              aes(label = value), hjust = -0.3, colour = INK, size = 3.2) +
    scale_fill_manual(values = c("#cde2fb", PALETTE[1]), name = NULL) +
    scale_x_continuous(expand = expansion(mult = c(0, 0.05))) +
    labs(title = sprintf("If you fail a %s course", subject),
         subtitle = "Courses anywhere in the calendar you can't take until you pass it",
         x = "Courses", y = NULL) +
    theme_net() +
    theme(panel.grid.major.y = element_blank(), legend.position = "top",
          legend.justification = "left")
  ggsave(file, p, width = 8, height = 5.5, dpi = 200)
}

# Terms are numbered 1-8 (two per year, no summer). 6+ credit courses run September to
# April, so they take two terms and can only start in term 1 of a year (odd terms).
course_terms <- function(g) {
  credits <- suppressWarnings(as.numeric(sub("-.*", "", V(g)$credits)))
  setNames(ifelse(!is.na(credits) & credits >= 6, 2, 1), V(g)$name)
}

term_label <- function(term) sprintf("Y%d T%d", (term + 1) %/% 2, (term + 1) %% 2 + 1)

earliest_terms <- function(g_raw) {
  groups <- prereq_groups(g_raw)
  duration <- course_terms(g_raw)
  standing <- ifelse(is.na(V(g_raw)$min_standing), 1, V(g_raw)$min_standing)
  start <- setNames(2 * standing - 1, V(g_raw)$name)
  for (v in as_ids(topo_sort(g_raw))) {
    for (grp in groups[[v]]) {
      via_course <- min(start[grp$courses] + duration[grp$courses])
      via_other <- if (is.na(grp$alternative_year)) Inf else 2 * grp$alternative_year - 1
      start[v] <- max(start[v], min(via_course, via_other))
    }
    if (duration[v] == 2 && start[v] %% 2 == 0) start[v] <- start[v] + 1
  }
  start
}

# Latest start that still finishes on time: by the end of the program year the course is
# listed in, and early enough for any later required course that strictly needs it.
latest_terms <- function(g_raw, program, required) {
  groups <- prereq_groups(g_raw)
  duration <- course_terms(g_raw)
  v <- V(program$graph)
  last_year <- setNames(v$program_year_max, v$name)[required]
  last_year[is.na(last_year)] <- max(v$program_year_max, na.rm = TRUE)
  latest <- 2 * last_year - duration[required] + 1
  order <- as_ids(topo_sort(g_raw))
  for (course in rev(order[order %in% required])) {
    for (grp in groups[[course]]) {
      pre <- grp$courses
      if (length(pre) == 1 && is.na(grp$alternative_year) && pre %in% required) {
        latest[pre] <- min(latest[pre], latest[course] - duration[pre])
        if (duration[pre] == 2 && latest[pre] %% 2 == 0) latest[pre] <- latest[pre] - 1
      }
    }
  }
  latest
}

period_label <- function(from, to) {
  ifelse(is.na(from), "Year not given",
         ifelse(from == to, paste("Year", from), paste0("Years ", from, "-", to)))
}

plot_credits_by_year <- function(program, file) {
  # Rows whose section names no year get their own bar rather than being dropped.
  reqs <- program$requirements
  reqs <- reqs[order(reqs$year_min, as.numeric(reqs$position), na.last = TRUE), ]
  reqs$period <- period_label(reqs$year_min, reqs$year_max)
  rows <- lapply(unique(reqs$period), function(period) {
    r <- reqs[reqs$period == period, ]
    credits <- function(kind) sum(r$credits[r$requirement_kind == kind], na.rm = TRUE)
    total <- r$credits[r$requirement_kind == "total"][1]
    fixed <- c(Required = credits("course"), `Choose from a list` = credits("course_choice"))
    electives <- if (is.na(total)) credits("elective") else max(total - sum(fixed), 0)
    data.frame(period = period, kind = c(names(fixed), "Electives"), credits = c(fixed, electives))
  })
  df <- do.call(rbind, rows)
  df <- df[ave(df$credits, df$period, FUN = sum) > 0, ]
  df$period <- factor(df$period, unique(df$period))
  df$kind <- factor(df$kind, c("Electives", "Choose from a list", "Required"))
  fixed <- sum(df$credits[df$kind != "Electives"])
  p <- ggplot(df, aes(period, credits, fill = kind)) +
    geom_col(width = 0.6, colour = "#fcfcfb", linewidth = 0.6) +
    geom_text(aes(label = ifelse(credits > 0, credits, "")), position = position_stack(vjust = 0.5),
              colour = INK, size = 3.4) +
    scale_fill_manual(values = c(Required = PALETTE[1], `Choose from a list` = PALETTE[2],
                                 Electives = "#d9d8d3"),
                      breaks = c("Required", "Choose from a list", "Electives"), name = NULL) +
    scale_y_continuous(expand = expansion(mult = c(0, 0.05))) +
    labs(title = sprintf("%s: credits by year", program$name),
         subtitle = sprintf("%d of %d listed credits (%.0f%%) are a specific course or a pick from a list",
                            fixed, sum(df$credits), 100 * fixed / sum(df$credits)),
         x = NULL, y = "Credits") +
    theme_net() +
    theme(panel.grid.major.x = element_blank(), legend.position = "top",
          legend.justification = "left")
  ggsave(file, p, width = 7, height = 5.5, dpi = 200)
}

plot_slack <- function(g_raw, program, file) {
  v <- V(program$graph)
  required <- intersect(v$name[v$role == "required"], V(g_raw)$name)
  earliest <- earliest_terms(g_raw)[required]
  latest <- latest_terms(g_raw, program, required)
  duration <- course_terms(g_raw)[required]
  df <- data.frame(course = sub("_O ", " ", required), earliest = earliest, latest = latest)
  df$course <- ifelse(duration == 2, paste(df$course, "(2 terms)"), df$course)
  df$status <- ifelse(latest < earliest, "Behind schedule",
                      ifelse(latest == earliest, "No slack", "Has slack"))
  df <- df[order(df$earliest, df$latest, df$course), ]
  df$course <- factor(df$course, rev(df$course))
  p <- ggplot(df, aes(y = course, colour = status)) +
    geom_segment(aes(x = earliest, xend = pmax(latest, earliest)), linewidth = 2.2, lineend = "round") +
    geom_point(aes(x = earliest), size = 3.2) +
    scale_colour_manual(values = c(`Has slack` = PALETTE[1], `No slack` = PALETTE[2],
                                   `Behind schedule` = INK), name = NULL, drop = TRUE) +
    scale_x_continuous(breaks = 1:8, labels = term_label(1:8), limits = c(0.7, 8.3)) +
    labs(title = sprintf("%s: when each required course can start", program$name),
         subtitle = "From the earliest start allowed to the latest start for a 4-year finish",
         x = NULL, y = NULL) +
    theme_net() +
    theme(panel.grid.major.y = element_blank(), legend.position = "top",
          legend.justification = "left")
  ggsave(file, p, width = 8, height = 1.6 + 0.3 * nrow(df), dpi = 200)
  invisible(df)
}

program_figures <- function(g, program_name, dir = "figures/programs") {
  program <- load_program(program_name, g)
  folder <- file.path(dir, gsub("^-|-$", "", gsub("[^a-z0-9]+", "-", tolower(program$name))))
  dir.create(folder, showWarnings = FALSE, recursive = TRUE)
  plot_credits_by_year(program, file.path(folder, "credits_by_year.png"))
  plot_slack(load_network(simplify = FALSE), program, file.path(folder, "slack.png"))
}

subject_figures <- function(g, subject, target = NULL, dir = "figures/subjects") {
  focus <- focus_subgraph(g, subject)
  linked <- delete_vertices(focus, degree(focus) == 0)
  if (is.null(target)) target <- tail(longest_path(focus), 1)
  prefix <- file.path(dir, tolower(subject), "")
  dir.create(prefix, showWarnings = FALSE, recursive = TRUE)
  palette <- subject_palette(linked, first = subject)
  plot_merged(linked, degree(linked, mode = "out"),
               sprintf("%s prerequisite network, node size = out-degree", subject),
               paste0(prefix, "gateways.png"), palette)
  plot_merged(linked, betweenness(linked),
               sprintf("%s prerequisite network, node size = betweenness", subject),
               paste0(prefix, "bridges.png"), palette)
  plot_chain(g, target, paste0(prefix, "chain.png"), palette)
  plot_failure_impact(load_network(simplify = FALSE), subject, paste0(prefix, "failure_impact.png"))
}

if (sys.nframe() == 0) {
  args <- commandArgs(trailingOnly = TRUE)
  flag <- which(args == "--program")
  programs <- args[flag + 1]
  subjects <- toupper(args[-c(flag, flag + 1)])
  if (anyNA(programs) || !length(c(subjects, programs))) {
    stop('Usage: Rscript analysis/viz.R [SUBJECT ...] [--program "NAME" ...]\n',
         '  e.g. Rscript analysis/viz.R COSC --program "Computer Science (B.Sc.)"')
  }
  dir.create("figures", showWarnings = FALSE)
  g <- load_network()
  unknown <- setdiff(subjects, V(g)$subject)
  if (length(unknown)) stop("Unknown subject(s): ", paste(unknown, collapse = ", "))

  plot_top(g, strength(g, mode = "out", weights = 1 / E(g)$alternatives),
           "Top gateway courses",
           "Courses unlocked, weighted by 1 / size of each 'one of' group",
           "figures/gateways.png")
  plot_top(g, betweenness(g, directed = TRUE),
           "Top bridge courses", "Directed betweenness centrality, whole calendar",
           "figures/bridges.png")
  plot_degree_distribution(g, "figures/degree_distribution.png")
  plot_subject_heatmap(g, "figures/subject_heatmap.png")
  for (subject in subjects) subject_figures(g, subject)
  for (program in programs) program_figures(g, program)
  cat("Wrote", length(list.files("figures", recursive = TRUE)), "files to figures/\n")
}
