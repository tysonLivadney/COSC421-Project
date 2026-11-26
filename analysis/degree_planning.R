
source("analysis/viz.R")

PLANNING_DIR <- "figures/planning"

label_course <- function(codes) sub("_O ", " ", codes)

planning_programs <- function(g, shares = program_shares(g)) {
  programs <- read.csv(file.path(PROGRAM_DIR, "programs.csv"), colClasses = "character")
  reqs <- read.csv(file.path(PROGRAM_DIR, "requirements.csv"), colClasses = "character")
  complete <- unique(shares$program[shares$ok])
  ids <- programs$program_id[programs$name %in% complete]
  lapply(ids, function(id) {
    sections <- reqs$section[reqs$program_id == id & reqs$source_type == "table"]
    load_program(id, g, track = default_track(sections))
  })
}

program_course_table <- function(ix, program) {
  v <- V(program$graph)
  required <- intersect(v$name[v$role == "required"], V(ix$graph)$name)
  if (!length(required)) return(NULL)
  earliest <- ix$earliest[required]
  latest <- latest_terms(ix, program, required)
  failure <- program_failure_impact(ix, program)
  offered <- ix$offered[required, , drop = FALSE]
  data.frame(
    program = program$name,
    course = required,
    earliest = earliest,
    latest_plan = latest,
    no_slack = latest <= earliest,
    one_term_only = ix$duration[required] == 1 & rowSums(offered) == 1,
    offered_in = ifelse(ix$duration[required] == 2, "Full year, Sep-Apr",
                        ifelse(rowSums(offered) == 2, "Both terms",
                               ifelse(offered[, "T1"], "Term 1 only", "Term 2 only"))),
    pushed_back = failure$pushed_back[match(required, failure$course)],
    delay_terms = failure$delay[match(required, failure$course)],
    row.names = NULL
  )
}

program_summary <- function(ix, programs, courses, shares) {
  rows <- lapply(programs, function(p) {
    d <- courses[courses$program == p$name, ]
    hidden <- hidden_prerequisites(ix, p)
    s <- shares[shares$program == p$name, ]
    fixed_share <- 100 * sum(s$credits[s$kind != "Electives"]) / sum(s$credits)
    data.frame(
      program = p$name,
      first_year = s$first_year[1],
      required_courses = nrow(d),
      no_slack = sum(d$no_slack),
      delay_if_failed = sum(d$delay_terms > 0),
      one_term_only = sum(d$one_term_only),
      courses_with_hidden_prereqs = if (is.null(hidden)) 0 else length(unique(hidden$course)),
      fixed_credit_share = round(fixed_share, 1)
    )
  })
  df <- do.call(rbind, rows)
  df[order(-df$delay_if_failed, -df$no_slack), ]
}

bottleneck_summary <- function(courses) {
  by_course <- split(courses, courses$course)
  df <- do.call(rbind, lapply(by_course, function(d) data.frame(
    course = label_course(d$course[1]),
    required_in = nrow(d),
    no_slack_in = sum(d$no_slack),
    delays_graduation_in = sum(d$delay_terms > 0),
    one_term_only = d$one_term_only[1],
    max_courses_pushed_back = max(d$pushed_back)
  )))
  df <- df[order(-df$delays_graduation_in, -df$no_slack_in, -df$required_in), ]
  rownames(df) <- NULL
  df
}

DELAY_COLOUR <- "#c4461a"

