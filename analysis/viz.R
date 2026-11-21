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
      plot.background = element_rect(fill = "#fcfcfb", colour = NA),
      plot.title.position = "plot"
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

# Everything the blocking and term calculations need, built once per run and passed
# to the figure functions as `ix`.
prereq_index <- function(g_raw = load_network(simplify = FALSE), offerings = load_offerings()) {
  ix <- list(graph = g_raw, groups = prereq_groups(g_raw), duration = course_terms(g_raw),
             order = as_ids(topo_sort(g_raw)))
  # Terms each course can start in. Courses with no winter sections in the schedule data
  # are assumed to run every term; two-term courses always start in term 1.
  names <- V(g_raw)$name
  ix$offered <- matrix(TRUE, length(names), 2, dimnames = list(names, c("T1", "T2")))
  known <- intersect(names, rownames(offerings))
  ix$offered[known, ] <- offerings[known, ]
  ix$offered[ix$duration == 2, ] <- rep(c(TRUE, FALSE), each = sum(ix$duration == 2))
  standing <- ifelse(is.na(V(g_raw)$min_standing), 1, V(g_raw)$min_standing)
  ix$earliest <- propagate_starts(ix, setNames(2 * standing - 1, V(g_raw)$name), ix$order)
  ix
}

# Terms are numbered 1-8 (two per year, no summer). 6+ credit courses run September to
# April, so they take two terms and can only start in term 1 of a year (odd terms).
# Moves `term` forward (step = 1) or back (step = -1) to a term `course` is offered in.
offered_term <- function(ix, course, term, step = 1) {
  while (!ix$offered[course, 2 - term %% 2]) term <- term + step
  term
}

course_terms <- function(g) {
  credits <- suppressWarnings(as.numeric(sub("-.*", "", V(g)$credits)))
  setNames(ifelse(!is.na(credits) & credits >= 6, 2, 1), V(g)$name)
}

term_label <- function(term) sprintf("Y%d T%d", (term + 1) %/% 2, (term + 1) %% 2 + 1)

# Pushes `start` forward through `courses` (in prerequisite order) so each starts after
# the quickest way through each of its groups. `not_before` sets minimum starts.
propagate_starts <- function(ix, start, courses, not_before = NULL) {
  duration <- ix$duration
  for (v in courses) {
    for (grp in ix$groups[[v]]) {
      via_course <- min(start[grp$courses] + duration[grp$courses])
      via_other <- if (is.na(grp$alternative_year)) Inf else 2 * grp$alternative_year - 1
      start[v] <- max(start[v], min(via_course, via_other))
    }
    if (v %in% names(not_before)) start[v] <- max(start[v], not_before[[v]])
    start[v] <- offered_term(ix, v, start[v])
  }
  start
}

# Earliest start of every course; `not_before` delays some (e.g. a retake after failing).
# Starts only move later, so just the delayed courses and their dependants are redone.
earliest_terms <- function(ix, not_before = NULL) {
  if (is.null(not_before)) return(ix$earliest)
  affected <- unlist(lapply(names(not_before), function(c)
    as_ids(subcomponent(ix$graph, c, mode = "out"))))
  propagate_starts(ix, ix$earliest, ix$order[ix$order %in% affected], not_before)
}

# Latest start that still finishes on time, and early enough for any later required
# course that strictly needs it. "On time" is the end of the year the program lists the
# course in (`plan = TRUE`) or the end of the degree (`plan = FALSE`).
latest_terms <- function(ix, program, required, plan = TRUE) {
  groups <- ix$groups
  duration <- ix$duration
  v <- V(program$graph)
  # Programs that name no years are treated as 4-year degrees.
  final_year <- max(c(v$program_year_max, if (all(is.na(v$program_year_max))) 4), na.rm = TRUE)
  last_year <- if (plan) setNames(v$program_year_max, v$name)[required] else
    setNames(rep(NA, length(required)), required)
  last_year[is.na(last_year)] <- final_year
  latest <- 2 * last_year - duration[required] + 1
  latest <- setNames(vapply(seq_along(required), function(i)
    offered_term(ix, required[i], latest[[i]], step = -1), numeric(1)), required)
  for (course in rev(ix$order[ix$order %in% required])) {
    for (grp in groups[[course]]) {
      pre <- grp$courses
      if (length(pre) == 1 && is.na(grp$alternative_year) && pre %in% required) {
        latest[pre] <- offered_term(ix, pre, min(latest[pre], latest[course] - duration[pre]), -1)
      }
    }
  }
  latest
}

