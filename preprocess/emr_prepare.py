import re
import os
import json
import pandas as pd
import hanlp

_hanlp = hanlp.load(hanlp.pretrained.mtl.CLOSE_TOK_POS_NER_SRL_DEP_SDP_CON_ELECTRA_SMALL_ZH)


def _extract_person_names(text: str) -> set:
    """使用 HanLP NER 提取文本中的人名。"""
    if not text.strip():
        return set()
    doc = _hanlp(text, tasks='ner')
    names = set()
    for entity, tag, start, end in doc['ner/msra']:
        if tag == 'PERSON' and len(entity.strip()) >= 2:
            names.add(entity.strip())
    return names


def _remove_sensitive_info(text: str) -> str:
    """
    删除病历内容中的敏感个人信息（通用于产科、儿科、神经内科）。

    策略：
      第一步：用正则删除固定结构的敏感段落
      第二步：用 HanLP NER 识别并删除残留的人名
    """
    if not isinstance(text, str) or not text.strip():
        return ''

    # ======================== 第一步：结构化正则清洗 ========================

    # 1. 去掉 "表格<申请表格>内容:" 前缀标记（后续由姓名块模式统一处理）
    text = re.sub(r'表格<申请表格>内容:', '', text)

    # 2. 新生儿信息头部：从"姓名："到"转科时间：YYYY年MM月DD日"
    #    例: 姓名：赵XX之 性别：日龄：产日 出生日期：...转科时间：2023年07月13日
    text = re.sub(
        r'姓名[：:].+?转科时间[：:]\d{4}年\d{2}月\d{2}日',
        '', text, flags=re.DOTALL
    )

    # 3. 姓名+性别+年龄块（通用，含可选的"之子/之女/之二女"等、可选的科室+床号）
    #    例: 姓名：范xx性别：男年龄：13岁
    #        姓名：丁xx之子性别：男年龄：57分钟
    #        姓名:程xx性别:女年龄:8岁科室:儿科普通病房床号:0xx
    #        姓名：伊xx性别：女年龄：55岁
    text = re.sub(
        r'姓名[：:].+?性别[：:][男女]年龄[：:]\S+(?:科室[：:].+?床号[：:]\S+)?',
        '', text
    )

    # 4. 科室联系电话 + 医务处联系电话
    #    例: 科室联系电话：82xxxxxx医务处联系电话：82xxxx
    text = re.sub(
        r'科室联系电话[：:]\S+\s*医务处联系电话[：:]\S+',
        '', text
    )

    # 5. 家族史中的父/母个人信息
    #    例: 父姓名：杨xx，年龄：43岁，...籍贯：湖北省，...母姓名：高xx，...
    text = re.sub(r'父姓名[：:].*?(?=母姓名)', '', text, flags=re.DOTALL)
    text = re.sub(r'母姓名[：:].*?(?=[。\n]|$)', '', text, flags=re.DOTALL)

    # 6. 操作者 / 操作医师（可含多人、助手、进修医师等复杂结构，匹配到句号或"记录者"前）
    #    例: 操作者：傅xx主治医师，杨xx副主任医师。
    #        操作者：吴松xx主任医师助手：周xx主治医师、潘xx进修医师
    #        操作医师：刘xx副主任医师 /徐xx
    text = re.sub(
        r'操作(?:者|医师)[：:].*?(?:[。]|(?=记录者)|$)',
        '', text
    )

    # 7. "以上处理是在XX总住院医师/主治医师指导下进行的。"
    text = re.sub(
        r'以上处理是在.{0,30}?指导下进行的[。.]?\s*',
        '', text
    )

    # 8. 记录者签名：从"记录者:"到行尾（可含 /姓名 /姓名）
    text = re.sub(r'记录者[：:][^\n]*', '', text)

    # 9. 医师签字（含可选的"无"前缀）
    text = re.sub(r'无?医师签字[：:][^\n]*', '', text)

    # 10. 申请医师签名 / 会诊医师签名 标签
    text = re.sub(r'(?:申请|会诊)医师签名[：:]\s*', '', text)

    # ======================== 第二步：HanLP NER 识别并删除人名 ========================

    person_names = _extract_person_names(text)

    # 按长度降序替换，避免短名误匹配长名的子串
    for name in sorted(person_names, key=len, reverse=True):
        text = text.replace(name, '')

    # ======================== 清理多余空白和标点 ========================
    text = re.sub(r'[，,]\s*[，,]', '，', text)   # 连续逗号
    text = re.sub(r'[ \u3000]{2,}', ' ', text)    # 多余空格
    text = re.sub(r'\n{3,}', '\n\n', text)         # 多余换行
    text = text.strip()

    return text


