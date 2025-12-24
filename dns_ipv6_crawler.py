#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DNS IPv6 解析爬虫
从 antping.com/dns 网站获取域名的 IPv6 (AAAA记录) 解析结果

优化策略：
- 保持单个页面，直接修改输入框内容进行查询
- 不重复加载页面，提高效率
- 添加详细日志记录
"""

import asyncio
import re
import time
import json
import ipaddress
import logging
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright
import openpyxl
from openpyxl.utils import get_column_letter

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(f'dns_crawler_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class DNSIPv6Crawler:
    def __init__(self, excel_path: str, headless: bool = True, use_proxy: bool = True, 
                 proxy_host: str = "127.0.0.1", proxy_port: int = 7890,
                 requests_per_ip: int = 10):
        self.excel_path = excel_path
        self.headless = headless
        self.base_url = "https://antping.com/dns"
        self.results = {}
        self.page_initialized = False  # 标记页面是否已初始化（选择了AAAA记录类型）
        
        # 代理配置
        self.use_proxy = use_proxy
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.proxy_url = f"http://{proxy_host}:{proxy_port}" if use_proxy else None
        
        # IP切换配置
        self.requests_per_ip = requests_per_ip  # 每个IP处理的请求数
        self.current_request_count = 0  # 当前IP已处理的请求数
        
        # 断点续传配置
        self.progress_file = excel_path.replace('.xlsx', '_progress.json')
        self.last_failed_index = None  # 记录失败时的索引
        
        # Clash API配置（用于切换节点）
        self.clash_api_url = "http://127.0.0.1:9090"
        self.clash_secret = ""  # 如果有密码，填写这里
        self.proxy_group = "🔰 节点选择"  # 代理组名称
        
    def check_proxy_available(self) -> bool:
        """检查代理是否可用"""
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((self.proxy_host, self.proxy_port))
        sock.close()
        return result == 0
    
    def get_clash_proxies(self) -> list:
        """获取Clash可用的代理节点列表"""
        import urllib.request
        try:
            url = f"{self.clash_api_url}/proxies/{urllib.parse.quote(self.proxy_group)}"
            headers = {}
            if self.clash_secret:
                headers['Authorization'] = f'Bearer {self.clash_secret}'
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                # 过滤掉非节点的选项
                all_proxies = data.get('all', [])
                valid_proxies = [p for p in all_proxies if not any(x in p for x in ['流量', '套餐', '重置', '直连', '自动', '故障'])]
                return valid_proxies
        except Exception as e:
            logger.warning(f"获取Clash代理列表失败: {e}")
            return []
    
    def switch_clash_proxy(self, proxy_name: str) -> bool:
        """切换Clash代理节点"""
        import urllib.request
        import urllib.parse
        try:
            url = f"{self.clash_api_url}/proxies/{urllib.parse.quote(self.proxy_group)}"
            headers = {'Content-Type': 'application/json'}
            if self.clash_secret:
                headers['Authorization'] = f'Bearer {self.clash_secret}'
            
            data = json.dumps({'name': proxy_name}).encode('utf-8')
            req = urllib.request.Request(url, data=data, headers=headers, method='PUT')
            with urllib.request.urlopen(req, timeout=5) as response:
                logger.info(f"已切换到代理节点: {proxy_name}")
                return True
        except Exception as e:
            logger.warning(f"切换Clash代理失败: {e}")
            return False
    
    def get_next_proxy(self) -> str:
        """获取下一个代理节点"""
        proxies = self.get_clash_proxies()
        if not proxies:
            return None
        
        # 随机选择一个节点
        import random
        return random.choice(proxies)
        
    async def init_browser(self):
        """初始化浏览器（无痕模式+随机指纹）"""
        logger.info("正在启动浏览器（无痕模式）...")
        self.playwright = await async_playwright().start()
        
        # 配置代理
        launch_options = {"headless": self.headless}
        
        # 无痕模式 + 随机指纹配置
        import random
        user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
        ]
        
        viewports = [
            {"width": 1920, "height": 1080},
            {"width": 1440, "height": 900},
            {"width": 1536, "height": 864},
            {"width": 1366, "height": 768},
        ]
        
        context_options = {
            "user_agent": random.choice(user_agents),
            "viewport": random.choice(viewports),
            "locale": random.choice(["zh-CN", "zh-TW", "en-US"]),
            "timezone_id": random.choice(["Asia/Shanghai", "Asia/Hong_Kong", "Asia/Taipei"]),
        }
        
        if self.use_proxy:
            if self.check_proxy_available():
                context_options["proxy"] = {"server": self.proxy_url}
                logger.info(f"使用代理: {self.proxy_url}")
            else:
                logger.warning(f"代理 {self.proxy_url} 不可用，将不使用代理")
                self.use_proxy = False
        
        self.browser = await self.playwright.chromium.launch(**launch_options)
        # 使用 new_context 创建无痕浏览上下文（Playwright默认就是无痕的）
        self.context = await self.browser.new_context(**context_options)
        self.page = await self.context.new_page()
        logger.info(f"浏览器启动成功，UA: {context_options['user_agent'][:50]}...")
        
    async def restart_browser_for_new_ip(self):
        """重启浏览器并切换代理节点"""
        logger.info("=" * 40)
        logger.info(f"已处理 {self.requests_per_ip} 个请求，切换代理节点...")
        logger.info("=" * 40)
        
        # 尝试通过Clash API切换节点
        next_proxy = self.get_next_proxy()
        if next_proxy:
            self.switch_clash_proxy(next_proxy)
            await asyncio.sleep(2)  # 等待切换生效
        else:
            logger.warning("无法获取代理节点列表，将继续使用当前节点")
        
        # 关闭当前浏览器
        await self.context.close()
        await self.browser.close()
        
        # 等待一段时间
        logger.info("等待3秒...")
        await asyncio.sleep(3)
        
        # 重新初始化浏览器
        context_options = {}
        if self.use_proxy and self.check_proxy_available():
            context_options["proxy"] = {"server": self.proxy_url}
            
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(**context_options)
        self.page = await self.context.new_page()
        
        # 重置状态
        self.page_initialized = False
        self.current_request_count = 0
        
        logger.info("浏览器已重启，继续爬取...")
        
    async def close_browser(self):
        """关闭浏览器"""
        logger.info("正在关闭浏览器...")
        await self.context.close()
        await self.browser.close()
        await self.playwright.stop()
        logger.info("浏览器已关闭")
        
    def read_domains_from_excel(self) -> list:
        """从Excel读取域名列表"""
        wb = openpyxl.load_workbook(self.excel_path)
        ws = wb.active
        domains = []
        for row in ws.iter_rows(min_row=2, max_col=1):
            domain = row[0].value
            if domain:
                domains.append(domain.strip())
        wb.close()
        return domains
    
    def save_progress(self, current_index: int, results: dict):
        """保存当前进度到文件"""
        progress_data = {
            'last_index': current_index,
            'timestamp': datetime.now().isoformat(),
            'results': results
        }
        with open(self.progress_file, 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
        logger.info(f"进度已保存到: {self.progress_file} (索引: {current_index})")
    
    def load_progress(self) -> tuple:
        """加载之前的进度"""
        if Path(self.progress_file).exists():
            try:
                with open(self.progress_file, 'r', encoding='utf-8') as f:
                    progress_data = json.load(f)
                last_index = progress_data.get('last_index', 0)
                results = progress_data.get('results', {})
                timestamp = progress_data.get('timestamp', '')
                logger.info(f"找到进度文件，上次停止于索引 {last_index}，时间: {timestamp}")
                return last_index, results
            except Exception as e:
                logger.warning(f"加载进度文件失败: {e}")
        return 0, {}
    
    def is_valid_ipv6(self, addr: str) -> bool:
        """验证是否是有效的IPv6地址"""
        try:
            # 过滤掉太短的地址（真实IPv6地址至少有15个字符，如 ::1 这种极端情况除外）
            if len(addr) < 10:
                return False
            # 排除一些明显不是IPv6的模式
            if addr.endswith('::') and len(addr) < 15:
                return False
            ipaddress.IPv6Address(addr)
            return True
        except:
            return False
    
    def extract_ipv6_addresses(self, text: str) -> set:
        """从文本中提取所有有效的IPv6地址"""
        # 更精确的IPv6地址正则表达式
        # 主要匹配类似 240e:6b0:ab0:11:1::1086 这种格式
        # 要求至少有3个冒号分隔的部分
        ipv6_pattern = r'\b([0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{0,4}){2,7})\b'
        
        matches = re.findall(ipv6_pattern, text)
        valid_ipv6 = set()
        
        for match in matches:
            # 额外验证：必须包含至少3个冒号
            if match.count(':') >= 3 and self.is_valid_ipv6(match):
                valid_ipv6.add(match)
        
        return valid_ipv6
    
    async def wait_for_loading_complete(self, timeout: int = 10):
        """等待页面加载动画消失"""
        try:
            # 等待spinner消失
            spinner = self.page.locator('.ant-spin-spinning')
            await spinner.wait_for(state="hidden", timeout=timeout * 1000)
        except:
            pass  # 如果没有spinner或已经消失，继续
        await asyncio.sleep(0.3)
    
    async def init_page_for_aaaa(self):
        """初始化页面，导航并选择AAAA记录类型（只执行一次）"""
        logger.info("正在初始化DNS查询页面...")
        
        # 导航到DNS查询页面（使用domcontentloaded而不是networkidle，更快）
        await self.page.goto(self.base_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)
        
        # 选择AAAA记录类型（使用force=True强制点击，忽略遮挡）
        logger.info("选择AAAA记录类型...")
        dropdown = self.page.locator('div').filter(has_text=re.compile(r'^A$')).nth(1)
        await dropdown.click(force=True)
        await asyncio.sleep(0.5)
        
        # 选择AAAA选项
        await self.page.get_by_title('AAAA').click(force=True)
        await asyncio.sleep(0.5)
        
        self.page_initialized = True
        logger.info("页面初始化完成，已选择AAAA记录类型")
    
    async def check_if_blocked(self) -> bool:
        """检查是否被封禁（24小时限制）"""
        try:
            content = await self.page.content()
            if "请求次数超过限制" in content or "24小时后重试" in content:
                return True
        except:
            pass
        return False
    
    async def query_ipv6(self, domain: str, max_retries: int = 3) -> list:
        """查询单个域名的IPv6地址（优化版：直接修改输入框，不重新加载页面）"""
        ipv6_list = []
        
        for attempt in range(max_retries):
            try:
                # 如果页面未初始化，先初始化
                if not self.page_initialized:
                    await self.init_page_for_aaaa()
                
                # 检查是否被封（24小时限制）
                if await self.check_if_blocked():
                    logger.warning("检测到IP被封禁，尝试切换代理节点...")
                    
                    # 尝试切换节点
                    next_proxy = self.get_next_proxy()
                    if next_proxy:
                        self.switch_clash_proxy(next_proxy)
                        await asyncio.sleep(3)
                        
                        # 重新加载页面
                        self.page_initialized = False
                        await self.init_page_for_aaaa()
                        
                        # 再次检查是否被封
                        if await self.check_if_blocked():
                            logger.error("=" * 60)
                            logger.error("切换节点后仍被封禁，停止爬虫！")
                            logger.error("请手动更换代理节点或等待24小时后再试")
                            logger.error("=" * 60)
                            raise Exception("IP_BLOCKED_24H")
                        else:
                            logger.info("切换节点成功，继续爬取...")
                    else:
                        logger.error("=" * 60)
                        logger.error("检测到IP被封禁（24小时限制），且无法切换节点，停止爬虫！")
                        logger.error("请手动更换代理节点或等待24小时后再试")
                        logger.error("=" * 60)
                        raise Exception("IP_BLOCKED_24H")
                
                logger.debug(f"开始查询域名: {domain}")
                
                # 直接修改输入框内容（使用force=True强制操作）
                input_box = self.page.get_by_role('textbox', name='例：cn.bing.com')
                await input_box.click(force=True)
                await input_box.fill('')  # 先清空
                await input_box.fill(domain)
                await asyncio.sleep(0.3)
                
                # 点击开始测试
                await self.page.get_by_role('button', name='开始测试').click(force=True)
                logger.debug(f"已点击开始测试按钮")
                
                # 等待Loading遮罩消失（等待DNS查询完成）
                # 关键：必须等待进度条到100%或Loading消失
                start_time = time.time()
                max_wait = 120  # 最多等待120秒
                last_ipv6_count = 0
                stable_count = 0
                
                while time.time() - start_time < max_wait:
                    await asyncio.sleep(3)  # 每3秒检查一次
                    elapsed = time.time() - start_time
                    
                    try:
                        # 获取页面内容
                        content = await self.page.content()
                        
                        # 检查Loading是否还在
                        # 1. 检查Loading文字
                        # 2. 检查进度百分比（如果不是100%说明还在加载）
                        has_loading_text = 'Loading' in content
                        has_spinner = 'ant-spin-spinning' in content
                        
                        # 提取进度百分比
                        import re
                        progress_match = re.search(r'(\d+)%', content)
                        progress = int(progress_match.group(1)) if progress_match else 100
                        
                        is_loading = has_loading_text or has_spinner or (progress < 100)
                        
                        if is_loading:
                            logger.info(f"[{domain}] 等待 {elapsed:.0f}s, DNS查询进行中... (进度: {progress}%)")
                            continue
                        
                        # Loading完成后，再等待2秒确保数据渲染完成
                        await asyncio.sleep(2)
                        content = await self.page.content()
                        
                        # 提取IPv6地址
                        valid_ipv6 = self.extract_ipv6_addresses(content)
                        current_count = len(valid_ipv6)
                        
                        logger.debug(f"[{domain}] Loading完成，找到 {current_count} 个IPv6")
                        
                        if current_count > 0:
                            if current_count == last_ipv6_count:
                                stable_count += 1
                                # 如果连续2次检查结果稳定，认为加载完成
                                if stable_count >= 2:
                                    ipv6_list = list(valid_ipv6)
                                    logger.info(f"✓ [{domain}] 找到 {len(ipv6_list)} 个IPv6: {', '.join(ipv6_list[:3])}{'...' if len(ipv6_list) > 3 else ''}")
                                    break
                            else:
                                stable_count = 0
                                last_ipv6_count = current_count
                        else:
                            # 没有IPv6，检查是否显示无记录
                            if '0 个 IP' in content or '0个IP' in content:
                                logger.info(f"- [{domain}] 无IPv6记录")
                                break
                            # 可能还在渲染，继续等待
                            stable_count += 1
                            if stable_count >= 3:
                                logger.info(f"- [{domain}] 无IPv6记录（超时）")
                                break
                            
                    except Exception as e:
                        logger.warning(f"[{domain}] 检查结果时出错: {e}")
                
                # 如果循环结束但有结果，也返回
                if not ipv6_list and last_ipv6_count > 0:
                    content = await self.page.content()
                    valid_ipv6 = self.extract_ipv6_addresses(content)
                    ipv6_list = list(valid_ipv6)
                    if ipv6_list:
                        logger.info(f"✓ [{domain}] 找到 {len(ipv6_list)} 个IPv6地址")
                
                # 超时但没有结果
                if not ipv6_list and time.time() - start_time >= max_wait:
                    logger.warning(f"⚠ [{domain}] 查询超时（{max_wait}秒）")
                        
                break  # 成功完成，退出重试循环
                
            except Exception as e:
                logger.error(f"[{domain}] 尝试 {attempt + 1}/{max_retries} 失败: {e}")
                if attempt < max_retries - 1:
                    # 重置页面状态，下次重新初始化
                    self.page_initialized = False
                    await asyncio.sleep(3)
                    
        return ipv6_list
    
    def write_results_to_excel(self):
        """将结果写入Excel文件"""
        wb = openpyxl.load_workbook(self.excel_path)
        ws = wb.active
        
        # 找到或创建IPv6结果列
        # 原有的AAAA记录在第4列，我们在后面添加新列
        header_row = list(ws[1])
        
        # 找到最大的IPv6数量
        max_ipv6_count = max(len(ips) for ips in self.results.values()) if self.results else 0
        
        # 添加新的列标题（如果需要）
        # 从第15列开始添加（假设原有14列）
        start_col = 15  # O列开始
        
        # 添加列标题
        for i in range(max_ipv6_count):
            col_letter = get_column_letter(start_col + i)
            ws[f'{col_letter}1'] = f'实时IPv6_{i+1}'
        
        # 写入数据
        for row_idx, row in enumerate(ws.iter_rows(min_row=2, max_col=1), start=2):
            domain = row[0].value
            if domain and domain.strip() in self.results:
                ipv6_list = self.results[domain.strip()]
                for i, ipv6 in enumerate(ipv6_list):
                    col_letter = get_column_letter(start_col + i)
                    ws[f'{col_letter}{row_idx}'] = ipv6
        
        # 保存文件
        output_path = self.excel_path.replace('.xlsx', '_with_ipv6.xlsx')
        wb.save(output_path)
        wb.close()
        logger.info(f"结果已保存到: {output_path}")
        return output_path
    
    async def run(self, start_index: int = 0, end_index: int = None, resume: bool = True):
        """运行爬虫
        
        Args:
            start_index: 起始索引
            end_index: 结束索引
            resume: 是否从上次中断处继续
        """
        logger.info("=" * 60)
        logger.info("DNS IPv6 解析爬虫 - 开始运行")
        logger.info("=" * 60)
        
        # 读取域名
        domains = self.read_domains_from_excel()
        total = len(domains)
        logger.info(f"共读取到 {total} 个域名")
        
        # 尝试加载之前的进度
        if resume:
            saved_index, saved_results = self.load_progress()
            if saved_index > start_index:
                start_index = saved_index
                self.results = saved_results
                logger.info(f"从上次中断处继续，起始索引: {start_index}")
        
        # 处理范围
        if end_index is None:
            end_index = total
        domains_to_process = domains[start_index:end_index]
        logger.info(f"将处理第 {start_index + 1} 到第 {end_index} 个域名（共 {len(domains_to_process)} 个）")
        
        # 初始化浏览器
        await self.init_browser()
        
        success_count = 0
        fail_count = 0
        no_record_count = 0
        current_idx = start_index
        
        try:
            for idx, domain in enumerate(domains_to_process, start=start_index + 1):
                current_idx = idx
                
                # 检查是否需要切换IP
                if self.use_proxy and self.current_request_count >= self.requests_per_ip:
                    await self.restart_browser_for_new_ip()
                
                logger.info(f"[{idx}/{end_index}] 正在查询: {domain} (当前IP请求数: {self.current_request_count + 1}/{self.requests_per_ip})")
                query_start = time.time()
                
                ipv6_list = await self.query_ipv6(domain)
                self.results[domain] = ipv6_list
                self.current_request_count += 1
                
                query_time = time.time() - query_start
                
                if ipv6_list:
                    success_count += 1
                else:
                    no_record_count += 1
                
                logger.debug(f"[{domain}] 查询耗时: {query_time:.1f}秒")
                
                # 每处理10个域名保存一次中间结果
                if idx % 10 == 0:
                    logger.info(f"--- 进度: {idx}/{end_index} ({idx*100//end_index}%) | 成功: {success_count} | 无记录: {no_record_count} ---")
                    self.write_results_to_excel()
                
                # 添加请求间隔（避免被封）
                await asyncio.sleep(3)  # 每个请求间隔3秒
                
        except KeyboardInterrupt:
            logger.warning("用户中断，正在保存进度和结果...")
            self.save_progress(current_idx, self.results)
        except Exception as e:
            if "IP_BLOCKED_24H" in str(e):
                logger.error("因IP被封禁（24小时限制）而停止，正在保存进度...")
                self.save_progress(current_idx, self.results)
            else:
                logger.error(f"运行出错: {e}")
                fail_count += 1
                self.save_progress(current_idx, self.results)
        finally:
            # 保存最终结果
            output_path = self.write_results_to_excel()
            
            # 关闭浏览器
            await self.close_browser()
            
        logger.info("=" * 60)
        logger.info("爬虫运行完成!")
        logger.info(f"统计: 成功获取IPv6: {success_count} | 无IPv6记录: {no_record_count} | 失败: {fail_count}")
        logger.info(f"结果文件: {output_path}")
        logger.info("=" * 60)
        
        return output_path


async def main():
    excel_path = "/Users/rongjiale/workspace/all_fobrain/new-project/域名资产数据_2025-12-23.xlsx"
    
    # 创建爬虫实例
    # headless=False 可以看到浏览器操作过程，调试时使用
    # headless=True 后台运行，正式使用
    # use_proxy=True 使用本地代理
    # requests_per_ip=10 每10个请求切换一次IP
    crawler = DNSIPv6Crawler(
        excel_path, 
        headless=False,  # 设置为True可后台运行
        use_proxy=True,  # 使用代理
        proxy_host="127.0.0.1",
        proxy_port=7890,
        requests_per_ip=20  # 每20个请求切换IP
    )
    
    # 运行爬虫
    # resume=True 会自动从上次中断处继续
    # 如果想从头开始，设置 resume=False
    await crawler.run(start_index=0, end_index=None, resume=True)


if __name__ == "__main__":
    asyncio.run(main())
