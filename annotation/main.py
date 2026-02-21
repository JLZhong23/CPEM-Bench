from quart import Quart, render_template, request, jsonify
import json
import os
import aiofiles
import pandas as pd
from config import TEMPLATE_FOLDER, DATA_ROOT, PORT, DATA_FILE, OUTPUT_FILE, HPO_FILE


# 配置
app = Quart(__name__, template_folder=TEMPLATE_FOLDER) 
APP_ROOT = os.path.dirname(os.path.abspath(__file__))

# 数据文件路径
DATA_FILE = os.path.join(DATA_ROOT, DATA_FILE)
OUTPUT_FILE = os.path.join(DATA_ROOT, OUTPUT_FILE)
HPO_FILE = HPO_FILE


RAW_DATA = []           # 未标注的数据
ANNOTATED_IDS = set()   # 已标注的数据ID集合
TOTAL_COUNT = 0         # 原始数据总数
STANDARD_TERMS = set()  # HPO标准术语集合（中文）


def load_hpo_terms():
    """加载HPO标准术语表"""
    global STANDARD_TERMS
    STANDARD_TERMS = set()
    
    if os.path.exists(HPO_FILE):
        try:
            df = pd.read_excel(HPO_FILE)
            # 假设中文翻译在"中文翻译"列
            if '中文翻译' in df.columns:
                STANDARD_TERMS = set(df['中文翻译'].dropna().astype(str).str.strip())
                print(f"[System] 已加载 {len(STANDARD_TERMS)} 条HPO标准术语。")
            else:
                print(f"[Warning] HPO文件中未找到'中文翻译'列，可用列: {list(df.columns)}")
        except Exception as e:
            print(f"[Warning] 加载HPO术语表失败: {e}")
    else:
        print(f"[Warning] HPO术语文件 {HPO_FILE} 不存在！")


async def load_annotated_ids():
    """加载已标注的数据ID"""
    global ANNOTATED_IDS
    ANNOTATED_IDS = set()
    
    if os.path.exists(OUTPUT_FILE):
        async with aiofiles.open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            async for line in f:
                line = line.strip()
                if line:
                    try:
                        item = json.loads(line)
                        if 'index' in item:
                            ANNOTATED_IDS.add(item['index'])
                    except json.JSONDecodeError:
                        continue
        print(f"[System] 已加载 {len(ANNOTATED_IDS)} 条已标注数据ID。")
    else:
        print(f"[Info] 标注输出文件 {OUTPUT_FILE} 不存在，将创建新文件。")


async def load_data_from_file():
    """启动时加载数据，并过滤已标注的数据"""
    global RAW_DATA, TOTAL_COUNT
    
    # 先加载已标注的ID
    await load_annotated_ids()
    
    if os.path.exists(DATA_FILE):
        async with aiofiles.open(DATA_FILE, 'r', encoding='utf-8') as f:
            content = await f.read()
            all_data = json.loads(content)
        
        # 记录原始总数
        TOTAL_COUNT = len(all_data)
        
        # 处理数据并过滤已标注的
        RAW_DATA = []
        for item in all_data:
            item['llm_predict'] = list(map(lambda x: x[0], item['llm_predict']))
            
            # 确保 human_annotated 中包含阴性表型字段
            if 'human_annotated' not in item:
                item['human_annotated'] = {}
            if 'patient_phenotypes_neg' not in item['human_annotated']:
                item['human_annotated']['patient_phenotypes_neg'] = []
            if 'family_phenotypes_neg' not in item['human_annotated']:
                item['human_annotated']['family_phenotypes_neg'] = []
            # 同时确保阳性表型字段存在
            if 'patient_phenotypes' not in item['human_annotated']:
                item['human_annotated']['patient_phenotypes'] = []
            if 'family_phenotypes' not in item['human_annotated']:
                item['human_annotated']['family_phenotypes'] = []
            
            # 只保留未标注的数据
            if item['index'] not in ANNOTATED_IDS:
                RAW_DATA.append(item)
        
        print(f"[System] 原始数据共 {TOTAL_COUNT} 条，已标注 {len(ANNOTATED_IDS)} 条，剩余 {len(RAW_DATA)} 条待标注。")
    else:
        print(f"[Warning] 数据文件 {DATA_FILE} 不存在！")
        RAW_DATA = []
        TOTAL_COUNT = 0


@app.before_serving
async def startup():
    load_hpo_terms()  # 加载HPO标准术语表
    await load_data_from_file()


# --- 路由定义 ---

@app.route('/')
async def index():
    return await render_template("index_backup.html")


@app.route('/standard_terms', methods=['GET'])
async def get_standard_terms():
    """获取HPO标准术语集合"""
    return jsonify({
        "terms": list(STANDARD_TERMS),
        "count": len(STANDARD_TERMS)
    })


