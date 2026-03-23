import json
import argparse
import pandas as pd
from clinphen_src.get_phenotypes import extract_phenotypes


def load_hpo_english_names(name_file):
    hpo_names = {}
    with open(name_file, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 2:
                hpo_names[parts[0]] = parts[1]
    return hpo_names


def load_chpo_translations(chpo_file):
    df = pd.read_excel(chpo_file)
    chpo_dict = {}
    for _, row in df.iterrows():
        hpo_id = str(row['HPO编号'])
        chinese_name = str(row['中文翻译'])
        if pd.notna(hpo_id) and pd.notna(chinese_name):
            if not hpo_id.startswith('HP:'):
                hpo_id = f'HP:{hpo_id}'
            chpo_dict[hpo_id] = chinese_name
    return chpo_dict


def extract_and_translate(results, chpo_dict):
    lines = results.split('\n')
    chinese_list = []
    hpo_id_list = []

    for line in lines[1:]:
        if line.strip():
            parts = line.split('\t')
            if len(parts) >= 2 and parts[0].startswith('HP:'):
                hpo_id = parts[0]
                chinese_name = chpo_dict.get(hpo_id, None)
                if chinese_name and chinese_name != "未找到中文翻译":
                    chinese_list.append(chinese_name)
                    hpo_id_list.append(hpo_id)

    return chinese_list, hpo_id_list


def main():
    parser = argparse.ArgumentParser(description="ClinPhen phenotype extraction with CHPO translation.")
    parser.add_argument("--input", type=str, required=True, help="Path to input JSON data file")
    parser.add_argument("--output", type=str, default=None,
                        help="Path to output JSON file (default: write back to input file)")
    parser.add_argument("--hpo-names", type=str,
                        default="miniconda3/Lib/site-packages/clinphen_src/data/hpo_term_names.txt",
                        help="Path to hpo_term_names.txt")
    parser.add_argument("--chpo", type=str,
                        default="CHPO第七次更新词表-2025-4.xlsx",
                        help="Path to CHPO translation Excel file")
    args = parser.parse_args()

    output_path = args.output if args.output else args.input

    hpo_names = load_hpo_english_names(args.hpo_names)
    chpo_dict = load_chpo_translations(args.chpo)

    with open(args.input, 'r', encoding='utf-8') as f:
        data = json.load(f)

    print(f"Loaded {len(data)} samples from {args.input}")

    for i, entry in enumerate(data):
        description = entry.get("description", "")
        results = extract_phenotypes(description, hpo_names)
        chinese_phenotypes, hpo_ids = extract_and_translate(results, chpo_dict)
        entry["clinphen"] = chinese_phenotypes
        entry["clinphen_hpo"] = hpo_ids

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Results written to {output_path}")


if __name__ == "__main__":
    main()