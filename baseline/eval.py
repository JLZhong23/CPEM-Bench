import json
import argparse
from pathlib import Path
from collections import defaultdict


METHODS = ["bert", "tagger", "fasthpocr", "pbtagger", "real", "rag_hpo", "base"]

POSITIVE_KEYS = ["patient_phenotypes", "family_phenotypes"]
ALL_KEYS = ["patient_phenotypes", "family_phenotypes",
            "patient_phenotypes_neg", "family_phenotypes_neg"]


def get_ground_truth(item: dict, positive_only: bool = False) -> set:
    """Collect HPO IDs from human annotations."""
    ha = item.get("human_annotated", {})
    gt = set()
    keys = POSITIVE_KEYS if positive_only else ALL_KEYS
    for key in keys:
        gt.update(ha.get(key, []))
    return gt


def get_predictions(item: dict, method: str) -> set:
    raw = item.get(method, [])
    if method == "base":
        return {entry[1] for entry in raw if isinstance(entry, list) and len(entry) >= 2}
    return set(raw)


def compute_metrics(data: list[dict], method: str, positive_only: bool = False) -> dict:

    precisions, recalls = [], []

    for item in data:
        gt = get_ground_truth(item, positive_only)
        pred = get_predictions(item, method)

        if not gt and not pred:
            p, r = 1.0, 1.0
        elif not gt and pred:
            p, r = 0.0, 0.0
        elif gt and not pred:
            p, r = 0.0, 0.0
        else:
            tp = len(gt & pred)
            p = tp / len(pred)
            r = tp / len(gt)

        precisions.append(p)
        recalls.append(r)

    n = len(precisions)
    if n == 0:
        return {"precision": 0, "recall": 0, "f1": 0, "n": 0}

    macro_p = sum(precisions) / n
    macro_r = sum(recalls) / n
    macro_f1 = 2 * macro_p * macro_r / (macro_p + macro_r) if (macro_p + macro_r) > 0 else 0.0

    return {
        "precision": macro_p,
        "recall":    macro_r,
        "f1":        macro_f1,
        "n":         n,
    }


def print_table(data: list[dict], methods: list[str], positive_only: bool = False, title: str = ""):
    if title:
        print(f"\n  {title} ({len(data)} samples)")
    print(f"  {'Method':<12} {'Precision':>9} {'Recall':>9} {'F1':>9}")
    print("  " + "-" * 45)

    results = {}
    for method in methods:
        m = compute_metrics(data, method, positive_only)
        results[method] = m
        print(f"  {method:<12} {m['precision']:>9.4f} {m['recall']:>9.4f} {m['f1']:>9.4f}")
    print("  " + "-" * 45)

    ranked = sorted(results.items(), key=lambda x: x[1]["f1"], reverse=True)
    return results


def main():
    parser = argparse.ArgumentParser(description="Evaluate PhenotypeIE methods.")
    parser.add_argument("--input", type=str, required=True, help="Path to all_data.json")
    parser.add_argument("--methods", nargs="*", default=METHODS, help="Methods to evaluate")
    parser.add_argument("--positive-only", action="store_true",
                        help="Evaluate on positive phenotypes only (patient + family), "
                             "excluding negative phenotypes")
    parser.add_argument("--by-source", action="store_true", help="Break down by data source")
    parser.add_argument("--by-department", action="store_true", help="Break down by department")
    args = parser.parse_args()

    data_path = Path(args.input)
    with open(data_path, "r", encoding="utf-8") as f:
        all_data = json.load(f)
    print(f"Loaded {len(all_data)} samples from {data_path}\n")

    mode = "Positive phenotypes only" if args.positive_only else "All phenotypes (pos + neg)"
    print(f"Evaluation mode: {mode}\n")

    print("Overall")
    print("=" * 50)
    print_table(all_data, args.methods, args.positive_only)

    # By source
    if args.by_source:
        print("By Source")
        print("=" * 50)
        source_data = defaultdict(list)
        for item in all_data:
            source_data[item.get("source", "unknown")].append(item)
        for source, items in sorted(source_data.items(), key=lambda x: -len(x[1])):
            print_table(items, args.methods, args.positive_only, title=f"Source: {source}")

    # By department
    if args.by_department:
        print("By Department")
        print("=" * 50)
        dept_data = defaultdict(list)
        for item in all_data:
            dept_data[item.get("department", "unknown")].append(item)
        for dept, items in sorted(dept_data.items(), key=lambda x: -len(x[1])):
            print_table(items, args.methods, args.positive_only, title=f"Department: {dept}")


if __name__ == "__main__":
    main()