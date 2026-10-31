from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

from app.score_ceos import DIMENSIONS, read_ceos


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TRAITS = {"亲和性": "agreeableness", "外向性": "extraversion", "尽责性": "conscientiousness",
          "神经质": "neuroticism", "经验开放性": "openness"}
IDENTITY_COLUMNS = ["CEO编号", "CEO姓名", "公司", "模型", "人格维度"]
SCORE_COLUMNS = [f"评分{i:03d}" for i in range(1, 101)]
SCORE_PATTERN = re.compile(r"(?:[1-6]\.[0-9]{2}|7\.00)")


def validate_data(data_dir=DATA_DIR, archive_dir=None):
    data_dir = Path(data_dir)
    archive_dir = Path(archive_dir) if archive_dir is not None else data_dir.parent / "archived_ratings"
    manifest = json.loads((archive_dir / "manifest.json").read_text(encoding="utf-8"))
    paths = {"sp500_ceos.csv": data_dir / "sp500_ceos.csv",
             "ChatGPT.csv": archive_dir / "ChatGPT.csv", "DeepSeek.csv": archive_dir / "DeepSeek.csv"}
    for name, path in paths.items():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != manifest["files"][name]["sha256"]:
            raise ValueError(f"File checksum differs from the published dataset: {name}")
    people = read_ceos(data_dir / "sp500_ceos.csv")
    if len(people) != 500:
        raise ValueError("The study input must contain 500 unique CEOs")
    by_id = {person["ceo_id"]: person for person in people}
    for correction in manifest["company_metadata_corrections"]:
        person = by_id.get(correction["ceo_id"])
        if person is None or (person["name"], person["company"]) != (correction["name"], correction["published_company_value"]):
            raise ValueError("Documented company metadata does not match the input list")
    report = {"people": len(people), "models": {}, "total_valid_scores": 0}
    for model in ("ChatGPT", "DeepSeek"):
        path = archive_dir / f"{model}.csv"
        slots = set()
        dimensions = Counter()
        valid_scores = 0
        rating_values = []
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if reader.fieldnames != IDENTITY_COLUMNS + SCORE_COLUMNS:
                raise ValueError(f"Unexpected columns or score-column order in {path.name}")
            for line, row in enumerate(reader, 2):
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"Incorrect field count in {path.name}, row {line}")
                identifier = row["CEO编号"]
                person = by_id.get(identifier)
                dimension = TRAITS.get(row["人格维度"])
                if person is None or dimension is None or row["模型"] != model:
                    raise ValueError(f"Unknown CEO, trait or model in {path.name}, row {line}")
                slot = (identifier, dimension)
                if slot in slots:
                    raise ValueError(f"Duplicate CEO/trait row in {path.name}, row {line}")
                slots.add(slot)
                dimensions[dimension] += 1
                if row["CEO姓名"] != person["name"]:
                    raise ValueError(f"CEO name differs from the input list in {path.name}, row {line}")
                if row["公司"] != person["company"]:
                    raise ValueError(f"Company differs from the input list in {path.name}, row {line}")
                for column in SCORE_COLUMNS:
                    if not SCORE_PATTERN.fullmatch(row[column]):
                        raise ValueError(f"Missing or invalid score in {path.name}, row {line}, {column}")
                    valid_scores += 1
                rating_values.append(",".join(row[column] for column in SCORE_COLUMNS))
        expected = {(identifier, dimension) for identifier in by_id for dimension in DIMENSIONS}
        if slots != expected or valid_scores != 250000:
            raise ValueError(f"Incomplete CEO/trait coverage in {path.name}")
        rating_digest = hashlib.sha256("\n".join(rating_values).encode("utf-8")).hexdigest()
        if rating_digest != manifest["files"][path.name]["rating_values_sha256"]:
            raise ValueError(f"Rating values differ from the original scores in {path.name}")
        report["models"][model] = {"rows": len(slots), "people": len(people),
                                    "traits": dict(sorted(dimensions.items())), "scores_per_row": 100,
                                    "valid_scores": valid_scores, "invalid_scores": 0,
                                    "duplicate_rows": 0, "missing_company_rows": 0}
        report["total_valid_scores"] += valid_scores
    if report["models"] != manifest["validation"]["models"]:
        raise ValueError("Computed validation does not match the published report")
    return report


def main():
    parser = argparse.ArgumentParser(description="Validate the published study data without API requests")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--archive-dir", type=Path)
    args = parser.parse_args()
    try:
        report = validate_data(args.data_dir, args.archive_dir)
    except (OSError, ValueError, KeyError, csv.Error) as exc:
        print(f"Data validation failed: {exc}", file=sys.stderr)
        return 2
    print(f"Input: {report['people']} CEOs")
    for model, values in report["models"].items():
        print(f"{model}: {values['rows']} CEO/trait rows; {values['valid_scores']:,} valid scores")
        print(f"  Missing company fields: {values['missing_company_rows']}")
    print(f"Checksums, identities, coverage and score format verified: {report['total_valid_scores']:,} scores. No API calls made.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
