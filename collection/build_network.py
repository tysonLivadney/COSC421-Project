"""Build the prerequisite network (nodes.csv, edges.csv) from parsed Calendar courses."""

from __future__ import annotations

import argparse
import csv
import itertools
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COURSES = (
    PROJECT_ROOT / "data/processed/academic_calendar/course_descriptions/courses.csv"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "data/processed/network"

# A bare number ("MATH_O 100, 101") continues the previous subject's list.
COURSE_REF = re.compile(r"\b(?:([A-Z]{3,4})(?:_O)?\s+)?(\d{3}[A-Z]?)\b(?![-\d%])")
# Sentences that mention courses without requiring them.
ADVICE = re.compile(
    r"recommended|preferred|should|strongly|credit will be granted|next level",
    re.IGNORECASE,
)
ALT_LABEL = re.compile(r"(?:\bor\s+|;\s*or\s+|\s)\([b-z]\)\s*", re.IGNORECASE)
CONNECTORS = re.compile(
    r"\b(?:either|one of|all of|two of|and|or)\b|\([a-z]\)|[.,;]", re.IGNORECASE
)
MAX_CLAUSES = 64


def courses_in(text: str) -> list[str]:
    found, subject = [], None
    for match in COURSE_REF.finditer(text):
        subject = match.group(1) or subject
        if subject:
            found.append(f"{subject}_O {match.group(2)}")
    return found


def parse(text: str):
    """Requirement text -> ("and"|"or", [children]) tree; non-course parts become None."""
    text = text.strip(" .;,")
    if not text:
        return None
    sentences = [s for s in re.split(r"\.(?=\s|$)", text) if not ADVICE.search(s)]
    if len(sentences) > 1:
        return node("and", sentences)
    text = sentences[0] if sentences else ""
    if re.search(r";\s*or\b", text):
        return node("or", re.split(r";\s*or\b", text))
    if ";" in text:
        return node("and", text.split(";"))
    either = re.search(r"\beither\b", text, re.IGNORECASE)
    if either and either.start() > 0:
        prefix = re.sub(r"\band\s*$", "", text[: either.start()].strip())
        return node("and", [prefix, text[either.start():]])
    if either:
        body = re.sub(r"^either\s*(\(a\))?", "", text, flags=re.IGNORECASE)
        return node("or", ALT_LABEL.split(body))
    if re.search(r"\band\b", text):
        return node("and", re.split(r"\band\b", text))
    codes = courses_in(text)
    if not codes:
        return None
    is_all_of = re.search(r"\ball of\b", text, re.IGNORECASE)
    is_list = re.search(r"\b(one|two) of\b|\bor\b", text, re.IGNORECASE)
    op = "or" if is_list and not is_all_of else "and"
    return (op, codes) if len(codes) > 1 else codes[0]


def node(op: str, parts: list[str]):
    children = [c for c in map(parse, parts) if c is not None]
    if not children:
        return None
    return (op, children) if len(children) > 1 else children[0]


def to_cnf(tree) -> list[frozenset[str]]:
    """Tree -> OR-clauses that must all hold, with absorbed clauses removed."""
    if tree is None:
        return []
    if isinstance(tree, str):
        return [frozenset([tree])]
    op, children = tree
    child_cnfs = [to_cnf(c) for c in children]
    if op == "and":
        clauses = [cl for cnf in child_cnfs for cl in cnf]
    else:  # (A and B) or C  ==  (A or C) and (B or C)
        clauses = [frozenset().union(*combo) for combo in itertools.product(*child_cnfs)]
        if len(clauses) > MAX_CLAUSES:
            raise ValueError(f"CNF blew up ({len(clauses)} clauses)")
    unique = set(clauses)
    return sorted(
        (c for c in unique if not any(o < c for o in unique)),
        key=lambda c: sorted(c),
    )


def unparsed(text: str) -> str:
    leftover = CONNECTORS.sub(" ", COURSE_REF.sub(" ", text))
    return " ".join(leftover.split())


def build(courses: list[dict[str, str]]) -> tuple[list[dict], list[dict]]:
    edges, notes, group_id = [], {}, 0
    for course in courses:
        target = course["course_code"]
        leftovers = []
        for kind, column in (("prereq", "prerequisite_text"), ("coreq", "corequisite_text")):
            text = course.get(column) or ""
            if not text:
                continue
            for clause in to_cnf(parse(text)):
                clause = clause - {target}
                if not clause:
                    continue
                group_id += 1
                edges.extend(
                    {"from": src, "to": target, "type": kind, "group_id": group_id}
                    for src in sorted(clause)
                )
            if rest := unparsed(text):
                leftovers.append(f"{kind}: {rest}")
        notes[target] = " | ".join(leftovers)

    nodes = {
        c["course_code"]: {
            "course_code": c["course_code"],
            "subject_code": c["subject_code"],
            "course_number": c["course_number"],
            "year_level": int(c["course_number"][0]),
            "credits": c["credits"],
            "title": c["title"],
            "in_calendar": True,
            "unparsed_text": notes.get(c["course_code"], ""),
        }
        for c in courses
    }
    for edge in edges:
        code = edge["from"]
        if code not in nodes:
            subject, number = code.split()
            nodes[code] = {
                "course_code": code, "subject_code": subject, "course_number": number,
                "year_level": int(number[0]), "credits": "", "title": "",
                "in_calendar": False, "unparsed_text": "",
            }
    return list(nodes.values()), edges


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--courses", type=Path, default=DEFAULT_COURSES)
    parser.add_argument("--output-directory", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    with args.courses.open(encoding="utf-8", newline="") as handle:
        nodes, edges = build(list(csv.DictReader(handle)))
    write_csv(args.output_directory / "nodes.csv", nodes)
    write_csv(args.output_directory / "edges.csv", edges)
    print(f"Wrote {len(nodes)} nodes and {len(edges)} edges to {args.output_directory}")


if __name__ == "__main__":
    main()
