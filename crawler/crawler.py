import csv
import time
import logging
import re
import playwright
import os
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

# 设置日志记录
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('crawler_log.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


_WIN_ILLEGAL_RE = re.compile(r'[<>:"/\\|?*]')


def _sanitize_windows_path_component(name: str) -> str:
    """Sanitize a string for use as a Windows file/folder name component."""
    if name is None:
        return "unknown"

    cleaned = str(name).replace("\ufeff", "").strip()
    # Remove control chars
    cleaned = re.sub(r"[\x00-\x1f]", "", cleaned)

    # Replace path separators with underscore to preserve readability
    cleaned = cleaned.replace("/", "_").replace("\\", "_")
    # Remove other illegal characters
    cleaned = cleaned.replace("?", "").replace("*", "")
    cleaned = cleaned.replace('"', "").replace("<", "").replace(">", "")
    cleaned = cleaned.replace(":", "_").replace("|", "_")

    # Collapse runs of underscores/spaces
    cleaned = re.sub(r"[ _]{2,}", "_", cleaned)

    # Windows doesn't like trailing dots/spaces
    cleaned = cleaned.strip().strip(".").strip()
    cleaned = cleaned.rstrip(". ")

    return cleaned or "unknown"


def ExtractDisease(csv_path: str | Path = "diseases.csv"):
    """读取疾病列表。

    兼容：
    - 每行一个疾病（可包含 OMIM，如 'xxx (OMIM:123)')
    - 或标准 CSV 单列
    """
    csv_path = Path(csv_path)
    diseases = []

    with open(csv_path, mode='r', encoding='utf-8-sig', newline='') as file:
        reader = csv.reader(file)
        for i, row in enumerate(reader):
            if not row:
                continue
            line = (row[0] or "").strip()
            if not line:
                continue
            # 去除括号中的 OMIM 等信息（兼容中英文括号）
            if "(" in line:
                disease_name = line.split("(")[0]
            elif "（" in line:
                disease_name = line.split("（")[0]
            else:
                disease_name = line
            diseases.append({'id': i + 1, 'name': disease_name.strip()})

    return diseases


class MedicalLiteratureCrawler:
    def __init__(self, browser_path=None, save_dir: str | Path = "disease_paper"):
        self.browser_path = browser_path
        self.results = []
        self.errors = []
        # 性能相关配置
        self.headless = True
        self.default_navigation_timeout = 30000
        self.default_action_timeout = 15000

        # 创建保存目录
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        
    def setup_browser(self, playwright):
        """设置浏览器"""
        launch_kwargs = {
            'headless': self.headless
        }
        if self.browser_path:
            launch_kwargs['executable_path'] = self.browser_path
        browser = playwright.chromium.launch(**launch_kwargs)
        return browser

    def safe_wait_for_load_state(self, page, state="networkidle", timeout=None):
        """安全等待页面加载：优先等待指定 state，超时后回退到 domcontentloaded，再降级为短暂等待，避免抛出未捕获超时异常"""
        try:
            use_timeout = timeout if timeout is not None else self.default_navigation_timeout
            page.wait_for_load_state(state, timeout=use_timeout)
            return True
        except Exception:
            try:
                # 回退到更宽松的加载状态
                page.wait_for_load_state("domcontentloaded", timeout=10000)
                return True
            except Exception:
                # 最后降级为固定短等待，继续执行（记录并返回 False）
                try:
                    page.wait_for_timeout(1500)
                except Exception:
                    pass
                return False
    
    def search_disease(self, page, disease_name):
        """搜索特定疾病"""
        try:
            search_box = page.get_by_role("textbox", name="输入主题、疾病名称、文献标题、作者")
            search_box.clear()
            search_box.fill(disease_name)
            search_box.press("Enter")
            
            self.safe_wait_for_load_state(page, "networkidle")
            page.wait_for_timeout(1000)  # 减少等待时间

            
            return True
            
        except Exception as e:
            self.errors.append({
                "disease": disease_name,
                "error": str(e),
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            return False
    
    def check_search_results(self, page, disease_name):
        """检查搜索结果是否为空"""
        try:
            no_result_selectors = [
                'text=未找到',
                'text=无结果',
                'text=没有找到',
                'text=No results',
                'text=暂无数据',
                '.no-result',
                '.empty-result',
                '.no-data'
            ]
            
            for selector in no_result_selectors:
                if page.locator(selector).count() > 0:
                    logger.info(f"疾病 '{disease_name}' 无搜索结果")
                    return False
            
            result_selectors = ['.w_search_item']
            
            for selector in result_selectors:
                count = page.locator(selector).count()
                if count > 0:
                    logger.info(f"疾病 '{disease_name}' 找到 {count} 个可能的结果项 (选择器: {selector})")
                    return True
                
            logger.warning(f"疾病 '{disease_name}' 无法确定是否有结果，继续处理")
            return True
            
        except Exception as e:
            logger.error(f"检查搜索结果时出错: {str(e)}")
            return False
    
    def extract_result_links(self, page, disease_name, max_results=2):
        """提取搜索结果中的链接"""
        links = []
        
        try:
            try:
                page.wait_for_selector('.w_search_item', timeout=3000)
            except:
                pass
            
            # 方法1：按结果项提取
            result_items = page.locator('.w_search_item').all()
            
            for i, item in enumerate(result_items[:max_results]):
                try:
                    # 提取标题
                    title_elem = item.locator('h1 a').first
                    title = ""
                    if title_elem.count() > 0:
                        title = title_elem.inner_text()[:150].strip()
                    else:
                        title_text = item.locator('h1').first
                        if title_text.count() > 0:
                            title = title_text.inner_text()[:150].strip()
                        else:
                            title = f"结果_{i+1}"
                    
                    # 查找全文链接
                    fulltext_elem = item.locator('a[href*="cmaid"]').first
                    if fulltext_elem.count() > 0:
                        href = fulltext_elem.get_attribute('href')
                        
                        if href:
                            if not href.startswith('http'):
                                if href.startswith('/'):
                                    href = f"https://rs.yiigle.com{href}"
                                elif 'cmaid' in href:
                                    href = f"https://rs.yiigle.com/{href}"
                            
                            links.append({
                                'url': href,
                                'title': title,
                                'index': i
                            })
                            
                except Exception as e:
                    continue
            
            return links
            
        except Exception as e:
            return []
    
    def check_keyword_in_page(self, page_content, disease_name):
        """检查页面内容是否包含疾病关键词"""
        keywords = []
        
        # 1. 完整的疾病名称
        keywords.append(disease_name)
        
        # 2. 去掉"型"、"症"等后缀的变体
        if disease_name.endswith("型"):
            keywords.append(disease_name[:-1])
        if disease_name.endswith("综合征"):
            keywords.append(disease_name[:-3])
            keywords.append(disease_name.replace("综合征", "").strip())
        if disease_name.endswith("症"):
            keywords.append(disease_name[:-1])
        
        # 3. 去除数字后的名称
        disease_without_number = re.sub(r'\d+型$', '', disease_name)
        if disease_without_number != disease_name:
            keywords.append(disease_without_number)
        
        # 去重
        keywords = list(set(keywords))
        
        # 检查每个关键词
        for keyword in keywords:
            if keyword and keyword in page_content:
                return True, keyword
        
        return False, None
    
    def extract_abstract(self, page):
        """从详情页提取摘要"""
        try:
            # 尝试常见的摘要选择器
            abstract_selectors = [
                '.abstract',
                '.summary',
                '.zhaiyao',
                'p:contains("摘要")',
                'div:contains("摘要")',
                '.content p',
                '.detail p',
                '.article-content p'
            ]
            
            for selector in abstract_selectors:
                try:
                    elements = page.locator(selector).all()
                    for elem in elements:
                        text = elem.inner_text().strip()
                        if len(text) > 50:  # 摘要通常较长
                            return text
                except:
                    continue
            
            # 如果没找到，尝试获取页面主要内容
            try:
                main_content = page.locator('body').inner_text()
                # 查找摘要相关内容
                lines = main_content.split('\n')
                for line in lines:
                    if '摘要' in line and len(line) > 10:
                        return line.strip()
            except:
                pass
            
            return "未找到摘要"
            
        except Exception as e:
            return f"提取摘要失败: {str(e)}"
    
    def download_pdf_from_detail_page(self, page, disease_name, result_index, save_dir, safe_title, pdf_url=None):
        """从详情页下载PDF文件"""
        try:
            # 等待页面完全加载（使用安全等待以避免超时抛出）
            self.safe_wait_for_load_state(page, "networkidle")
            page.wait_for_timeout(1000)

            # 如果提供了直接的pdf_url，优先使用HTTP请求下载
            if pdf_url:
                try:
                    href = pdf_url.strip()
                    if href.startswith('//'):
                        href = 'https:' + href
                    if href.startswith('http'):
                        full_url = href
                    elif href.startswith('/'):
                        full_url = 'https://www.yiigle.com' + href
                    else:
                        full_url = 'https://' + href

                    resp = page.request.get(full_url, timeout=30000)
                    if resp.ok:
                        content = resp.body()
                        # 简单判断是否为pdf
                        ctype = resp.headers.get('content-type', '')
                        if b'%PDF' in content[:4] or 'pdf' in ctype.lower() or len(content) > 2000:
                            safe_disease_name = _sanitize_windows_path_component(disease_name)
                            pdf_filename = f"{safe_disease_name}_{safe_title}.pdf"
                            pdf_path = save_dir / pdf_filename
                            save_dir.mkdir(parents=True, exist_ok=True)
                            with open(pdf_path, 'wb') as f:
                                f.write(content)
                            return str(pdf_path)
                        # 如果不是pdf则继续尝试页面点击下载
                    # 如果请求失败，降级为页面触发下载
                except Exception:
                    pass

            # 根据录制代码：尝试通过页面按钮触发下载
            # 1) 先尝试页面中所有直接含有 .pdf 的链接
            try:
                anchors = page.locator('a').all()
                for a in anchors:
                    try:
                        ahref = a.get_attribute('href')
                        if not ahref:
                            continue
                        if '.pdf' in ahref.lower() or ahref.lower().endswith('.pdf'):
                            candidate = ahref
                            if candidate.startswith('//'):
                                candidate = 'https:' + candidate
                            elif not candidate.startswith('http'):
                                # 相对路径处理
                                candidate = page.url.rstrip('/') + '/' + candidate.lstrip('/')
                            try:
                                resp = page.request.get(candidate, timeout=30000)
                                if resp.ok:
                                    content = resp.body()
                                    ctype = resp.headers.get('content-type','')
                                    if b'%PDF' in content[:4] or 'pdf' in ctype.lower() or len(content) > 2000:
                                        safe_disease_name = _sanitize_windows_path_component(disease_name)
                                        pdf_filename = f"{safe_disease_name}_{safe_title}.pdf"
                                        pdf_path = save_dir / pdf_filename
                                        save_dir.mkdir(parents=True, exist_ok=True)
                                        with open(pdf_path, 'wb') as f:
                                            f.write(content)
                                        return str(pdf_path)
                            except Exception:
                                continue
                    except Exception:
                        continue
            except Exception:
                pass

            # 2) 尝试查找 iframe 中嵌入的 pdf
            try:
                iframes = page.frames
                for fr in iframes:
                    try:
                        src = fr.url
                        if src and ('.pdf' in src.lower() or src.lower().endswith('.pdf')):
                            candidate = src
                            if candidate.startswith('//'):
                                candidate = 'https:' + candidate
                            elif not candidate.startswith('http'):
                                candidate = page.url.rstrip('/') + '/' + candidate.lstrip('/')
                            resp = page.request.get(candidate, timeout=30000)
                            if resp.ok:
                                content = resp.body()
                                ctype = resp.headers.get('content-type','')
                                if b'%PDF' in content[:4] or 'pdf' in ctype.lower() or len(content) > 2000:
                                    safe_disease_name = _sanitize_windows_path_component(disease_name)
                                    pdf_filename = f"{safe_disease_name}_{safe_title}.pdf"
                                    pdf_path = save_dir / pdf_filename
                                    save_dir.mkdir(parents=True, exist_ok=True)
                                    with open(pdf_path, 'wb') as f:
                                        f.write(content)
                                    return str(pdf_path)
                    except Exception:
                        continue
            except Exception:
                pass

            # 3) 尝试通过点击可能的下载按钮触发浏览器下载
            try:
                download_button_texts = ['PDF下载', '下载PDF', '下载全文', '查看PDF', '全文下载', '下载']
                for text in download_button_texts:
                    try:
                        elems = page.get_by_text(text)
                        if elems.count() > 0:
                            # 尝试点击并捕获下载
                            for idx in range(elems.count()):
                                try:
                                    with page.expect_download(timeout=20000) as download_info:
                                        elems.nth(idx).click()
                                    download = download_info.value
                                    safe_disease_name = _sanitize_windows_path_component(disease_name)
                                    pdf_filename = f"{safe_disease_name}_{safe_title}.pdf"
                                    pdf_path = save_dir / pdf_filename
                                    save_dir.mkdir(parents=True, exist_ok=True)
                                    download.save_as(str(pdf_path))
                                    return str(pdf_path)
                                except Exception:
                                    continue
                    except Exception:
                        continue
            except Exception:
                pass

            # 4) 未找到或下载失败
            logger.info(f"未能为 '{safe_title}' 找到可下载的 PDF（页面: {page.url}）")
            return None

        except Exception as e:
            print(f"PDF下载过程出错: {e}")
            return None
    

    def process_detail_page(self, page, link_info, disease_name, result_index, save_dir, pdf_candidate=None):
        """处理详情页并收集信息"""
        try:
            # 等待页面加载（使用安全等待避免 networkidle 超时）
            self.safe_wait_for_load_state(page, "networkidle")
            page.wait_for_timeout(500)
            
            # 直接提取摘要并保存，同时下载PDF
            title = link_info['title']
            abstract = self.extract_abstract(page)
            
            # 创建安全的文件名
            safe_title = _sanitize_windows_path_component(
                title.replace(' ', '_')
            )
            safe_disease_name = _sanitize_windows_path_component(disease_name)
            
            # 保存txt文件
            txt_filename = f"{safe_disease_name}_{safe_title}.txt"
            txt_path = save_dir / txt_filename
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(f"题目: {title}\n\n摘要: {abstract}\n")
            
            # 下载PDF，优先使用传入的候选pdf链接
            pdf_path = None
            if pdf_candidate:
                pdf_path = self.download_pdf_from_detail_page(page, disease_name, result_index, save_dir, safe_title, pdf_url=pdf_candidate)
            if not pdf_path:
                pdf_path = self.download_pdf_from_detail_page(page, disease_name, result_index, save_dir, safe_title)
            
            if pdf_path:
                print(f"下载PDF: {pdf_path}")
            print(f"保存TXT: {txt_path}")
            
            return {
                'url': page.url,
                'title': link_info['title'],
                'disease': disease_name,
                'txt_file': str(txt_path),
                'pdf_file': str(pdf_path) if pdf_path else None
            }
            
        except Exception as e:
            print(f"处理详情页失败: {e}")
            return None
    
    def process_disease_cmcr(self, page, context, disease_name, disease_index, max_results_per_disease=2):
        """处理单个疾病的完整流程"""
        disease_result = {
            'disease': disease_name,
            'search_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'has_results': False,
            'result_count': 0,
            'details': []
        }
        
        try:
            # 1. 搜索疾病
            search_success = self.search_disease(page, disease_name)
            if not search_success:
                return disease_result
            
            # 2. 检查是否有结果
            has_results = self.check_search_results(page, disease_name)
            disease_result['has_results'] = has_results
            
            if not has_results:
                return disease_result
            
            # 3. 提取结果链接
            links = self.extract_result_links(page, disease_name, max_results=2)
            disease_result['result_count'] = len(links)
            
            print(f"找到 {len(links)} 个结果")
            
            if not links:
                return disease_result
            
            # 4. 访问详情页（复用单个详情页以减少创建开销）
            max_to_visit = min(len(links), max_results_per_disease)
            detail_page = context.new_page()
            try:
                for i, link in enumerate(links[:max_to_visit]):
                    try:
                        detail_page.goto(link['url'], timeout=self.default_navigation_timeout)
                        detail_page.wait_for_load_state('domcontentloaded')
                        detail_info = self.process_detail_page(detail_page, link, disease_name, i, self.current_save_dir)
                        if detail_info:
                            disease_result['details'].append(detail_info)
                    except Exception:
                        continue
                    # 轻微等待让页面事件完成
                    time.sleep(0.2)
            finally:
                try:
                    detail_page.close()
                except:
                    pass
            
            return disease_result
            
        except Exception as e:
            disease_result['error'] = str(e)
            return disease_result
    
    def save_results(self):
        """保存所有结果到CSV文件"""
        # 由于我们现在只保存txt文件，这里简化处理
        logger.info(f"所有文献信息已保存到目录: {self.save_dir}")
        
        # 如果需要保存错误信息
        if self.errors:
            errors_path = self.save_dir / "errors.csv"
            with open(errors_path, 'w', newline='', encoding='utf-8-sig') as f:
                fieldnames = ['disease', 'error', 'time']
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.errors)
    
    def search_disease_new_site(self, page, disease_name):
        """搜索特定疾病在新网站"""
        try:
            search_box = page.get_by_role("textbox", name="主题/文题/作者/刊名")
            search_box.clear()
            search_box.fill(disease_name)
            page.get_by_role("button", name="搜索").click()
            
            # 使用安全等待
            self.safe_wait_for_load_state(page, "networkidle")
            page.wait_for_timeout(1000)
            
            return True
            
        except Exception as e:
            self.errors.append({
                "disease": disease_name,
                "error": str(e),
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            return False
    
    def extract_top_results(self, page, max_results=2):
        """提取前几个搜索结果"""
        results = []
        try:
            result_elements = page.locator('.s_searchResult_li').all()
            for i, elem in enumerate(result_elements[:max_results]):
                try:
                    title_elem = elem.locator('.s_searchResult_li_title a').first
                    title = title_elem.inner_text().strip() if title_elem.count() > 0 else f"Result {i+1}"
                    text = elem.inner_text().strip()
                    results.append({'title': title, 'text': text})
                except Exception as e:
                    logger.error(f"提取结果 {i} 失败: {str(e)}")
                    continue
        except Exception as e:
            logger.error(f"提取搜索结果失败: {str(e)}")
        return results
    
    def process_disease_new_site(self, page, context, disease_name, disease_id, max_results=2):
        """处理单个疾病在新网站"""
        disease_result = {
            'disease': disease_name,
            'search_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'details': []
        }
        
        try:
            # 1. 搜索疾病
            search_success = self.search_disease_new_site(page, disease_name)
            if not search_success:
                return disease_result
            
            # 2. 提取前两个结果
            results = self.extract_top_results(page, max_results)
            print(f"找到 {len(results)} 个结果")
            
            # 4. 处理每个结果
            for i, result in enumerate(results):
                try:
                    safe_disease_name = _sanitize_windows_path_component(disease_name)

                    # 先尝试打开详情页，优先从详情页提取题目/摘要与可能的PDF链接
                    detail_url = None
                    title_links = page.locator('.s_searchResult_li_title a').all()
                    if i < len(title_links):
                        href = title_links[i].get_attribute('href')
                        if href:
                            detail_url = href if href.startswith('http') else ('https:' + href if href.startswith('//') else ('https://www.yiigle.com' + href))

                    pdf_file_path = None
                    txt_path = None

                    if detail_url:
                        try:
                            # 复用详情页
                            if 'detail_page' not in locals():
                                detail_page = context.new_page()
                            detail_page.goto(detail_url, timeout=self.default_navigation_timeout)
                            detail_page.wait_for_load_state('domcontentloaded')

                            # 提取题目：优先使用页面的主标题，否则使用结果页的标题
                            title_text = None
                            try:
                                h1 = detail_page.locator('h1').first
                                if h1.count() > 0:
                                    title_text = h1.inner_text().strip()[:200]
                            except:
                                title_text = None
                            if not title_text:
                                title_text = result.get('title') or 'untitled'

                            # 提取摘要
                            abstract = self.extract_abstract(detail_page)

                            # 生成安全文件名
                            safe_title = _sanitize_windows_path_component(title_text.replace(' ', '_'))

                            # 保存txt（如果只有题目也保存）
                            txt_filename = f"{safe_disease_name}_{safe_title}.txt"
                            txt_path = self.current_save_dir / txt_filename
                            with open(txt_path, 'w', encoding='utf-8') as f:
                                if abstract and abstract != '未找到摘要':
                                    f.write(f"题目: {title_text}\n\n摘要: {abstract}\n")
                                else:
                                    f.write(f"题目: {title_text}\n")
                            print(f"保存TXT: {txt_path}")

                            # 在详情页查找PDF链接候选
                            pdf_candidates = []
                            try:
                                # 常见选择器：直接以.pdf结尾的链接，或包含PDF关键词的链接
                                anchors = detail_page.locator('a').all()
                                for a in anchors:
                                    try:
                                        ahref = a.get_attribute('href')
                                        if ahref and (ahref.endswith('.pdf') or '.pdf' in ahref):
                                            pdf_candidates.append(ahref)
                                        else:
                                            # 文本中包含PDF或下载关键词
                                            txt = a.inner_text().lower()
                                            if 'pdf' in txt or '下载pdf' in txt or 'download' in txt:
                                                if ahref:
                                                    pdf_candidates.append(ahref)
                                    except:
                                        continue
                            except:
                                pass

                            # 尝试使用pdf_candidates优先下载
                            for candidate in pdf_candidates:
                                possible = candidate
                                try:
                                    if possible.startswith('//'):
                                        possible = 'https:' + possible
                                    elif not possible.startswith('http'):
                                        possible = 'https://www.yiigle.com' + possible
                                    resp = detail_page.request.get(possible, timeout=30000)
                                    if resp.ok:
                                        content = resp.body()
                                        ctype = resp.headers.get('content-type','')
                                        if b'%PDF' in content[:4] or 'pdf' in ctype.lower() or len(content) > 2000:
                                            pdf_filename = f"{safe_disease_name}_{safe_title}.pdf"
                                            pdf_path = self.current_save_dir / pdf_filename
                                            with open(pdf_path, 'wb') as f:
                                                f.write(content)
                                            pdf_file_path = str(pdf_path)
                                            print(f"下载PDF: {pdf_file_path}")
                                            break
                                except Exception:
                                    continue

                            # 如果详情页没有可用pdf，再尝试搜索页的PDF链接
                            if not pdf_file_path:
                                # 搜索页的PDF链接（如存在）
                                try:
                                    search_pdf_links = page.locator('.s_searchResult_li_button_r a').all()
                                    if i < len(search_pdf_links):
                                        shref = search_pdf_links[i].get_attribute('href')
                                        if shref:
                                            candidate = shref
                                            if candidate.startswith('//'):
                                                candidate = 'https:' + candidate
                                            elif not candidate.startswith('http'):
                                                candidate = 'https://www.yiigle.com' + candidate
                                            resp = page.request.get(candidate, timeout=30000)
                                            if resp.ok:
                                                content = resp.body()
                                                ctype = resp.headers.get('content-type','')
                                                if b'%PDF' in content[:4] or 'pdf' in ctype.lower() or len(content) > 2000:
                                                    pdf_filename = f"{safe_disease_name}_{safe_title}.pdf"
                                                    pdf_path = self.current_save_dir / pdf_filename
                                                    with open(pdf_path, 'wb') as f:
                                                        f.write(content)
                                                    pdf_file_path = str(pdf_path)
                                                    print(f"下载PDF: {pdf_file_path}")
                                except Exception:
                                    pass
                            
                            # 关闭将留到 finally 中统一关闭 detail_page
                        except Exception as e:
                            print(f"打开详情页失败: {e}")

                    # 如果没有detail_url但搜索结果提供了title，仍尝试从搜索页下载PDF并保存题目
                    if not detail_url:
                        # 使用结果页的title作为题目
                        title_text = result.get('title') or 'untitled'
                        safe_title = _sanitize_windows_path_component(title_text.replace(' ', '_'))
                        txt_filename = f"{safe_disease_name}_{safe_title}.txt"
                        txt_path = self.current_save_dir / txt_filename
                        with open(txt_path, 'w', encoding='utf-8') as f:
                            f.write(f"题目: {title_text}\n")
                        print(f"保存TXT: {txt_path}")

                        # 尝试搜索页pdf链接
                        try:
                            search_pdf_links = page.locator('.s_searchResult_li_button_r a').all()
                            if i < len(search_pdf_links):
                                shref = search_pdf_links[i].get_attribute('href')
                                if shref:
                                    candidate = shref
                                    if candidate.startswith('//'):
                                        candidate = 'https:' + candidate
                                    elif not candidate.startswith('http'):
                                        candidate = 'https://www.yiigle.com' + candidate
                                    resp = page.request.get(candidate, timeout=30000)
                                    if resp.ok:
                                        content = resp.body()
                                        ctype = resp.headers.get('content-type','')
                                        if b'%PDF' in content[:4] or 'pdf' in ctype.lower() or len(content) > 2000:
                                            pdf_filename = f"{safe_disease_name}_{safe_title}.pdf"
                                            pdf_path = self.current_save_dir / pdf_filename
                                            with open(pdf_path, 'wb') as f:
                                                f.write(content)
                                            pdf_file_path = str(pdf_path)
                                            print(f"下载PDF: {pdf_file_path}")
                        except Exception:
                            pass

                        detail_info = {
                        'url': detail_url if 'detail_url' in locals() else None,
                        'title': title_text if 'title_text' in locals() else result.get('title'),
                        'disease': disease_name,
                        'txt_file': str(txt_path) if txt_path else None,
                        'pdf_file': pdf_file_path
                    }
                    disease_result['details'].append(detail_info)
                    
                except Exception as e:
                    logger.error(f"处理结果 {i} 失败: {str(e)}")
                    continue
            
            # 关闭复用的 detail_page（如果存在）
            try:
                if 'detail_page' in locals():
                    detail_page.close()
            except:
                pass

            return disease_result
            
        except Exception as e:
            disease_result['error'] = str(e)
            return disease_result
    
    def run(self, diseases, browser_path=None):
        """主运行函数"""
        if browser_path:
            self.browser_path = browser_path
            
        with sync_playwright() as p:
            browser = self.setup_browser(p)
            context = browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                accept_downloads=True  # 允许下载文件
            )
            # 统一设置默认超时，避免在不同页面反复传参
            try:
                context.set_default_navigation_timeout(self.default_navigation_timeout)
                context.set_default_timeout(self.default_action_timeout)
            except Exception:
                pass
            page = context.new_page()
            
            try:
                # 遍历所有疾病
                total_diseases = len(diseases)
                for i, disease in enumerate(diseases):
                    disease_id = disease['id']
                    disease_name = disease['name']
                    print(f"正在处理疾病 {disease_id}/{total_diseases}: {disease_name}")

                    # 每个疾病的处理用独立的 try/except 包裹，避免单个超时导致整个爬虫中断
                    try:
                        # 设置保存目录
                        safe_folder_name = _sanitize_windows_path_component(disease_name)
                        self.current_save_dir = self.save_dir / f"{disease_id}_{safe_folder_name}"
                        self.current_save_dir.mkdir(parents=True, exist_ok=True)

                        # 1. 处理cmcr.yiigle.com
                        print(f"正在搜索疾病 {disease_name} 在 https://cmcr.yiigle.com/index")
                        page.goto("https://cmcr.yiigle.com/index")
                        self.safe_wait_for_load_state(page, "networkidle")
                        page.wait_for_timeout(1000)

                        result_cmcr = self.process_disease_cmcr(page, context, disease_name, disease_id, max_results_per_disease=2)
                    except Exception as e:
                        logger.error(f"处理疾病 {disease_name} 时出错: {e}")
                        self.errors.append({
                            'disease': disease_name,
                            'error': str(e),
                            'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        continue

                    # # 2. 处理www.yiigle.com
                    # print(f"正在搜索疾病 {disease_name} 在 https://www.yiigle.com/index")
                    # page.goto("https://www.yiigle.com/index")
                    # page.wait_for_load_state("networkidle")
                    # page.wait_for_timeout(1000)
                    
                    # result_new = self.process_disease_new_site(page, context, disease_name, disease_id, max_results=2)
                    
                    # 合并结果
                    combined_result = {
                        'disease': disease_name,
                        'id': disease_id,
                        'cmcr_results': result_cmcr,
                        # 'new_site_results': result_new
                    }
                    self.results.append(combined_result)
                    
                    # 减少等待时间以加速
                    time.sleep(1)
                
            finally:
                # 保存结果
                self.save_results()
                
                # 关闭浏览器
                browser.close()
    
    def print_summary(self):
        """打印运行摘要"""
        logger.info("=" * 50)
        logger.info("爬虫运行完成！")
        logger.info(f"处理疾病总数: {len(self.results)}")
        
        successful = sum(1 for r in self.results if r.get('has_results', False))
        details_count = sum(len(r.get('details', [])) for r in self.results)
        txt_count = sum(
            1 for r in self.results 
            for d in r.get('details', []) 
            if d.get('txt_file')
        )
        pdf_count = sum(
            1 for r in self.results 
            for d in r.get('details', []) 
            if d.get('pdf_file')
        )
        
        logger.info(f"有搜索结果的疾病: {successful}")
        logger.info(f"获取到的详情页总数: {details_count}")
        logger.info(f"成功保存文献信息文件数: {txt_count}")
        logger.info(f"成功下载PDF文件数: {pdf_count}")
        logger.info(f"错误数量: {len(self.errors)}")
        logger.info(f"所有文件保存在: {self.save_dir}")
        logger.info("=" * 50)


# 使用示例
def run():
    # 1) 需要爬取的 part 与对应 CSV
    parts_to_crawl = {
        1: Path("csv") / "diseases_part1.csv",
        2: Path("csv") / "diseases_part2.csv",
        4: Path("csv") / "diseases_part4.csv",
    }

    # 2) 指定浏览器路径
    browser_path = r"D:\playwright_browsers\chromium-1200\chrome-win64\chrome.exe"

    # 3) 逐个 part 爬取，并将结果落到 paper/part{n}/website1
    for part, csv_path in parts_to_crawl.items():
        diseases = ExtractDisease(csv_path)
        save_dir = Path("paper") / f"part{part}" / "website1"
        crawler = MedicalLiteratureCrawler(save_dir=save_dir)
        crawler.run(diseases, browser_path)


if __name__ == "__main__":
    run()