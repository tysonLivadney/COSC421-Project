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
subject_colours <- function(g) {
  top <- head(names(sort(table(V(g)$subject), decreasing = TRUE)), length(PALETTE))
  group <- ifelse(V(g)$subject %in% top, V(g)$subject, "Other")
  list(group = group, colour = c(setNames(PALETTE[seq_along(top)], top), Other = OTHER))
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

plot_network <- function(g, size_by, title, file, layout = layout_with_kk(g), n_labels = 10,
                         highlight = NULL) {
  colours <- subject_colours(g)
  size <- 3 + 12 * sqrt(size_by / max(size_by, 1))
  labelled <- rank(-size_by, ties.method = "first") <= n_labels
  if (!is.null(highlight)) labelled <- V(g)$name %in% highlight
  on_path <- if (is.null(highlight)) rep(FALSE, ecount(g)) else
    E(g) %in% E(g, path = highlight)

  png(file, width = 2400, height = 1800, res = 200, bg = "#fcfcfb")
  par(mar = c(0, 0, 3, 0))
  plot(
    g, layout = layout,
    vertex.size = size,
    vertex.color = colours$colour[colours$group],
    vertex.frame.color = "#fcfcfb",
    vertex.label = ifelse(labelled, V(g)$label, NA),
    vertex.label.color = INK, vertex.label.cex = 0.7, vertex.label.dist = 1.4,
    vertex.label.family = "sans",
    edge.arrow.size = 0.25,
    edge.color = ifelse(on_path, INK, adjustcolor(MUTED, 0.35)),
    edge.width = ifelse(on_path, 2.5, 0.6),
    edge.lty = ifelse(E(g)$alternatives > 1, 2, 1),
    main = title
  )
  legend("bottomleft", legend = c(names(colours$colour), "required", "one of several"),
         pch = c(rep(21, length(colours$colour)), NA, NA), lty = c(rep(NA, length(colours$colour)), 1, 2),
         pt.bg = colours$colour, col = c(rep("#fcfcfb", length(colours$colour)), MUTED, MUTED),
         pt.cex = 1.8, bty = "n", text.col = INK)
  dev.off()
}

plot_chain <- function(g, to, file) {
  path <- longest_path(g, to)
  sub <- induced_subgraph(g, subcomponent(g, to, mode = "in"))
  layout <- layout_with_sugiyama(sub)$layout
  layout[, 2] <- -layout[, 2]
  plot_network(
    sub, size_by = rep(1, vcount(sub)), layout = layout, highlight = path,
    title = sprintf("Longest prerequisite chain to %s (%d courses), rows = prerequisite depth",
                    sub("_O ", " ", to), length(path)),
    file = file
  )
}

if (sys.nframe() == 0) {
  dir.create("figures", showWarnings = FALSE)
  g <- load_network()
  cosc <- focus_subgraph(g, "COSC")
  cosc_linked <- delete_vertices(cosc, degree(cosc) == 0)

  plot_top(g, strength(g, mode = "out", weights = 1 / E(g)$alternatives),
           "Top gateway courses",
           "Courses unlocked, weighted by 1 / size of each 'one of' group",
           "figures/gateways.png")
  plot_top(g, betweenness(g, directed = TRUE),
           "Top bridge courses", "Directed betweenness centrality, whole calendar",
           "figures/bridges.png")
  plot_degree_distribution(g, "figures/degree_distribution.png")
  plot_network(cosc_linked, degree(cosc_linked, mode = "out"),
               "COSC prerequisite network, node size = out-degree", "figures/cosc_gateways.png")
  plot_network(cosc_linked, betweenness(cosc_linked),
               "COSC prerequisite network, node size = betweenness", "figures/cosc_bridges.png")
  plot_chain(g, "COSC_O 499", "figures/cosc_499_chain.png")
  cat("Wrote", length(list.files("figures")), "files to figures/\n")
}
