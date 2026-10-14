"""Extract user-authorized regression examples without modifying the supplied Word file."""
import hashlib
import json
from pathlib import Path
from transcomic.docx_document import import_docx
from transcomic.prompts import messages


def main():
    source = Path(r"D:\word 50 cach\7-8.docx")
    document = import_docx(source)
    cases = []
    categories = {5: "internal narration", 24: "feeding action", 25: "short contextual dialogue", 26: "context after feeding",
                  30: "long clauses / formatting failure", 38: "speaker relations", 48: "Hugo / dialogue", 72: "Jacqueline / reproach",
                  74: "Damian / sensitive family address", 96: "question without literal question mark", 94: "names / long narration"}
    for index, category in categories.items():
        line = {"id": f"fixture-{index+1}", "source": document.units[index].text,
                "context": [{"id": f"fixture-{n+1}", "source": document.units[n].text} for n in range(max(0, index-4), min(len(document.units), index+5)) if n != index]}
        cases.append({"ordinal": index, "category": category, "locator": document.units[index].locator, "line": line,
                      "reference_options": ["Say ah", "Open wide"] if index == 25 else []})
    result = {"source_sha256": hashlib.sha256(document.raw).hexdigest(), "unit_count": len(document.units), "cases": cases,
              "synthetic_cases": [{"source": "Dr. Cael trả 3.5 USD tại https://example.com/a.b", "translation": "Dr. Cael pays 3.5 USD at https://example.com/a.b"},
                                  {"source": "xin chào, {name}", "translation": "hello, {name}"}]}
    folder = Path("tests/fixtures")
    folder.mkdir(exist_ok=True)
    (folder / "review_7_8.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    report = []
    for case in cases:
        old = messages([case["line"]], "Tiếng Việt", "Tiếng Anh", "legacy-v1")
        new = messages([case["line"]], "Tiếng Việt", "Tiếng Anh")
        report.append({"line_number": case["ordinal"]+1, "legacy_chars": sum(len(m["content"]) for m in old),
                       "new_chars": sum(len(m["content"]) for m in new), "reference_lines": len(case["line"]["context"])})
    Path("artifacts").mkdir(exist_ok=True)
    Path("artifacts/prompt_comparison.json").write_text(json.dumps({"evaluation": "offline structure only; no semantic/API claim", "cases": report}, indent=2), encoding="utf-8")
    print(f"Extracted {len(cases)} cases from {len(document.units)} units; original unchanged")


if __name__ == "__main__":
    main()
