import unittest

from collection.build_network import build, parse, to_cnf


def groups(text: str) -> list[set[str]]:
    return [set(clause) for clause in to_cnf(parse(text))]


class RequirementParsingTests(unittest.TestCase):
    def test_one_of_and_all_of(self) -> None:
        self.assertEqual(
            groups("All of COSC 221, COSC 222 and one of MATH 221, APSC 179."),
            [{"APSC_O 179", "MATH_O 221"}, {"COSC_O 221"}, {"COSC_O 222"}],
        )

    def test_either_after_prefix_and_bare_numbers(self) -> None:
        self.assertEqual(
            groups("All of MATH 200, MATH 221 and either (a) COSC 111 or (b) DATA 301."),
            [{"COSC_O 111", "DATA_O 301"}, {"MATH_O 200"}, {"MATH_O 221"}],
        )
        self.assertEqual(
            groups("one of MATH_O 100, 101; or CHEM_O 113 or 123"),
            [{"MATH_O 100", "MATH_O 101", "CHEM_O 113", "CHEM_O 123"}],
        )

    def test_either_distributes_to_cnf(self) -> None:
        self.assertEqual(
            groups("Either (a) BIOL 125 or (b) all of BIOL 117, BIOL 122."),
            [{"BIOL_O 117", "BIOL_O 125"}, {"BIOL_O 122", "BIOL_O 125"}],
        )

    def test_non_course_and_advice_dropped(self) -> None:
        self.assertEqual(
            groups(
                "A score more than 60% in COSC 222 and a score more than 60% in "
                "one of PHYS 121, PHYS 122. PHYS 121 preferred."
            ),
            [{"COSC_O 222"}, {"PHYS_O 121", "PHYS_O 122"}],
        )
        self.assertEqual(groups("3 credits of 300-level ENGL. Third-year standing."), [])
        self.assertEqual(groups("3 credits from POLI 310-329."), [])


class BuildTests(unittest.TestCase):
    def test_edges_groups_and_external_nodes(self) -> None:
        course = {
            "course_code": "COSC_O 222", "subject_code": "COSC_O", "course_number": "222",
            "credits": "3", "title": "Data Structures",
            "prerequisite_text": "One of COSC 121, COSC 999. Third-year standing.",
            "corequisite_text": "",
        }
        nodes, edges = build([course])
        self.assertEqual(
            [(e["from"], e["type"], e["group_id"]) for e in edges],
            [("COSC_O 121", "prereq", 1), ("COSC_O 999", "prereq", 1)],
        )
        by_code = {n["course_code"]: n for n in nodes}
        self.assertFalse(by_code["COSC_O 121"]["in_calendar"])
        self.assertIn("Third-year standing", by_code["COSC_O 222"]["unparsed_text"])


if __name__ == "__main__":
    unittest.main()
