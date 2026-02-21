import json
from prompts import *
from tqdm import tqdm
from llm_call import LLM_Call

DATA_NO_DUP = '../data/bio_reports/processed_data_no_info_processed.json'
DATA_PATIENT_SPECIFIC = '../data/bio_reports/processed/patient_specific.json'
DATA_PATIENT_SPECIFIC_LLM_ANNOTATION = '../data/bio_reports/processed/patient_specific_gemini.json'
processed_data = []

LLM = LLM_Call(
    api_pool=False, 
    use_async_api=False, 
    api_model='gemini-3-flash-preview'
)


def process_no_dup_data():
    """
    Description:
        Process the data file without duplicate samples and extract phenotype information from patients.
    """
    with open(DATA_NO_DUP, 'r', encoding='utf-8') as f:
        samples = f.readlines()
        processed_data = []
        for sample in samples:
            tmp = json.loads(sample)
            human_annotated_data = tmp['results']
            # patient phenotypes
            patient_phenotypes = get_phenotype_from_reports(human_annotated_data[0])
            # patient family's phenotypes
            family_phenotypes = []
            for i in range(1, len(human_annotated_data)):
                family_phenotypes.extend(get_phenotype_from_reports(human_annotated_data[i]))
            family_phenotypes = list(set(family_phenotypes))

            tmp.pop('results')
            tmp['human_annotated'] = {}
            tmp['human_annotated']['patient_phenotypes'] = patient_phenotypes
            tmp['human_annotated']['family_phenotypes'] = family_phenotypes
            tmp['human_annotated']['all_phenotypes'] = list(set(patient_phenotypes + family_phenotypes))
            tmp['index'] = len(processed_data)

            processed_data.append(tmp)
    with open(DATA_PATIENT_SPECIFIC, 'w', encoding='utf-8') as fw:
        # processed_data = list(map(lambda x: json.dumps(x, ensure_ascii=False), processed_data))
        # print(processed_data)
        # fw.writelines(processed_data)
        json.dump(processed_data, fw, ensure_ascii=False, indent=4)


def get_phenotype_from_reports(annotation: list):
    """
    Description:
        Extract phenotype information from human-annotated reports line.

    Args:
        annotation (list): A list of annotations from human-annotated reports, e.g., ["高血压；高甘油三酯血症；蛋白尿；糖尿病；高凝状态；高脂血症；"].

    Returns:
        list: A list of extracted phenotypes.
    """
    if not annotation:
        return []
    no_phenotype_words = ['正常无表型', '正常表型', '-']
    ann = annotation[1]
    if ann.strip() in no_phenotype_words:
        return []
    phenotypes = []
    ann = ann.replace('；', ';')
    ann = ann.replace('。', ';')
    ann = ann.replace('，', ';')
    ann = ann.replace(',', ';')
    ann = ann.replace('、', ';')
    phenotype_list = ann.split(';')
    for phenotype in phenotype_list:
        if phenotype != '':
            phenotypes.append(phenotype)
    return phenotypes

def llm_annotation(description: str) -> str:
    prompt = PROMPT_ANNOTATION.format(description=description)
    response = LLM.single_chat(0, prompt)
    return response

def sparse_response(response: str) -> str:
    pass

def annotation():
    with open(DATA_PATIENT_SPECIFIC_LLM_ANNOTATION, 'r', encoding='utf-8') as f:
        data = json.load(f)
    for item in tqdm(data):
        description = item['description']
        if 'llm_annotation' in item:
            continue
        llm_response = llm_annotation(description)
        item['llm_annotation'] = llm_response
        with open(DATA_PATIENT_SPECIFIC_LLM_ANNOTATION, 'w', encoding='utf-8') as fw:
            json.dump(data, fw, ensure_ascii=False, indent=4)

if __name__ == '__main__':
    # process_no_dup_data()
    annotation()