@app.route('/progress', methods=['GET'])
async def get_progress():
    """获取标注进度"""
    annotated_count = len(ANNOTATED_IDS)
    remaining_count = len(RAW_DATA)
    
    return jsonify({
        "total": TOTAL_COUNT,
        "annotated": annotated_count,
        "remaining": remaining_count,
        "percentage": round(annotated_count / TOTAL_COUNT * 100, 1) if TOTAL_COUNT > 0 else 0
    })


@app.route('/change', methods=['POST'])
async def change_data():
    """
    处理数据切换请求 (初始化/上一条/下一条)
    前端 Payload: { "action": "init"|"next"|"prev", "current_id": "DATA_001" }
    """
    data = await request.get_json()
    action = data.get('action')
    current_id = data.get('current_id')
    
    if not RAW_DATA:
        return jsonify({
            "message": "No more data",
            "progress": {
                "total": TOTAL_COUNT,
                "annotated": len(ANNOTATED_IDS),
                "remaining": 0,
                "percentage": 100.0 if TOTAL_COUNT > 0 else 0
            }
        }), 200

    current_index = 0
    
    # 找到当前 ID 的索引
    if current_id:
        for i, item in enumerate(RAW_DATA):
            if item['index'] == current_id:
                current_index = i
                break
    
    # 根据动作计算新的索引
    new_index = current_index
    
    if action == 'init':
        new_index = 0
    elif action == 'next':
        new_index = current_index + 1
    elif action == 'prev':
        new_index = current_index - 1
        
    # 边界检查
    if new_index < 0:
        new_index = 0
    if new_index >= len(RAW_DATA):
        # 如果超出范围，返回空或特定的结束标记
        return jsonify({
            "message": "No more data",
            "progress": {
                "total": TOTAL_COUNT,
                "annotated": len(ANNOTATED_IDS),
                "remaining": len(RAW_DATA),
                "percentage": round(len(ANNOTATED_IDS) / TOTAL_COUNT * 100, 1) if TOTAL_COUNT > 0 else 0
            }
        }), 200

    # 返回新的数据对象，附带进度信息
    response_data = RAW_DATA[new_index].copy()
    response_data['progress'] = {
        "total": TOTAL_COUNT,
        "annotated": len(ANNOTATED_IDS),
        "remaining": len(RAW_DATA),
        "percentage": round(len(ANNOTATED_IDS) / TOTAL_COUNT * 100, 1) if TOTAL_COUNT > 0 else 0
    }
    
    return jsonify(response_data)


@app.route('/submit', methods=['POST'])
async def submit_annotation():
    """
    处理标注提交
    前端 Payload: { 
        "index": "...", 
        "description": "...",
        "patient_phenotypes": [],
        "family_phenotypes": [],
        "patient_phenotypes_neg": [],
        "family_phenotypes_neg": [],
        "is_sure": true/false
    }
    """
    result = await request.get_json()
    
    # 检查是否重复提交
    submitted_id = result.get('index')
    if submitted_id in ANNOTATED_IDS:
        print(f"[Warning] 数据 {submitted_id} 已存在，跳过重复保存。")
        return jsonify({"status": "warning", "message": "Data already annotated, skipped."})
    
    # 确保所有必要字段都存在
    save_result = {
        "index": result.get('index'),
        "description": result.get('description'),
        "patient_phenotypes": result.get('patient_phenotypes', []),
        "family_phenotypes": result.get('family_phenotypes', []),
        "patient_phenotypes_neg": result.get('patient_phenotypes_neg', []),
        "family_phenotypes_neg": result.get('family_phenotypes_neg', []),
        "is_sure": result.get('is_sure', True)
    }
    
    # 将结果追加写入到 jsonl 文件中 (每一行是一个 json)
    async with aiofiles.open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
        await f.write(json.dumps(save_result, ensure_ascii=False) + "\n")
    
    # 更新已标注集合
    ANNOTATED_IDS.add(submitted_id)
    
    # 从待标注列表中移除
    global RAW_DATA
    RAW_DATA = [item for item in RAW_DATA if item['index'] != submitted_id]
        
    print(f"[Submit] 数据 {submitted_id} 已保存。剩余 {len(RAW_DATA)} 条待标注。")
    
    return jsonify({
        "status": "success", 
        "message": "Saved successfully",
        "progress": {
            "total": TOTAL_COUNT,
            "annotated": len(ANNOTATED_IDS),
            "remaining": len(RAW_DATA),
            "percentage": round(len(ANNOTATED_IDS) / TOTAL_COUNT * 100, 1) if TOTAL_COUNT > 0 else 0
        }
    })


if __name__ == '__main__':
    print("=" * 60)
    print("标注系统后端启动")
    print(f"Template Folder: {app.template_folder}")
    print(f"Data File: {DATA_FILE}")
    print(f"Output File: {OUTPUT_FILE}")
    print("=" * 60)
    # 调试模式运行
    app.run(port=PORT, debug=True)