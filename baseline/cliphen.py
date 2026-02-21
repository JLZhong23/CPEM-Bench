import json
import pandas as pd
from clinphen_src.get_phenotypes import extract_phenotypes

def load_hpo_english_names():
    name_file = 'miniconda3/Lib/site-packages/clinphen_src/data/hpo_term_names.txt'
    hpo_names = {}
    with open(name_file, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) >= 2:
                hpo_names[parts[0]] = parts[1]
    return hpo_names

def load_chpo_translations():
    chpo_file = r"CHPO第七次更新词表-2025-4.xlsx"
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
    
    for line in lines[1:]:
        if line.strip():
            parts = line.split('\t')
            if len(parts) >= 2 and parts[0].startswith('HP:'):
                hpo_id = parts[0]
                chinese_name = chpo_dict.get(hpo_id, None)

                if chinese_name and chinese_name != "未找到中文翻译":
                    chinese_list.append(chinese_name)
    
    return chinese_list

hpo_names = load_hpo_english_names()
chpo_dict = load_chpo_translations()

with open('input', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 遍历所有数据
for i, entry in enumerate(data):
    description = entry.get("description", "")
    results = extract_phenotypes(description, hpo_names)
    chinese_phenotypes = extract_and_translate(results, chpo_dict)
    entry["clinphen"] = chinese_phenotypes
        

output_file = 'output.json'
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
