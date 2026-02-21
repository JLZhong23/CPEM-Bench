import csv
import time
import logging
import re
import os
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright


# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('crawler2_log.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def _sanitize_windows_path_component(name: str) -> str:
    """Sanitize a string for use as a Windows file/folder name component."""
    if name is None:
        return "unknown"

    cleaned = str(name).replace("\ufeff", "").strip()
    cleaned = re.sub(r"[\x00-\x1f]", "", cleaned)  # control chars
    cleaned = cleaned.replace("/", "_").replace("\\", "_")
    cleaned = cleaned.replace("?", "").replace("*", "")
    cleaned = cleaned.replace('"', "").replace("<", "").replace(">", "")
    cleaned = cleaned.replace(":", "_").replace("|", "_")
    cleaned = re.sub(r"[ _]{2,}", "_", cleaned)
    cleaned = cleaned.strip().strip(".").strip().rstrip(". ")
    return cleaned or "unknown"


def ExtractDisease(csv_path: str | Path = 'diseases.csv'):
    csv_path = Path(csv_path)
    with open(csv_path, mode='r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        diseases = []
        for i, row in enumerate(reader):
            if row:
                line = (row[0] or '').strip()
                if not line:
                    continue
                # 兼容中英文括号，去除 OMIM 等附加信息
                if "(" in line:
                    name = line.split("(")[0].strip()
                elif "（" in line:
                    name = line.split("（")[0].strip()
                else:
                    name = line.strip()
                diseases.append({'id': i + 1, 'name': name})
    return diseases


class MedicalLiteratureCrawler2:
    def __init__(self, browser_path=None, headless=True, save_dir: str | Path = 'disease_paper2'):
        self.browser_path = browser_path
        self.results = []
        self.errors = []
        self.headless = headless
        self.default_navigation_timeout = 40000
        self.default_action_timeout = 25000
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)

    def setup_browser(self, playwright):
        kwargs = {
            'headless': self.headless,
            'args': [
                '--disable-gpu',
                '--disable-dev-shm-usage',
                '--disable-setuid-sandbox',
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--window-position=0,0',
                '--ignore-certificate-errors',
                '--ignore-certificate-errors-spki-list',
            ]
        }
        if self.browser_path:
            kwargs['executable_path'] = self.browser_path
        browser = playwright.chromium.launch(**kwargs)
        return browser

    def safe_wait_for_load_state(self, page, state='networkidle', timeout=None):
        try:
            use_timeout = timeout if timeout is not None else self.default_navigation_timeout
            page.wait_for_load_state(state, timeout=use_timeout)
            return True
        except Exception:
            try:
                page.wait_for_load_state('domcontentloaded', timeout=15000)
                return True
            except Exception:
                try:
                    page.wait_for_timeout(2000)
                except Exception:
                    pass
                return False

    def search_on_yiigle(self, page, disease_name):
        try:
            logger.info(f"正在搜索疾病: {disease_name}")
            
            self.safe_wait_for_load_state(page, 'networkidle')
            time.sleep(1)
            
            # 查找搜索框并输入
            search_box = page.get_by_role('textbox', name='主题/文题/作者/刊名')
            if not search_box.count() > 0:
                search_box = page.locator('input[type="text"], input[placeholder*="主题"], input[placeholder*="搜索"]').first
            
            # 清空并输入搜索词
            search_box.click()
            search_box.press("ControlOrMeta+a")
            search_box.fill(disease_name)
            
            # 点击搜索按钮
            search_button = page.get_by_role('button', name='搜索')
            if not search_button.count() > 0:
                search_button = page.locator('button:has-text("搜索")').first
            
            search_button.click()
            
            # 等待搜索结果加载
            page.wait_for_timeout(4000)
            self.safe_wait_for_load_state(page, 'networkidle')
            page.wait_for_timeout(3000)
            
            # 检查是否有搜索结果
            try:
                no_result_texts = ['没有找到', '未找到', '无结果', '0 条结果']
                for text in no_result_texts:
                    no_result = page.get_by_text(text)
                    if no_result.count() > 0:
                        logger.warning(f"搜索 '{disease_name}' 没有找到结果")
                        return True
            except Exception:
                pass
                
            return True
            
        except Exception as e:
            self.errors.append({'disease': disease_name, 'error': str(e), 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
            logger.error(f"搜索疾病 '{disease_name}' 失败: {e}")
            return False

    def extract_top_results(self, page, max_results=2):
        results = []
        try:
            page.wait_for_timeout(3000)
            
            result_selectors = [
                '.s_searchResult_li',
                '.search-result-item',
                '.result-item',
                '.article-item',
                '.list-item',
                'div[class*="result"]',
                'div[class*="item"]:has(a)'
            ]
            
            for selector in result_selectors:
                try:
                    result_items = page.locator(selector).all()
                    if result_items and len(result_items) > 0:
                        logger.info(f"使用选择器 '{selector}' 找到 {len(result_items)} 个结果")
                        
                        for item in result_items[:max_results]:
                            try:
                                title_link = item.locator('a').first
                                if title_link.count() > 0:
                                    title = title_link.inner_text().strip()
                                    href = title_link.get_attribute('href')
                                    
                                    if title and len(title) > 5:
                                        if not href:
                                            href = title_link.get_attribute('onclick')
                                            if href and 'href' in href:
                                                match = re.search(r"href\s*=\s*['\"]([^'\"]+)['\"]", href)
                                                if match:
                                                    href = match.group(1)
                                        
                                        results.append({
                                            'title': title,
                                            'href': href if href else '',
                                            'text': title
                                        })
                                        logger.info(f"找到结果: {title}")
                                else:
                                    title_text = item.inner_text().strip()
                                    if title_text and len(title_text) > 10:
                                        results.append({
                                            'title': title_text,
                                            'href': '',
                                            'text': title_text
                                        })
                            except Exception as e:
                                logger.debug(f"提取单个结果失败: {e}")
                                continue
                        
                        if results:
                            break
                except Exception as e:
                    logger.debug(f"选择器 '{selector}' 失败: {e}")
                    continue
            
            if not results:
                logger.info("尝试通用方法查找结果...")
                try:
                    all_links = page.locator('a').all()
                    for link in all_links[:50]:
                        try:
                            text = link.inner_text().strip()
                            if (text and 10 <= len(text) <= 200 and 
                                '搜索' not in text and '登录' not in text and 
                                '注册' not in text and '首页' not in text):
                                href = link.get_attribute('href')
                                results.append({
                                    'title': text,
                                    'href': href if href else '',
                                    'text': text
                                })
                                if len(results) >= max_results:
                                    break
                        except Exception:
                            continue
                except Exception as e:
                    logger.debug(f"通用方法失败: {e}")
            
            logger.info(f"总共找到 {len(results)} 个结果")
            return results
            
        except Exception as e:
            logger.error(f'提取搜索结果失败: {e}')
            return results

    def extract_title_from_detail(self, page):
        """从详情页提取题目"""
        try:
            selectors = [
                'h1',
                '.article-title',
                '.title',
                '.paper-title',
                'header h1',
                '.detail-title',
                '[class*="title"]'
            ]
            
            for selector in selectors:
                try:
                    title_elem = page.locator(selector).first
                    if title_elem.count() > 0:
                        title = title_elem.inner_text().strip()
                        if title and len(title) > 5:
                            logger.info(f"使用选择器 '{selector}' 找到题目: {title}")
                            return title
                except Exception:
                    continue
            
            try:
                meta_title = page.locator('meta[name="citation_title"], meta[property="og:title"]').first
                if meta_title.count() > 0:
                    title = meta_title.get_attribute('content')
                    if title:
                        logger.info(f"从meta标签找到题目: {title}")
                        return title.strip()
            except Exception:
                pass
                
            return "未找到题目"
        except Exception as e:
            logger.error(f"提取题目失败: {e}")
            return "提取题目失败"

    def extract_abstract_from_detail(self, page):
        """从详情页提取摘要"""
        try:
            logger.info("开始提取摘要...")
            
            keywords = ['ABSTRACT', '摘要', 'Abstract']
            
            for keyword in keywords:
                try:
                    elements = page.locator(f':text("{keyword}")').all()
                    
                    for elem in elements:
                        try:
                            parent = elem.evaluate_handle('(elem) => elem.parentElement')
                            if parent:
                                parent_text = parent.inner_text()
                                pattern = re.compile(f'{keyword}[\\s:：]*([\\s\\S]+?)(?:\\n\\n|$)', re.IGNORECASE)
                                match = pattern.search(parent_text)
                                if match:
                                    abstract = match.group(1).strip()
                                    if len(abstract) > 50:
                                        logger.info(f"从'{keyword}'找到摘要，长度: {len(abstract)}")
                                        return abstract
                        except Exception:
                            continue
                except Exception:
                    continue
            
            abstract_selectors = [
                '.abstract',
                '.abstract-content',
                '.article-abstract',
                '.zhaiyao',
                '[class*="abstract"]',
                '[class*="Abstract"]',
                '.summary',
                '.content'
            ]
            
            for selector in abstract_selectors:
                try:
                    abstract_elem = page.locator(selector).first
                    if abstract_elem.count() > 0:
                        abstract_text = abstract_elem.inner_text().strip()
                        if abstract_text and len(abstract_text) > 50:
                            logger.info(f"使用选择器 '{selector}' 找到摘要，长度: {len(abstract_text)}")
                            return abstract_text
                except Exception:
                    continue
            
            try:
                meta_abstract = page.locator('meta[name="citation_abstract"], meta[name="description"], meta[property="og:description"]').all()
                for meta in meta_abstract:
                    try:
                        content = meta.get_attribute('content')
                        if content and len(content) > 50:
                            logger.info(f"从meta标签找到摘要，长度: {len(content)}")
                            return content.strip()
                    except Exception:
                        continue
            except Exception:
                pass
            
            try:
                main_content = page.locator('article, .article-content, .main-content, .content').first
                if main_content.count() > 0:
                    content_text = main_content.inner_text().strip()
                    if content_text and len(content_text) > 100:
                        abstract = content_text[:500] + ('...' if len(content_text) > 500 else '')
                        logger.info(f"从主要内容提取摘要，长度: {len(abstract)}")
                        return abstract
            except Exception:
                pass
            
            logger.warning("未找到摘要")
            return "未找到摘要"
            
        except Exception as e:
            logger.error(f"提取摘要失败: {e}")
            return f"提取摘要失败: {e}"

    def download_pdf_from_detail(self, page):
        """下载PDF"""
        try:
            logger.info("尝试下载PDF...")
            
            page.wait_for_timeout(2000)
            
            # 先点击PDF下载（如果有的话）
            try:
                pdf_download_link = page.locator('[id="__layout"]').get_by_text('PDF下载')
                if pdf_download_link.count() > 0 and pdf_download_link.is_visible():
                    logger.info("点击 'PDF下载' 链接")
                    pdf_download_link.click()
                    page.wait_for_timeout(1500)
            except Exception:
                pass
            
            download_strategies = [
                {'role': 'button', 'name': '下载PDF', 'exact': True},
                {'role': 'button', 'name': '下载PDF', 'exact': False},
                {'selector': '.iconfont.icon-google-drive-pdf-file'},
                {'text': 'PDF下载'},
                {'text': '下载'},
                {'text': 'Download PDF'},
                {'text': 'Download'}
            ]
            
            for strategy in download_strategies:
                try:
                    if 'role' in strategy:
                        if strategy.get('exact', False):
                            download_btn = page.get_by_role(strategy['role'], name=strategy['name'], exact=True)
                        else:
                            download_btn = page.get_by_role(strategy['role'], name=strategy['name'])
                        
                        if download_btn.count() > 0:
                            for i in range(download_btn.count()):
                                try:
                                    btn = download_btn.nth(i)
                                    if btn.is_visible():
                                        logger.info(f"找到并点击 {strategy} 按钮")
                                        with page.expect_download(timeout=30000) as download_info:
                                            btn.click()
                                        download = download_info.value
                                        return download
                                except Exception:
                                    continue
                    
                    elif 'selector' in strategy:
                        icon = page.locator(strategy['selector'])
                        if icon.count() > 0 and icon.is_visible():
                            logger.info(f"找到并点击 {strategy['selector']} 图标")
                            icon.click()
                            page.wait_for_timeout(1000)
                            
                            try:
                                download_btn = page.get_by_role('button', name='下载PDF')
                                if download_btn.count() > 0 and download_btn.is_visible():
                                    with page.expect_download(timeout=30000) as download_info:
                                        download_btn.click()
                                    download = download_info.value
                                    return download
                            except Exception:
                                pass
                    
                    elif 'text' in strategy:
                        download_link = page.get_by_text(strategy['text'])
                        if download_link.count() > 0:
                            for i in range(download_link.count()):
                                try:
                                    elem = download_link.nth(i)
                                    if elem.is_visible():
                                        logger.info(f"找到并点击 '{strategy['text']}' 文本")
                                        with page.expect_download(timeout=30000) as download_info:
                                            elem.click()
                                        download = download_info.value
                                        return download
                                except Exception:
                                    continue
                    
                except Exception as e:
                    logger.debug(f"下载策略 {strategy} 失败: {e}")
                    continue
            
            logger.warning("未找到可用的PDF下载方式")
            return None
            
        except Exception as e:
            logger.error(f"下载PDF失败: {e}")
            return None

    def process_disease(self, page, context, disease, max_results=2):
        disease_name = disease['name']
        disease_id = disease['id']
        result = {'disease': disease_name, 'id': disease_id, 'details': []}
        
        logger.info(f"开始处理疾病: {disease_name} (ID: {disease_id})")
        
        # 搜索疾病
        if not self.search_on_yiigle(page, disease_name):
            logger.error(f"搜索疾病 '{disease_name}' 失败")
            return result
        
        # 提取搜索结果
        search_results = self.extract_top_results(page, max_results=max_results)
        if not search_results:
            logger.warning(f"未找到疾病 '{disease_name}' 的搜索结果")
            return result
        
        logger.info(f"找到 {len(search_results)} 个结果，开始处理...")
        
        # 处理每个结果
        for i, result_item in enumerate(search_results):
            try:
                logger.info(f"处理第 {i+1} 个结果: {result_item['title']}")
                
                # 创建保存目录
                safe_disease_name = _sanitize_windows_path_component(disease_name)
                # 目录命名参考 paper/part3/website2：{id}_{disease}
                disease_dir = self.save_dir / f"{disease_id}_{safe_disease_name}"
                disease_dir.mkdir(parents=True, exist_ok=True)
                
                # 点击进入详情页
                try:
                    with page.expect_popup(timeout=15000) as popup_info:
                        page.get_by_text(result_item['text']).first.click()
                    
                    detail_page = popup_info.value
                    detail_page.wait_for_load_state('domcontentloaded')
                    detail_page.wait_for_timeout(3000)
                    
                    # 提取题目
                    title = self.extract_title_from_detail(detail_page)
                    if title == "未找到题目":
                        title = result_item['title']

                    safe_title = _sanitize_windows_path_component(title)
                    
                    # 提取摘要
                    abstract = self.extract_abstract_from_detail(detail_page)
                    
                    # 保存题目和摘要到txt文件
                    txt_filename = f"{disease_id}_{safe_disease_name}_{safe_title}.txt"
                    txt_path = disease_dir / txt_filename
                    
                    with open(txt_path, 'w', encoding='utf-8') as f:
                        f.write(f"疾病名称: {disease_name}\n")
                        f.write(f"疾病ID: {disease_id}\n")
                        f.write(f"题目: {title}\n")
                        f.write(f"摘要: {abstract}\n")
                        f.write(f"来源URL: {detail_page.url}\n")
                        f.write(f"提取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    
                    logger.info(f"已保存txt文件: {txt_path}")
                    
                    # 下载PDF
                    pdf_path = None
                    try:
                        pdf_filename = f"{disease_id}_{safe_disease_name}_{safe_title}.pdf"
                        pdf_path = disease_dir / pdf_filename
                        
                        # 下载PDF
                        download = self.download_pdf_from_detail(detail_page)
                        
                        if download:
                            # 直接保存到目标目录
                            download.save_as(str(pdf_path))
                            logger.info(f"已保存PDF文件: {pdf_path}")
                            pdf_path = str(pdf_path)
                        else:
                            logger.warning("未能下载PDF文件")
                    except Exception as e:
                        logger.error(f"下载PDF失败: {e}")
                    
                    # 关闭详情页
                    detail_page.close()
                    
                    # 记录结果
                    detail_info = {
                        'title': title,
                        'abstract': abstract[:200] + '...' if len(abstract) > 200 else abstract,
                        'txt_file': str(txt_path),
                        'pdf_file': pdf_path
                    }
                    result['details'].append(detail_info)
                    
                except Exception as e:
                    logger.error(f"处理详情页失败: {e}")
                    try:
                        safe_title_basic = _sanitize_windows_path_component(result_item.get('title', 'untitled'))
                        txt_filename = f"{disease_id}_{safe_disease_name}_{safe_title_basic}_basic.txt"
                        txt_path = disease_dir / txt_filename
                        with open(txt_path, 'w', encoding='utf-8') as f:
                            f.write(f"疾病名称: {disease_name}\n")
                            f.write(f"疾病ID: {disease_id}\n")
                            f.write(f"题目: {result_item['title']}\n")
                            f.write(f"状态: 无法访问详情页\n")
                            f.write(f"错误: {str(e)[:200]}\n")
                        logger.info(f"已保存基本信息文件: {txt_path}")
                    except Exception:
                        pass
                    continue
                
            except Exception as e:
                logger.error(f"处理结果 {i+1} 失败: {e}")
                continue
        
        return result

    def run(self, diseases, browser_path=None, start=0):
        if browser_path:
            self.browser_path = browser_path

        with sync_playwright() as p:
            browser = self.setup_browser(p)
            context = browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                accept_downloads=True
            )
            
            context.set_default_timeout(self.default_action_timeout)
            context.set_default_navigation_timeout(self.default_navigation_timeout)
            
            page = context.new_page()
            try:
                # 打开首页
                logger.info("正在打开医脉通首页...")
                page.goto('https://www.yiigle.com/index', wait_until='networkidle')
                page.wait_for_timeout(3000)
                
                # 处理疾病（i 为疾病在原列表中的序号，从 1 开始）
                for i, disease in enumerate(diseases[start:], start=start + 1):
                    logger.info(f"[{i}] 处理疾病: {disease['name']}")
                    print(f"[{i}] 处理: {disease['name']}")
                    
                    try:
                        res = self.process_disease(page, context, disease, max_results=2)
                        self.results.append(res)
                    except Exception as e:
                        logger.error(f"处理疾病 {disease['name']} 时出错: {e}")
                        self.errors.append({
                            'disease': disease['name'],
                            'error': str(e),
                            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        })
                    
                    time.sleep(3)
                
                # 保存最终结果
                if self.results:
                    result_path = self.save_dir / 'crawler2_results.csv'
                    with open(result_path, 'w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=['disease', 'id', 'details'])
                        writer.writeheader()
                        writer.writerows(self.results)
                    logger.info(f"已保存结果到: {result_path}")
                
            except Exception as e:
                logger.error(f"运行爬虫时发生错误: {e}")
            finally:
                # 保存错误信息
                if self.errors:
                    err_path = self.save_dir / 'errors_crawler2.csv'
                    with open(err_path, 'w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=['disease', 'error', 'time'])
                        writer.writeheader()
                        writer.writerows(self.errors)
                    logger.info(f"已保存错误信息到: {err_path}")
                
                browser.close()


def run():
    # 1) 需要爬取的 part 与对应 CSV
    parts_to_crawl = {
        1: Path('csv') / 'diseases_part1.csv',
        2: Path('csv') / 'diseases_part2.csv',
        4: Path('csv') / 'diseases_part4.csv',
    }

    # 2) 浏览器路径
    browser_path = r"D:\playwright_browsers\chromium-1200\chrome-win64\chrome.exe"

    # 3) 逐个 part 爬取，并将结果落到 paper/part{n}/website2
    start_by_part = {
        1: 0,
        2: 0,
        4: 0,
    }
    for part, csv_path in parts_to_crawl.items():
        diseases = ExtractDisease(csv_path)
        save_dir = Path('paper') / f"part{part}" / 'website2'
        crawler = MedicalLiteratureCrawler2(headless=True, save_dir=save_dir)
        crawler.run(diseases, browser_path=browser_path, start=start_by_part.get(part, 0))


if __name__ == '__main__':
    run()