def _extract_row(row, department_en: str) -> dict:
    """从一行数据中提取标准化的 dict，通用于所有科室。"""
    # description: 病历内容，清洗敏感信息
    raw_content = row.get('病历内容', '')
    description = _remove_sensitive_info(
        str(raw_content) if pd.notna(raw_content) else ''
    )

    # scenario: 病历模板类型
    scenario_raw = row.get('病历模板类型', '')
    scenario = str(scenario_raw).strip() if pd.notna(scenario_raw) else ''

    # disease: 诊断（列表形式）
    disease_raw = row.get('诊断', '')
    if pd.isna(disease_raw) or str(disease_raw).strip().lower() in ('nan', ''):
        disease = []
    else:
        disease = [str(disease_raw).strip()]

    # patient_id & admission_date：患者ID和入院日期，直接提取（不清洗）
    patient_id = row.get('患者ID', ''),
    if isinstance(patient_id, tuple):
        patient_id = str(patient_id[0]).zfill(12)
    elif isinstance(patient_id, float) or isinstance(patient_id, int):
        patient_id = str(int(patient_id)).zfill(12)
    admission_date = row.get('入院时间', ''),

    return {
        'description': description,
        'department': department_en,
        'scenario': f'emr-{scenario}',
        'patient_id': patient_id,
        'admission_date': admission_date,
        'disease': disease,
    }


def _load_existing_json(json_path: str) -> list:
    """检查 json 文件是否存在且合法，存在则加载返回，否则返回空列表。"""
    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    return []


def _save_json(json_list: list, json_path: str):
    """将 json_list 保存到文件，自动创建目录。"""
    os.makedirs(os.path.dirname(os.path.abspath(json_path)), exist_ok=True)
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_list, f, ensure_ascii=False, indent=4)


def xlsx_to_json(
    xlsx_path="./data/emr/raw/副本表2 病历信息 - 整理版1.xlsx",
    json_path="./data/emr/raw/emr_data.json",
):
    # 检查已有 json 文件，存在则从末尾 index + 1 继续，否则从 0 开始
    json_list = []
    # json_list = _load_existing_json(json_path)

    dfs = pd.read_excel(xlsx_path, sheet_name=None)

    department_map = {
        '产科': 'obstetrics',
        '儿科': 'pediatrics',
        '神经内科': 'neurology',
    }

    for department in dfs.keys():
        df = dfs[department]
        dept_key = department.strip()

        if dept_key not in department_map:
            raise ValueError(f'未知科室: {department}')

        dept_en = department_map[dept_key]

        for _, row in df.iterrows():
            data_sample = _extract_row(row, dept_en)
            data_sample['index'] = len(json_list)
            json_list.append(data_sample)

            # 保存到 json 文件
            if len(json_list) % 1000 == 0:
                _save_json(json_list, json_path)
                print(f'已保存 {len(json_list)} 条记录到 {json_path}')

    # 保存到 json 文件
    _save_json(json_list, json_path)
    print(f'已保存 {len(json_list)} 条记录到 {json_path}')

    return json_list


if __name__ == '__main__':
    xlsx_to_json()