period_label <- function(from, to) {
  ifelse(is.na(from), "Year not given",
         ifelse(from == to, paste("Year", from), paste0("Years ", from, "-", to)))
}

# Credits per year by kind. Rows whose section names no year get their own period rather
# than being dropped; `has_total` says whether the period's credits came from a total row.
credits_by_period <- function(reqs) {
  reqs <- reqs[order(reqs$year_min, as.numeric(reqs$position), na.last = TRUE), ]
  reqs$period <- period_label(reqs$year_min, reqs$year_max)
  rows <- lapply(unique(reqs$period), function(period) {
    r <- reqs[reqs$period == period, ]
    credits <- function(kind) sum(r$credits[r$requirement_kind == kind], na.rm = TRUE)
    total <- r$credits[r$requirement_kind == "total"][1]
    fixed <- c(Required = credits("course"), `Choose from a list` = credits("course_choice"))
    electives <- if (is.na(total)) credits("elective") else max(total - sum(fixed), 0)
    data.frame(period = period, kind = c(names(fixed), "Electives"), credits = c(fixed, electives),
               has_total = !is.na(total), total = total)
  })
  df <- do.call(rbind, rows)
  df[ave(df$credits, df$period, FUN = sum) > 0, ]
}

plot_credits_by_year <- function(program, file) {
  df <- credits_by_period(program$requirements)
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

plot_slack <- function(ix, program, file) {
  v <- V(program$graph)
  required <- intersect(v$name[v$role == "required"], V(ix$graph)$name)
  earliest <- ix$earliest[required]
  latest <- latest_terms(ix, program, required)
  duration <- ix$duration[required]
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
         subtitle = "Earliest start allowed, to the latest start that keeps to the program's year plan",
         x = NULL, y = NULL) +
    theme_net() +
    theme(panel.grid.major.y = element_blank(), legend.position = "top",
          legend.justification = "left")
  ggsave(file, p, width = 8, height = 1.6 + 0.3 * nrow(df), dpi = 200)
  invisible(df)
}

# What `start` needs beyond the `covered` courses: courses that are the only option in a
# group (followed further back), and "one of" groups none of whose options the program lists.
unmet_prerequisites <- function(groups, start, covered, listed) {
  found <- list()
  queue <- start
  while (length(queue)) {
    course <- queue[1]
    queue <- queue[-1]
    for (grp in groups[[course]]) {
      options <- grp$courses
      if (!is.na(grp$alternative_year) || any(options %in% covered)) next
      if (length(options) == 1) {
        found[[length(found) + 1]] <- data.frame(needs = options, one_of = FALSE)
        covered <- c(covered, options)
        queue <- c(queue, options)
      } else if (!any(options %in% listed)) {
        found[[length(found) + 1]] <- data.frame(needs = paste(sort(options), collapse = "|"),
                                                 one_of = TRUE)
      }
    }
  }
  if (length(found)) unique(do.call(rbind, found)) else NULL
}

hidden_prerequisites <- function(ix, program) {
  role <- setNames(V(program$graph)$role, V(program$graph)$name)
  role <- role[names(role) %in% V(ix$graph)$name]
  groups <- ix$groups
  required <- names(role)[role == "required"]
  listed <- names(role)[role != "not listed"]
  # Students take every required course, so whatever those force counts as covered for the rest.
  from_required <- do.call(rbind, lapply(required, function(r)
    unmet_prerequisites(groups, r, required, listed)))
  forced <- c(required, if (!is.null(from_required)) from_required$needs[!from_required$one_of])
  rows <- lapply(listed, function(course) {
    covered <- if (role[[course]] == "required") required else forced
    found <- unmet_prerequisites(groups, course, covered, listed)
    if (!is.null(found)) cbind(course = course, found)
  })
  df <- do.call(rbind, rows)
  if (is.null(df)) return(NULL)
  df$course_role <- role[df$course]
  df$needs_role <- ifelse(df$one_of, "not listed", role[df$needs])
  df
}

