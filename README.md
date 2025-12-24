# DNS IPv6 解析爬虫

从 [antping.com/dns](https://antping.com/dns) 网站批量获取域名的 IPv6 (AAAA记录) 解析结果。

## 功能特点

- **自动化操作**：使用 Playwright 模拟浏览器访问
- **AAAA记录查询**：自动选择 IPv6 记录类型进行查询
- **代理支持**：支持 HTTP 代理（如 Clash/V2Ray）
- **断点续传**：IP被封或中断后，重启可从上次位置继续
- **智能等待**：等待 Loading 完成后再提取结果
- **详细日志**：同时输出到控制台和日志文件

## 安装依赖

```bash
# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install openpyxl pandas playwright

# 安装浏览器
playwright install chromium
```

## 使用方法

### 1. 准备 Excel 文件

Excel 文件需要包含"域名"列（第一列），示例：

| 域名 | 企业名称 | ... |
|------|----------|-----|
| example.com | XX公司 | ... |

### 2. 修改配置

编辑 `dns_ipv6_crawler.py` 文件末尾的 `main()` 函数：

```python
crawler = DNSIPv6Crawler(
    excel_path,           # Excel文件路径
    headless=False,       # True=后台运行, False=显示浏览器
    use_proxy=True,       # 是否使用代理
    proxy_host="127.0.0.1",
    proxy_port=7890,
    requests_per_ip=10    # 每个IP处理的请求数
)

await crawler.run(
    start_index=0,        # 起始索引
    end_index=None,       # 结束索引，None表示全部
    resume=True           # 是否从上次中断处继续
)
```

### 3. 运行爬虫

```bash
./venv/bin/python3 dns_ipv6_crawler.py
```

## 断点续传

当遇到以下情况时，爬虫会自动保存进度：
- IP 被封禁（24小时限制）
- 用户按 Ctrl+C 中断
- 程序异常退出

进度保存在 `域名资产数据_2025-12-23_progress.json` 文件中。

重新运行爬虫时，设置 `resume=True` 会自动从上次中断处继续。

## 输出文件

- **结果文件**：`域名资产数据_2025-12-23_with_ipv6.xlsx`
- **进度文件**：`域名资产数据_2025-12-23_progress.json`
- **日志文件**：`dns_crawler_YYYYMMDD_HHMMSS.log`

## 代理配置

如果使用 Clash/V2Ray 等代理软件，需要添加规则让 antping.com 走代理：

```
DOMAIN-SUFFIX,antping.com,代理节点
```

## 注意事项

1. antping.com 有请求频率限制，IP 被封后需要等待24小时或更换IP
2. 建议使用代理并定期切换节点
3. 每个域名查询需要等待 DNS 全球节点响应，约 10-30 秒

## License

MIT
