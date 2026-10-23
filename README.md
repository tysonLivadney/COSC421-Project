# COSC 421 Course-Prerequisite Network

This repository contains the data-collection and R analysis pipeline for the
UBC Okanagan course-prerequisite network project.

The pipeline keeps collection separate from analysis:

- `collection/` contains configurable, deterministic data-collection and
  conversion tools.
- `data/raw/` stores unchanged source responses.
- `data/processed/` stores tabular data generated from the raw responses.
- Network construction and analysis will be performed in R in a later stage.

Start with [collection/README.md](collection/README.md) for the current data
conversion workflow.