plot_hidden_prerequisites <- function(ix, program, file) {
  df <- hidden_prerequisites(ix, program)
  title <- sprintf("%s: prerequisites the program doesn't list", program$name)
  if (is.null(df)) {
    p <- ggplot() + annotate("text", x = 0, y = 0, label = "None found", colour = MUTED) +
      labs(title = title) + theme_void()
    return(ggsave(file, p, width = 7, height = 2, dpi = 200))
  }
  label <- function(codes) gsub("_O ", " ", gsub("|", " or ", codes, fixed = TRUE))
  note <- c(required = "", choice = " (a choice)", `elective list` = " (elective)", `not listed` = "")
  df$row <- paste0(label(df$course), note[df$course_role])
  df$need <- paste0(label(df$needs), note[df$needs_role])
  df$kind <- ifelse(df$one_of, "One of these", "Only option")
  df <- df[order(match(df$course_role, c("required", "choice", "elective list")), df$course,
                 df$one_of), ]
  df$row <- factor(df$row, rev(unique(df$row)))
  df$slot <- ave(seq_len(nrow(df)), df$row, FUN = seq_along)
  p <- ggplot(df, aes(slot, row, label = need, fill = kind)) +
    geom_label(hjust = 0, size = 3.4, linewidth = 0, label.padding = unit(0.35, "lines"),
               colour = INK) +
    scale_fill_manual(values = c(`Only option` = "#f2a07c", `One of these` = "#fbd9c8"),
                      name = "Also needs", breaks = c("Only option", "One of these")) +
    scale_x_continuous(limits = c(1, max(df$slot) + 1.6), expand = c(0, 0.05)) +
    guides(fill = guide_legend(override.aes = list(label = "    "))) +
    labs(title = title,
         subtitle = sprintf("%d of the program's courses need a course it doesn't require",
                            length(unique(df$course))),
         x = NULL, y = NULL) +
    theme_net() +
    theme(panel.grid.major.x = element_blank(), axis.text.x = element_blank(),
          legend.position = "top", legend.justification = "left")
  ggsave(file, p, width = 8, height = 1.8 + 0.4 * length(unique(df$row)), dpi = 200)
}

# Pages that list several tracks: use the first Major, otherwise drop Honours and Minors.
default_track <- function(sections) {
  tops <- unique(sub(" > .*", "", sections))
  if (length(tops) < 2) return(NULL)
  major <- grep("\\bMajor\\b", tops, value = TRUE)
  keep <- if (length(major)) major[1] else grep("Honours|Minor", tops, value = TRUE, invert = TRUE)
  paste0("^(", paste(gsub("([().])", "\\\\\\1", keep), collapse = "|"), ")")
}

# One row per program whose requirement tables give a complete, consistent degree:
# every year has a total, required + choice doesn't exceed it, nothing is under "Year not
# given", and the years add up to 90-130 credits.
program_shares <- function(g) {
  programs <- read.csv(file.path(PROGRAM_DIR, "programs.csv"), colClasses = "character")
  reqs <- read.csv(file.path(PROGRAM_DIR, "requirements.csv"), colClasses = "character")
  rows <- lapply(programs$program_id, function(id) {
    sections <- reqs$section[reqs$program_id == id & reqs$source_type == "table"]
    if (!length(sections)) return(NULL)
    program <- load_program(id, g, track = default_track(sections))
    d <- credits_by_period(program$requirements)
    fixed <- tapply(d$credits[d$kind != "Electives"], d$period[d$kind != "Electives"], sum)
    total <- tapply(d$total, d$period, `[`, 1)
    ok <- nrow(d) > 0 && all(d$has_total) && !any(d$period == "Year not given") &&
      all(fixed[names(total)] <= total) && sum(d$credits) >= 90 && sum(d$credits) <= 130
    years <- program$requirements$year_min
    first_year <- if (all(is.na(years))) NA else min(years, na.rm = TRUE)
    data.frame(program = program$name, first_year = first_year, ok = ok,
               kind = c("Required", "Choose from a list", "Electives"),
               credits = vapply(c("Required", "Choose from a list", "Electives"),
                                function(k) sum(d$credits[d$kind == k]), numeric(1)))
  })
  do.call(rbind, rows)
}

