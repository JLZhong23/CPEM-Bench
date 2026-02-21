import re
import json
from collections import defaultdict

emr_data = './data/emr/raw/emr_data.json'
disease_list = './data/emr/raw/disease_list.txt'
pattern = r'\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\s(?:[01]\d|2[0-3]):[0-5]\d'

def generate_disease_list(emr_data_path=emr_data, disease_list_path=disease_list):
    with open(emr_data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    disease_set = set()
    for item in data:
        for disease in item['disease']:
            disease_set.add(disease)
    disease_list = list(disease_set)
    with open(disease_list_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(sorted(disease_list)))

def get_sub_k_statistics(k=200, emr_data_path=emr_data):
    # 选择不超过 k 字的病历记录，并统计不同科室和场景的数量
    department_counts = defaultdict(int)
    scenario_counts = defaultdict(int)
    daily_flag_counts = defaultdict(int)    # 统计选用的记录中，每个患者出现的次数
    filtered_records = []

    with open(emr_data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    for item in data:
        if '表格<会诊表格>内容:会诊意见:会诊时间: 年 月 日时分' in item['description']:
                item['description'] = item['description'].replace('表格<会诊表格>内容:会诊意见:会诊时间: 年 月 日时分', '')
        if '表格<会诊表格>内容:会诊意见:' in item['description']:
            item['description'] = item['description'].replace('表格<会诊表格>内容:会诊意见:', '')
        if '会诊医师职称 会诊意见:会诊时间:' in item['description']:
            item['description'] = item['description'].replace('会诊医师职称 会诊意见:会诊时间:', '')
        if '主诉，继续当前治疗，密观患者病情变化。' in item['description']:
            item['description'] = item['description'].replace('主诉，继续当前治疗，密观患者病情变化。', '')
        if '主诉，考虑暂时观察。密观。' in item['description']:
            item['description'] = item['description'].replace('主诉，考虑暂时观察。密观。', '')
        if '主诉，嘱其伤口三日勿沾水。' in item['description']:
            item['description'] = item['description'].replace('主诉，嘱其伤口三日勿沾水。', '')
        matches = re.findall(pattern, item['description'])
        if matches and item['description'].startswith(matches[0]):
            item['description'] = item['description'][len(matches[0])].lstrip()

        if 10 <= len(item['description']) <= k:
            # 每个患者只取一次日常病程记录
            if item['scenario'] == 'emr-日常病程记录' and daily_flag_counts[item['patient_id']] >= 1:
                continue
            if '拆线前伤口勿沾水。' in item['description']:
                continue
            department_counts[item['department']] += 1
            scenario_counts[item['scenario']] += 1
            daily_flag_counts[item['patient_id']] += 1
            filtered_records.append(item)

    print("统计描述长度不超过 {} 字的病历记录数量：".format(k))
    print("Department counts:", dict(department_counts))
    print("Scenario counts:", dict(scenario_counts))
    return filtered_records

if __name__ == "__main__":
    # generate_disease_list()
    filtered_records = get_sub_k_statistics(k=200)
    print(filtered_records[:2])
