from utils import get_trans
import json
from tqdm import tqdm

source_file = './data/bio_reports/processed/patient_specific_gemini_predict.json'
target_file = './data/bio_reports/processed/patient_specific_gemini_predict_eng.json'

translator = get_trans()

with open(source_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

for sample in tqdm(data):
    en_text = translator.call_url(sample['description'])
    sample['translate'] = en_text
    with open(target_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)