plot_program_comparison <- function(g, file) {
  all <- program_shares(g)
  df <- all[all$ok, ]
  df$program <- ifelse(df$first_year > 1, sprintf("%s (from year %d)", df$program, df$first_year),
                       df$program)
  df$share <- 100 * df$credits / ave(df$credits, df$program, FUN = sum)
  fixed <- tapply(df$share[df$kind != "Electives"], df$program[df$kind != "Electives"], sum)
  df$program <- factor(df$program, names(sort(fixed)))
  df$kind <- factor(df$kind, c("Electives", "Choose from a list", "Required"))
  p <- ggplot(df, aes(share, program, fill = kind)) +
    geom_col(width = 0.7, colour = "#fcfcfb", linewidth = 0.4) +
    geom_text(data = data.frame(program = names(fixed), share = as.numeric(fixed)),
              aes(x = 101, y = program, label = sprintf("%.0f%%", share)), inherit.aes = FALSE,
              hjust = 0, size = 3.2, colour = INK) +
    scale_fill_manual(values = c(Required = PALETTE[1], `Choose from a list` = PALETTE[2],
                                 Electives = "#d9d8d3"),
                      breaks = c("Required", "Choose from a list", "Electives"), name = NULL) +
    scale_x_continuous(limits = c(0, 108), breaks = seq(0, 100, 25),
                       labels = function(x) paste0(x, "%"), expand = c(0, 0)) +
    labs(title = "How much of each degree is fixed",
         subtitle = sprintf("Share of credits; the %d of %d programs with complete requirement tables",
                            length(unique(df$program)), length(unique(all$program))),
         x = NULL, y = NULL) +
    theme_net() +
    theme(panel.grid.major.y = element_blank(), legend.position = "top",
          legend.justification = "left")
  ggsave(file, p, width = 8.5, height = 2 + 0.32 * length(unique(df$program)), dpi = 200)
}

# Fail each required course once at its planned term (its earliest start, but not before
# the year the program lists it in) and retake it at the next offering; everything else
# still starts as early as prerequisites allow. Graduation is delayed if any required
# course is pushed past the latest start that still finishes the degree on time.
# "COSC_O 210", "COSC_O 211", "MATH_O 221" -> "COSC 210, 211, MATH 221"
course_list <- function(codes) {
  subject <- sub("_O .*", "", codes)
  number <- sub(".* ", "", codes)
  paste(ifelse(c(TRUE, subject[-1] != subject[-length(subject)]),
               paste(subject, number), number), collapse = ", ")
}

program_failure_impact <- function(ix, program) {
  v <- V(program$graph)
  required <- intersect(v$name[v$role == "required"], V(ix$graph)$name)
  earliest <- ix$earliest
  latest <- latest_terms(ix, program, required, plan = FALSE)
  duration <- ix$duration
  listed_year <- setNames(v$program_year_min, v$name)
  do.call(rbind, lapply(required, function(course) {
    planned <- max(earliest[[course]], if (is.na(listed_year[[course]])) 1 else 2 * listed_year[[course]] - 1)
    planned <- offered_term(ix, course, planned)
    after <- earliest_terms(ix, setNames(planned + duration[[course]], course))
    pushed <- setdiff(required[after[required] > earliest[required]], course)
    data.frame(course = course, planned = planned, pushed_back = length(pushed),
               pushed = course_list(pushed),
               delay = max(0, after[required] - latest[required]))
  }))
}