plot_bottlenecks <- function(courses, file) {
  delaying <- unique(courses$course[courses$delay_terms > 0])
  df <- courses[courses$course %in% delaying, ]
  df$effect <- ifelse(df$delay_terms > 0, "Failing it delays graduation by a year",
                      "Failing it can be caught up")
  programs <- names(sort(tapply(df$delay_terms > 0, df$program, sum), decreasing = TRUE))
  rank <- aggregate(cbind(delays = delay_terms > 0, required = 1) ~ course, df, sum)
  rank <- rank[order(-rank$delays, -rank$required, rank$course), ]
  df$x <- match(df$program, programs)
  df$y <- factor(label_course(df$course), rev(label_course(rank$course)))
  offered <- unique(df[, c("y", "offered_in")])
  columns <- vapply(programs, function(p) paste(strwrap(p, 14), collapse = "\n"), character(1))
  p <- ggplot(df, aes(x, y, fill = effect)) +
    geom_tile(width = 0.86, height = 0.8) +
    geom_text(data = offered, aes(x = length(programs) + 0.65, y = y, label = offered_in),
              inherit.aes = FALSE, hjust = 0, size = 3.2, colour = MUTED) +
    scale_fill_manual(values = c(`Failing it delays graduation by a year` = DELAY_COLOUR,
                                 `Failing it can be caught up` = "#d9d8d3"),
                      breaks = c("Failing it delays graduation by a year", "Failing it can be caught up"),
                      name = NULL) +
    scale_x_continuous(breaks = seq_along(programs), labels = columns, position = "top",
                       limits = c(0.5, length(programs) + 2.3), expand = c(0, 0)) +
    labs(title = "Required courses that delay graduation if failed",
         subtitle = paste("Each square is a program that requires the course to graduate;",
                          "right: when the course runs"),
         x = NULL, y = NULL) +
    theme_net() +
    theme(panel.grid.major = element_blank(), axis.text.x.top = element_text(size = 8.5, lineheight = 0.9),
          legend.position = "bottom", legend.justification = "left")
  ggsave(file, p, width = 9, height = 2.6 + 0.32 * length(delaying), dpi = 200)
}

plot_program_fragility <- function(summary, file) {
  df <- summary
  df$label <- ifelse(df$first_year > 1, sprintf("%s (from year %d)", df$program, df$first_year), df$program)
  df$label <- factor(df$label, df$label[order(df$delay_if_failed, -rank(df$program))])
  df$note <- sprintf("%d of %d required courses", df$delay_if_failed, df$required_courses)
  top <- max(df$delay_if_failed)
  p <- ggplot(df, aes(delay_if_failed, label)) +
    geom_col(fill = DELAY_COLOUR, width = 0.7) +
    geom_text(aes(x = delay_if_failed + top * 0.02, label = note),
              hjust = 0, size = 3.2, colour = INK) +
    scale_x_continuous(limits = c(0, top * 1.45), breaks = seq(0, top, 2), expand = c(0, 0)) +
    labs(title = "Programs where failing a required course delays graduation",
         subtitle = "Required courses that push graduation back a year if failed once in their planned term",
         x = NULL, y = NULL) +
    theme_net() +
    theme(panel.grid.major.y = element_blank())
  ggsave(file, p, width = 9, height = 2 + 0.36 * nrow(df), dpi = 200)
}

if (sys.nframe() == 0) {
  dir.create(PLANNING_DIR, showWarnings = FALSE, recursive = TRUE)
  g <- load_network()
  ix <- prereq_index()
  shares <- program_shares(g)
  programs <- planning_programs(g, shares)
  courses <- do.call(rbind, lapply(programs, function(p) program_course_table(ix, p)))
  summary <- program_summary(ix, programs, courses, shares)
  bottlenecks <- bottleneck_summary(courses)

  write.csv(courses, file.path(PLANNING_DIR, "required_courses.csv"), row.names = FALSE)
  write.csv(summary, file.path(PLANNING_DIR, "program_summary.csv"), row.names = FALSE)
  write.csv(bottlenecks, file.path(PLANNING_DIR, "bottleneck_courses.csv"), row.names = FALSE)
  plot_bottlenecks(courses, file.path(PLANNING_DIR, "bottleneck_courses.png"))
  plot_program_fragility(summary, file.path(PLANNING_DIR, "program_fragility.png"))
  cat(length(programs), "programs,", nrow(courses), "required course slots\n")
}