plot_program_failure_impact <- function(ix, program, file) {
  df <- program_failure_impact(ix, program)
  if (!is.null(df)) df <- df[df$pushed_back > 0 | df$delay > 0, ]
  title <- sprintf("%s: if you fail a required course", program$name)
  if (is.null(df) || !nrow(df)) {
    p <- ggplot() + annotate("text", x = 0, y = 0, label = "No required course holds up another",
                             colour = MUTED) + labs(title = title) + theme_void()
    return(ggsave(file, p, width = 7, height = 2, dpi = 200))
  }
  df <- df[order(-df$delay, -df$pushed_back, df$planned), ]
  df$row <- factor(sprintf("%s (%s)", sub("_O ", " ", df$course), term_label(df$planned)),
                   rev(sprintf("%s (%s)", sub("_O ", " ", df$course), term_label(df$planned))))
  df$effect <- ifelse(df$delay > 0, "Delays graduation", "No delay")
  df$note <- paste0(ifelse(df$delay > 0, sprintf("+%d term%s", df$delay, ifelse(df$delay > 1, "s", "")),
                           "no delay"),
                    ifelse(df$pushed_back > 0, paste0("  ·  pushes back ", df$pushed), ""))
  p <- ggplot(df, aes(pushed_back, row, fill = effect)) +
    geom_col(width = 0.6) +
    geom_point(data = df[df$pushed_back == 0, ], aes(colour = effect), size = 3, show.legend = FALSE) +
    geom_text(aes(x = pushed_back + 0.2, label = note), hjust = 0, size = 3, colour = INK) +
    scale_colour_manual(values = c(`Delays graduation` = PALETTE[2], `No delay` = PALETTE[1])) +
    scale_fill_manual(values = c(`Delays graduation` = PALETTE[2], `No delay` = PALETTE[1]),
                      name = NULL) +
    scale_x_continuous(limits = c(-0.3, max(df$pushed_back) * 2.2 + 3), expand = c(0, 0),
                       breaks = function(x) seq(0, max(df$pushed_back), by = 1)) +
    labs(title = title,
         subtitle = "Failing once in the planned term (shown) and retaking it at the next chance",
         x = "Required courses pushed back", y = NULL) +
    theme_net() +
    theme(panel.grid.major.y = element_blank(), legend.position = "top",
          legend.justification = "left")
  ggsave(file, p, width = 9, height = 2.2 + 0.4 * nrow(df), dpi = 200)
}

program_figures <- function(g, program_name, dir = "figures/programs", ix = prereq_index()) {
  program <- load_program(program_name, g)
  folder <- file.path(dir, gsub("^-|-$", "", gsub("[^a-z0-9]+", "-", tolower(program$name))))
  dir.create(folder, showWarnings = FALSE, recursive = TRUE)
  plot_credits_by_year(program, file.path(folder, "credits_by_year.png"))
  plot_slack(ix, program, file.path(folder, "slack.png"))
  plot_hidden_prerequisites(ix, program, file.path(folder, "hidden_prerequisites.png"))
  plot_program_failure_impact(ix, program, file.path(folder, "failure_impact.png"))
}

subject_figures <- function(g, subject, target = NULL, dir = "figures/subjects") {
  focus <- focus_subgraph(g, subject)
  linked <- delete_vertices(focus, degree(focus) == 0)
  if (is.null(target)) target <- tail(longest_path(focus), 1)
  prefix <- file.path(dir, tolower(subject), "")
  dir.create(prefix, showWarnings = FALSE, recursive = TRUE)
  palette <- subject_palette(linked, first = subject)
  merged <- merge_equivalent(linked, degree(linked, mode = "out"))
  plot_network(merged$graph, merged$values,
               sprintf("%s prerequisite network, node size = out-degree", subject),
               paste0(prefix, "gateways.png"), palette = palette)
  plot_chain(g, target, paste0(prefix, "chain.png"), palette)
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
  plot_program_comparison(g, "figures/program_comparison.png")
  for (subject in subjects) subject_figures(g, subject)
  ix <- if (length(programs)) prereq_index()
  for (program in programs) program_figures(g, program, ix = ix)
  cat("Wrote", length(list.files("figures", recursive = TRUE)), "files to figures/\n")
}
