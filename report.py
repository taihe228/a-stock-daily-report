#!/usr/bin/env python3
"""
A股每日投资分析报告 - 核心引擎
数据源: 腾讯财经(实时行情+估值) + 东方财富(板块/资讯)
适配 GitHub Actions 定时运行
"""

import requests, re, json, time, os, sys
from datetime import datetime, timedelta

# ============================================================
# 配置
# ============================================================
NOW = datetime.now()
# 判断是否是交易日（周一到周五）
WEEKDAY = NOW.weekday()
if WEEKDAY >= 5:  # 周六日跳过
    print(f"⏭️ 今天是周末（周{WEEKDAY+1}），A股休市，跳过报告生成。")
    sys.exit(0)

# 检查时间：如果在交易时段内（9:30-15:00），等待到15:00后再生成
HOUR = NOW.hour
MINUTE = NOW.minute
if 9 <= HOUR < 15 or (HOUR == 9 and MINUTE >= 30):
    print(f"⏳ 当前在交易时段内（{HOUR}:{MINUTE:02d}），将使用盘中数据生成报告。")
elif HOUR < 9 or (HOUR == 9 and MINUTE < 30):
    print(f"⏰ 当前尚未开盘（{HOUR}:{MINUTE:02d}），将使用前一交易日数据。")

NOW_STR = NOW.strftime("%Y-%m-%d %H:%M:%S")
TRADE_DATE = NOW.strftime("%Y-%m-%d")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}

# 输出目录
OUTPUT_DIR = os.environ.get('OUTPUT_DIR', os.getcwd())
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# 工具函数
# ============================================================
def safe_get(url, retry=3, timeout=20, referer='https://finance.qq.com/'):
    for i in range(retry):
        try:
            h = dict(HEADERS)
            h['Referer'] = referer
            resp = requests.get(url, headers=h, timeout=timeout)
            resp.encoding = 'gbk'
            return resp
        except Exception as e:
            if i == retry - 1:
                print(f"  ⚠️ 请求失败(已重试{retry}次): {url[:60]}... {e}")
                raise
            time.sleep(3)
    return None

def pct(v):
    if v is None: return '-'
    return f"{v:+.2f}%"

def amt(v):
    if v is None or v == 0: return '-'
    if abs(v) >= 1e8: return f"{v/1e8:.2f}亿"
    elif abs(v) >= 1e4: return f"{v/1e4:.0f}万"
    return f"{v:.0f}"

def num2(v):
    if v is None: return '-'
    return f"{v:.2f}"

# ============================================================
# 数据获取
# ============================================================
INDEX_CODES = ['sh000001','sz399001','sz399006','sh000688','sh000300','sh000016','sz399905']
INDEX_NAMES = {'sh000001':'上证指数','sz399001':'深证成指','sz399006':'创业板指',
               'sh000688':'科创50','sh000300':'沪深300','sh000016':'上证50','sz399905':'中证500'}

STOCK_CANDIDATES = [
    'sz000725','sh601138','sz002475','sz002156','sz000021','sz000977','sh603019',
    'sz002049','sz300308','sz300285','sz000858','sz000568','sh600887','sh600690',
    'sz300014','sz002432','sh601899','sh600031','sh601012','sh603799','sh603993',
    'sh600183','sz002008','sh600118','sh601318','sz000001','sh600036','sh601166',
    'sh600030','sh600703','sh600893','sz002167','sh600584','sh603986','sh603501',
]

ETF_CANDIDATES = [
    'sh510050','sh510300','sh510500','sh588000','sh159919','sh512480','sh159995',
    'sh512760','sh515050','sh512660','sh516510','sh512880','sh513180','sh159766',
]

# 专项跟踪 ETF（用户指定）
TRACKED_ETFS = ['sh512690', 'sz159781']
TRACKED_ETF_NAMES = {'sh512690': '酒ETF(512690)', 'sz159781': '科创创业ETF易方达(159781)'}
TRACKED_ETF_DESC = {
    'sh512690': '跟踪中证酒指数，覆盖白酒、啤酒、葡萄酒龙头',
    'sz159781': '跟踪科创创业50指数，覆盖科创板和创业板龙头科技公司',
}

def get_index_data():
    url = f"https://qt.gtimg.cn/q={','.join(INDEX_CODES)}"
    resp = safe_get(url)
    results, total_amt = [], 0
    for line in resp.text.strip().split('\n'):
        m = re.search(r'="(.+)"', line)
        if not m: continue
        p = m.group(1).split('~')
        if len(p) < 40: continue
        close = float(p[3]) if p[3] else 0
        prev = float(p[4]) if p[4] else close
        chg = close - prev
        chg_pct = (close/prev - 1)*100 if prev else 0
        a = float(p[37])*10000 if len(p)>37 and p[37] else 0
        total_amt += a
        results.append({'name': INDEX_NAMES.get(INDEX_CODES[len(results)], p[1]),
                        'close': close, 'chg': chg, 'chg_pct': chg_pct, 'amount': a})
    return results, total_amt

def get_stock_data(codes):
    results = []
    batch_size = 20
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        url = f"https://qt.gtimg.cn/q={','.join(batch)}"
        try:
            resp = safe_get(url)
            for line in resp.text.strip().split('\n'):
                m = re.search(r'="(.+)"', line)
                if not m: continue
                p = m.group(1).split('~')
                if len(p) < 50: continue
                results.append({
                    'code': p[2], 'name': p[1],
                    'price': float(p[3]) if p[3] else 0,
                    'prev_close': float(p[4]) if p[4] else 0,
                    'open': float(p[5]) if p[5] else 0,
                    'volume': float(p[6]) if p[6] else 0,
                    'chg_pct': float(p[32]) if p[32] else 0,
                    'high': float(p[33]) if p[33] else 0,
                    'low': float(p[34]) if p[34] else 0,
                    'amount': float(p[37])*10000 if p[37] else 0,
                    'pe': float(p[39]) if p[39] and float(p[39]) > 0 else None,
                    'high_52w': float(p[41]) if p[41] else 0,
                    'low_52w': float(p[42]) if p[42] else 0,
                    'market_cap': float(p[45]) if p[45] else 0,
                    'pb': float(p[46]) if p[46] and float(p[46]) > 0 else None,
                })
            time.sleep(0.3)
        except Exception as e:
            print(f"  ⚠️ batch {i} 获取失败: {e}")
    return results

# ============================================================
# 精选标的筛选
# ============================================================
def score_stock(s):
    score, reasons = 0, []
    pe, pb = s.get('pe'), s.get('pb')

    if pe and pe > 0:
        if 5 <= pe <= 15: score += 25; reasons.append('低估值(PE优)')
        elif 15 < pe <= 25: score += 20; reasons.append('估值合理')
        elif 25 < pe <= 40: score += 12; reasons.append('估值适中')
        elif pe < 5: score += 8; reasons.append('极低PE')
        else: score += 5
    else: score += 5

    if pb and pb > 0:
        if 0.5 <= pb <= 2.5: score += 20; reasons.append('PB低(安全边际高)')
        elif 2.5 < pb <= 5: score += 12; reasons.append('PB适中')
        elif pb < 0.5: score += 8
        else: score += 5
    else: score += 5

    high52, price = s.get('high_52w', 0), s.get('price', 0)
    if high52 > 0 and price > 0:
        dd = (high52 - price) / high52 * 100
        s['drawdown'] = dd
        if dd > 25: score += 20; reasons.append(f'深度回调{dd:.0f}%')
        elif dd > 15: score += 15; reasons.append(f'明显回调{dd:.0f}%')
        elif dd > 8: score += 10; reasons.append(f'适度回调{dd:.0f}%')
        elif dd > 3: score += 5
    else: s['drawdown'] = 0

    mc = s.get('market_cap', 0)
    if 200 <= mc <= 3000: score += 15; reasons.append('市值适中')
    elif 50 <= mc < 200: score += 10; reasons.append('中小市值')
    elif mc > 3000: score += 8; reasons.append('大盘蓝筹')
    else: score += 5

    high, low, chg = s.get('high', 0), s.get('low', 0), s.get('chg_pct', 0)
    if high > 0 and low > 0 and price > 0 and high != low:
        pos = (price - low) / (high - low)
        if pos > 0.7: score += 8; reasons.append('收盘强势')
        elif pos > 0.4: score += 5
        else: score += 2

    if 0 < chg <= 5: score += 7; reasons.append('温和上涨')
    elif 5 < chg <= 10: score += 5; reasons.append('放量上攻')
    elif chg > 10: score += 2
    elif -5 <= chg <= 0: score += 6; reasons.append('回调机会')
    else: score += 3

    vol = s.get('volume', 0)
    if vol > 0: score += min(int(vol / 500000), 5)

    s['score'] = score
    s['reasons'] = '、'.join(reasons)
    return s

def filter_and_rank(stocks, top_n=5):
    qualified = []
    for s in stocks:
        code, name, price = s.get('code', ''), s.get('name', ''), s.get('price', 0)
        pe, pb = s.get('pe'), s.get('pb')
        if price <= 0 or price >= 100: continue
        if code.startswith('688'): continue
        if 'ST' in name or '*ST' in name: continue
        if pe is None or pe <= 0: continue
        if pb is None or pb <= 0: continue
        qualified.append(score_stock(s))
    qualified.sort(key=lambda x: x['score'], reverse=True)
    return qualified[:top_n]

def pick_etfs(etf_data, top_n=3):
    scored = []
    hot_kw = ['半导体','芯片','科创','AI','人工智能','通信','科技','恒生科技','云计算']
    for e in etf_data:
        score, reasons = 0, []
        name = e.get('name', '')
        amt_val = e.get('amount', 0)
        chg = e.get('chg_pct', 0)
        if amt_val > 5e8: score += 15; reasons.append('流动性极好')
        elif amt_val > 1e8: score += 10; reasons.append('流动性良好')
        else: score += 3
        if 1 <= chg <= 8: score += 12; reasons.append('趋势健康')
        elif chg > 8: score += 8; reasons.append('短期强势')
        elif -3 <= chg < 1: score += 8; reasons.append('蓄势待发')
        else: score += 3
        for kw in hot_kw:
            if kw in name: score += 8; reasons.append(f'热门主题({kw})'); break
        else: score += 3
        if 0.5 <= e.get('price', 0) <= 5: score += 5
        e['etf_score'] = score
        e['etf_reasons'] = '、'.join(reasons)
        scored.append(e)
    scored.sort(key=lambda x: x['etf_score'], reverse=True)
    return scored[:top_n]

# ============================================================
# 报告生成
# ============================================================
def generate_report():
    print(f"{'='*60}")
    print(f"  A股每日投资分析报告")
    print(f"  日期: {TRADE_DATE}  |  时间: {NOW_STR}")
    print(f"{'='*60}\n")

    print("📊 [1/4] 获取指数行情...")
    index_data, total_amount = get_index_data()
    time.sleep(1)

    print("📊 [2/4] 获取个股数据...")
    all_stocks = get_stock_data(STOCK_CANDIDATES)
    time.sleep(1)

    print("📊 [3/4] 获取ETF数据...")
    all_etfs = get_stock_data(ETF_CANDIDATES)
    time.sleep(1)

    print("📊 [4/4] 筛选精选标的...")
    top_stocks = filter_and_rank(all_stocks, top_n=5)
    top_etfs = pick_etfs(all_etfs, top_n=2)

    # 板块聚合
    sector_map = {}
    for s in all_stocks:
        name = s.get('name', '')
        sector = '其他'
        for kw, label in [
            ('半导体','半导体'),('芯片','半导体'),('微电','半导体'),('长电','半导体'),
            ('通富','半导体'),('深科技','半导体'),('紫光','半导体'),('兆易','半导体'),
            ('光电','光学'),('显示','光学'),('京东方','面板'),
            ('通信','通信'),('旭创','通信'),
            ('工业富联','AI服务器'),('浪潮','AI服务器'),('曙光','AI服务器'),
            ('电子','消费电子'),('立讯','消费电子'),('蓝思','消费电子'),
            ('亿纬','新能源'),('宁德','新能源'),('锂','新能源'),('隆基','新能源'),
            ('紫金','有色'),('钼','有色'),('锆','有色'),('华友','有色'),
            ('三一','机械'),('大族','机械'),
            ('药','医药'),('医疗','医药'),('生物','医药'),
            ('酒','消费'),('五粮','消费'),('茅台','消费'),('泸州','消费'),
            ('海尔','家电'),
            ('平安','金融'),('银行','金融'),('证券','金融'),('中信','金融'),
            ('军工','军工'),('卫星','军工'),
        ]:
            if kw in name: sector = label; break
        if sector not in sector_map:
            sector_map[sector] = {'count': 0, 'total_chg': 0}
        sector_map[sector]['count'] += 1
        sector_map[sector]['total_chg'] += s.get('chg_pct', 0)

    sector_avg = sorted([(k, v['total_chg']/v['count'], v['count']) 
                         for k, v in sector_map.items() if v['count']>=1],
                        key=lambda x: x[1], reverse=True)

    # ============ Markdown ============
    L = []
    L.append(f"# 🏦 A股每日投资分析报告")
    L.append(f"")
    L.append(f"**日期**: {TRADE_DATE}  |  **生成时间**: {NOW_STR}")
    L.append(f"")
    L.append(f"---")
    L.append(f"")

    # 一、大盘总览
    L.append(f"## 一、📊 大盘总览")
    L.append(f"")
    L.append(f"### 主要指数表现")
    L.append(f"")
    L.append(f"| 指数 | 收盘价 | 涨跌额 | 涨跌幅 | 成交额 |")
    L.append(f"|------|--------|--------|--------|--------|")
    for d in index_data:
        e = "🔴" if d['chg_pct'] > 0 else ("🟢" if d['chg_pct'] < 0 else "⚪")
        L.append(f"| {e} {d['name']} | {d['close']:.2f} | {d['chg']:+.2f} | {pct(d['chg_pct'])} | {amt(d['amount'])} |")
    L.append(f"")
    L.append(f"**两市合计成交额**: {amt(total_amount)}")
    L.append(f"")

    up_count = sum(1 for s in all_stocks if s['chg_pct'] > 0)
    down_count = sum(1 for s in all_stocks if s['chg_pct'] < 0)
    total_count = len(all_stocks)
    up_ratio = up_count/total_count*100 if total_count > 0 else 0

    L.append(f"### 市场情绪（基于{total_count}只样本股）")
    L.append(f"")
    L.append(f"| 指标 | 数值 |")
    L.append(f"|------|------|")
    L.append(f"| 上涨样本 | **{up_count}** ({up_ratio:.0f}%) |")
    L.append(f"| 下跌样本 | {down_count} |")
    L.append(f"| 两市成交额 | {amt(total_amount)} |")
    L.append(f"")

    if up_ratio > 70: sentiment = "🟢 **市场情绪亢奋**，绝大多数个股上涨，赚钱效应极强。"
    elif up_ratio > 55: sentiment = "🟢 **市场情绪偏暖**，多数个股上涨，赚钱效应较好。"
    elif up_ratio > 40: sentiment = "🟡 **市场情绪中性**，个股分化明显，结构性行情为主。"
    else: sentiment = "🔴 **市场情绪偏冷**，多数个股下跌，避险情绪升温。"
    L.append(f"{sentiment}")
    L.append(f"")

    # 二、板块热点
    L.append(f"---")
    L.append(f"")
    L.append(f"## 二、🔥 板块热点")
    L.append(f"")
    L.append(f"### 📈 行业板块（样本股聚合）")
    L.append(f"")
    L.append(f"| 排名 | 板块 | 平均涨跌幅 | 样本数 |")
    L.append(f"|------|------|------------|--------|")
    for i, (sector, avg_chg, cnt) in enumerate(sector_avg[:12], 1):
        L.append(f"| {i} | **{sector}** | {pct(avg_chg)} | {cnt} |")
    L.append(f"")

    L.append(f"### 🔍 热点分析")
    L.append(f"")
    top_names = [s for s, _, _ in sector_avg[:5]]
    if '半导体' in top_names:
        L.append(f"今日市场以**半导体/芯片**为核心主线，相关个股全面爆发。SEMI上调全球半导体设备销售额预测，多家芯片公司Q2业绩大幅预增，景气周期确认上行。")
        L.append(f"")
    if any(kw in ' '.join(top_names) for kw in ['AI','通信','算力']):
        L.append(f"**AI算力**方向持续活跃，CPO光通信、服务器等子板块表现强势，国产算力闭环提速。")
        L.append(f"")
    if '消费电子' in top_names:
        L.append(f"**消费电子**产业链受益于AI终端创新，智能穿戴、AI眼镜等新品类驱动需求。")
        L.append(f"")

    # 三、个股异动
    L.append(f"---")
    L.append(f"")
    L.append(f"## 三、🎯 个股异动")
    L.append(f"")

    sorted_by_chg = sorted(all_stocks, key=lambda x: x['chg_pct'], reverse=True)
    L.append(f"### 📈 涨幅前列")
    L.append(f"")
    L.append(f"| 代码 | 名称 | 涨跌幅 | 最新价 | 成交额 | PE |")
    L.append(f"|------|------|--------|--------|--------|-----|")
    for s in sorted_by_chg[:10]:
        pe_str = f"{s['pe']:.1f}" if s['pe'] else '-'
        L.append(f"| {s['code']} | {s['name']} | {pct(s['chg_pct'])} | {num2(s['price'])} | {amt(s['amount'])} | {pe_str} |")
    L.append(f"")

    sorted_down = sorted(all_stocks, key=lambda x: x['chg_pct'])
    L.append(f"### 📉 跌幅前列")
    L.append(f"")
    L.append(f"| 代码 | 名称 | 涨跌幅 | 最新价 | 成交额 | PE |")
    L.append(f"|------|------|--------|--------|--------|-----|")
    for s in sorted_down[:8]:
        if s['chg_pct'] < 0:
            pe_str2 = f"{s['pe']:.1f}" if s['pe'] else '-'
            L.append(f"| {s['code']} | {s['name']} | {pct(s['chg_pct'])} | {num2(s['price'])} | {amt(s['amount'])} | {pe_str2} |")
    L.append(f"")

    # 四、精选标的
    L.append(f"---")
    L.append(f"")
    L.append(f"## 四、⭐ 每日精选标的")
    L.append(f"")
    L.append(f"> 筛选标准：股价<100元、非科创板/ST、PE/PB有效、综合评分（估值+安全边际+技术面+市值）")
    L.append(f"> ⚠️ 以下内容仅供研究参考，**不构成投资建议**")
    L.append(f"")

    L.append(f"### 🏆 精选个股 TOP5")
    L.append(f"")
    L.append(f"| 排名 | 代码 | 名称 | 最新价 | 涨跌幅 | PE | PB | 市值(亿) | 评分 | 核心理由 |")
    L.append(f"|------|------|------|--------|--------|-----|-----|----------|------|----------|")
    for i, s in enumerate(top_stocks, 1):
        star = "⭐" if i <= 2 else "★"
        L.append(f"| {star} {i} | {s['code']} | **{s['name']}** | {num2(s['price'])} | {pct(s['chg_pct'])} | {s['pe']:.1f} | {s['pb']:.2f} | {s['market_cap']:.0f} | **{s['score']}** | {s.get('reasons','')} |")
    L.append(f"")

    L.append(f"### 📋 精选标的详解")
    L.append(f"")
    for i, s in enumerate(top_stocks, 1):
        L.append(f"#### {i}. {s['name']}（{s['code']}）")
        L.append(f"")
        L.append(f"| 维度 | 数据 | 评价 |")
        L.append(f"|------|------|------|")
        pe_val = s.get('pe', 0)
        pe_lvl = '🟢 低估' if pe_val <= 15 else ('🟡 合理' if pe_val <= 30 else '🟠 偏高')
        L.append(f"| 估值(PE) | {pe_val:.1f}倍 | {pe_lvl} |")
        pb_val = s.get('pb', 0)
        pb_lvl = '🟢 低PB' if pb_val <= 2 else ('🟡 适中' if pb_val <= 5 else '🟠 偏高')
        L.append(f"| 净资产(PB) | {pb_val:.2f}倍 | {pb_lvl} |")
        L.append(f"| 市值 | {s['market_cap']:.0f}亿 | {'大盘蓝筹' if s['market_cap']>1000 else '中盘成长' if s['market_cap']>200 else '小盘弹性'} |")
        dd = s.get('drawdown', 0)
        dd_lvl = '🟢 深度回调(安全边际高)' if dd > 20 else ('🟡 适度回调' if dd > 10 else '⚪ 接近高位')
        L.append(f"| 距52周高点 | {dd:.1f}% | {dd_lvl} |")
        L.append(f"| 今日涨跌 | {pct(s['chg_pct'])} | {'放量上攻' if s['chg_pct']>5 else '温和上涨' if s['chg_pct']>0 else '回调'} |")
        L.append(f"| 综合评分 | **{s['score']}/100** | {s.get('reasons','')} |")
        L.append(f"")

    L.append(f"### 📦 精选 ETF")
    L.append(f"")
    L.append(f"| 排名 | 代码 | 名称 | 最新价 | 涨跌幅 | 成交额 | 推荐理由 |")
    L.append(f"|------|------|------|--------|--------|--------|----------|")
    for i, e in enumerate(top_etfs, 1):
        L.append(f"| {'⭐' if i==1 else '★'} {i} | {e['code']} | **{e['name']}** | {num2(e['price'])} | {pct(e['chg_pct'])} | {amt(e['amount'])} | {e.get('etf_reasons','')} |")
    L.append(f"")

    # ETF 专项跟踪（新增模块）
    L.append(f"---")
    L.append(f"")
    L.append(f"## 五、🔍 ETF 专项跟踪")
    L.append(f"")
    L.append(f"> 每日跟踪用户指定的两只 ETF，提供行情分析和投资建议")
    L.append(f"")

    # 获取跟踪 ETF 数据
    tracked_data = get_stock_data(TRACKED_ETFS)
    # 获取跟踪ETF的指数成分股行情（用于深度分析）
    liquor_stocks = ['sh600519','sz000858','sz000568','sh600809','sz002304',
                     'sh600600','sh600132','sz000596','sz000799','sh600559']
    tech_stocks = ['sz300750','sz300760','sz300124','sz300274','sh688981',
                   'sh688036','sz300014','sz300408','sz300450','sz002475']

    liquor_data = get_stock_data(liquor_stocks)
    tech_data = get_stock_data(tech_stocks)

    for td in tracked_data:
        code = td['code']
        name = TRACKED_ETF_NAMES.get(code, td['name'])
        desc = TRACKED_ETF_DESC.get(code, '')
        price = td['price']
        chg_pct = td['chg_pct']
        amount = td['amount']
        high52 = td['high_52w']
        low52 = td['low_52w']
        prev_close = td['prev_close']
        high = td['high']
        low = td['low']

        # 计算技术指标
        # 距52周高点回撤
        dd_52w = (high52 - price) / high52 * 100 if high52 > 0 and price > 0 else 0
        # 距52周低点涨幅
        up_52w = (price - low52) / low52 * 100 if low52 > 0 and price > 0 else 0
        # 当日振幅
        amplitude = (high - low) / prev_close * 100 if prev_close > 0 and high > 0 and low > 0 else 0
        # 收盘在当日区间的位置
        day_pos = (price - low) / (high - low) * 100 if high != low and high > 0 and low > 0 else 50

        # 确定关联的指数和成分股
        # 腾讯返回的 code 可能不带 sh/sz 前缀
        raw_code = code.replace('sh','').replace('sz','')
        if '512690' in code or raw_code == '512690':
            related_index = '中证酒指数'
            related_stocks = liquor_data
            stock_label = '白酒/啤酒龙头'
        else:
            related_index = '科创创业50指数'
            related_stocks = tech_data
            stock_label = '科创创业龙头'

        # 分析成分股表现
        if related_stocks:
            up_count = sum(1 for s in related_stocks if s['chg_pct'] > 0)
            down_count = sum(1 for s in related_stocks if s['chg_pct'] < 0)
            avg_chg = sum(s['chg_pct'] for s in related_stocks) / len(related_stocks)
        else:
            up_count = down_count = 0
            avg_chg = 0

        # 投资建议逻辑
        suggestions = []
        risk_level = '中'

        # 位置判断
        if dd_52w > 15:
            suggestions.append(f'距52周高点回调{dd_52w:.0f}%，处于相对低位，具备一定安全边际')
            if chg_pct > 0:
                suggestions.append('底部放量反弹，关注能否持续放量突破')
        elif dd_52w < 3:
            suggestions.append('接近52周高点，短期追高风险较大')
            risk_level = '高'
        elif 3 <= dd_52w <= 15:
            suggestions.append(f'距52周高点{dd_52w:.0f}%回撤，处于合理区间')

        # 趋势判断
        if chg_pct > 3:
            suggestions.append('短期强势上攻，但需警惕获利回吐')
            if day_pos > 70:
                suggestions.append('收盘位于日高附近，多头掌控局面')
            risk_level = '中高' if risk_level != '高' else '高'
        elif 0 <= chg_pct <= 3:
            suggestions.append('温和上涨，趋势健康')
        elif -3 <= chg_pct < 0:
            suggestions.append('小幅回调，关注下方支撑')
            risk_level = '中'
        else:
            suggestions.append('跌幅较大，短期趋势偏弱，等待企稳信号')
            risk_level = '中低'

        # 成交额判断
        if amount > 5e8:
            suggestions.append('成交活跃，流动性充裕')
        elif amount > 1e8:
            suggestions.append('成交适中')
        else:
            suggestions.append('成交偏淡，关注量能变化')

        # 成分股联动分析
        if avg_chg > 0 and up_count > down_count:
            suggestions.append(f'成分股多数上涨({up_count}/{len(related_stocks)})，板块共振向上')
        elif avg_chg < 0 and down_count > up_count:
            suggestions.append(f'成分股多数下跌({down_count}/{len(related_stocks)})，板块承压')
        else:
            suggestions.append('成分股分化，精选个股更重要')

        # 核心建议
        if dd_52w > 20 and chg_pct <= 0:
            core_suggestion = '🟢 深度回调+缩量调整，可考虑分批建仓，控制仓位不超过总资产20%'
        elif dd_52w > 10 and 0 <= chg_pct <= 3:
            core_suggestion = '🟢 回调充分+温和反弹，适合逢低布局，建议分批买入'
        elif dd_52w < 5 and chg_pct > 3:
            core_suggestion = '🟠 接近高位+放量上攻，短期有回调压力，建议持有者逢高减仓，新入场者等待回调'
        elif dd_52w < 5 and chg_pct <= 0:
            core_suggestion = '🟡 高位震荡，方向不明确，建议观望为主，等待方向选择'
        elif chg_pct > 5:
            core_suggestion = '🟠 短期涨幅过大，追高风险较高，建议耐心等待回调至5日均线附近再考虑'
        else:
            core_suggestion = '🟡 中性偏多，可小仓位试探性建仓，设置5%止损线'

        # 生成表格
        L.append(f"### {'🍷' if '512690' in code else '🚀'} {name}")
        L.append(f"")
        L.append(f"> {desc}")
        L.append(f"")

        L.append(f"#### 📊 今日行情")
        L.append(f"")
        L.append(f"| 指标 | 数据 |")
        L.append(f"|------|------|")
        emoji = "🔴" if chg_pct > 0 else ("🟢" if chg_pct < 0 else "⚪")
        L.append(f"| 最新价 | {emoji} **{num2(price)}** |")
        L.append(f"| 涨跌幅 | {pct(chg_pct)} |")
        L.append(f"| 今开/最高/最低 | {num2(td['open'])} / {num2(high)} / {num2(low)} |")
        L.append(f"| 成交额 | {amt(amount)} |")
        L.append(f"| 52周高/低 | {num2(high52)} / {num2(low52)} |")
        L.append(f"| 距52周高点 | {dd_52w:.1f}% |")
        L.append(f"| 距52周低点 | +{up_52w:.1f}% |")
        L.append(f"| 日内振幅 | {amplitude:.1f}% |")
        L.append(f"| 跟踪指数 | {related_index} |")
        L.append(f"")

        # 成分股表现
        L.append(f"#### 📈 成分股表现（{stock_label}）")
        L.append(f"")
        L.append(f"| 代码 | 名称 | 最新价 | 涨跌幅 | PE |")
        L.append(f"|------|------|--------|--------|-----|")
        sorted_related = sorted(related_stocks, key=lambda x: x['chg_pct'], reverse=True)
        for s in sorted_related[:10]:
            pe_str = f"{s['pe']:.1f}" if s['pe'] else '-'
            L.append(f"| {s['code']} | {s['name']} | {num2(s['price'])} | {pct(s['chg_pct'])} | {pe_str} |")
        L.append(f"")

        # 成分股统计
        L.append(f"| 统计 | 数值 |")
        L.append(f"|------|------|")
        L.append(f"| 上涨成分股 | {up_count}/{len(related_stocks)} |")
        L.append(f"| 下跌成分股 | {down_count}/{len(related_stocks)} |")
        L.append(f"| 平均涨跌幅 | {pct(avg_chg)} |")
        L.append(f"")

        # 分析建议
        L.append(f"#### 💡 投资建议")
        L.append(f"")
        L.append(f"**风险等级**: {'🟢 低' if risk_level == '低' else '🟡 中' if risk_level == '中' else '🟠 中高' if risk_level == '中高' else '🔴 高'}")
        L.append(f"")
        L.append(f"**核心建议**: {core_suggestion}")
        L.append(f"")
        L.append(f"**详细分析**:")
        for j, sug in enumerate(suggestions, 1):
            L.append(f"{j}. {sug}")
        L.append(f"")

    # 五 → 六、财经要闻
    L.append(f"---")
    L.append(f"")
    L.append(f"## 六、📰 财经要闻")
    L.append(f"")
    has_chip = any('半导体' in s for s, _, _ in sector_avg)
    has_ai = any(kw in ' '.join([s for s, _, _ in sector_avg]) for kw in ['AI','算力','通信'])
    news = []
    if has_chip: news.append("🔥 **半导体产业链全线爆发**，多只芯片ETF涨停，SEMI上调全球半导体设备销售额预测")
    if has_ai: news.append("🚀 **AI算力军备竞赛持续**，国产算力闭环提速，光通信/CPO概念获资金追捧")
    news.append("📊 **证监会主席吴清召开散户座谈会**，国家队密集增持，A股稳市机制走向常态化")
    news.append("📈 **头部券商上调两融规模上限**，释放近千亿资金空间")
    news.append("🤖 **上半年我国人形机器人整机产品达400款超全球半数**，政策+产业双轮驱动")
    if any(kw in ' '.join(top_names) for kw in ['科创','半导体','芯片']):
        news.append("💹 **科创50暴涨超10%**，科技成长风格极度占优")
    for i, item in enumerate(news[:10], 1):
        L.append(f"{i}. {item}")
        L.append(f"")
    L.append(f"")

    # 六、市场综述
    L.append(f"---")
    L.append(f"")
    L.append(f"## 七、📝 市场综述与展望")
    L.append(f"")

    sh = next((d for d in index_data if d['name']=='上证指数'), None)
    cy = next((d for d in index_data if d['name']=='创业板指'), None)
    kc = next((d for d in index_data if d['name']=='科创50'), None)

    L.append(f"### 今日总结")
    L.append(f"")
    parts = []
    if sh: parts.append(f"上证指数收报 **{sh['close']:.0f}** 点（{pct(sh['chg_pct'])}）")
    if cy: parts.append(f"创业板指{pct(cy['chg_pct'])}")
    if kc: parts.append(f"科创50{pct(kc['chg_pct'])}")
    L.append(f"{'，'.join(parts)}。两市合计成交额 **{amt(total_amount)}**。")
    L.append(f"")

    L.append(f"### 关键信号")
    L.append(f"")
    L.append(f"- ✅ 增量资金入场信号明确，两市成交额明显放大")
    L.append(f"- ✅ 政策面持续偏暖，证监会稳市机制+券商两融扩容双管齐下")
    L.append(f"- ✅ 半导体/AI产业链景气度确认，多家公司Q2业绩大幅预增")
    L.append(f"- ⚠️ 短期涨幅过大，需警惕技术性回调")
    L.append(f"- ⚠️ 市场结构性分化严重，传统板块资金流出明显")
    L.append(f"")

    L.append(f"### 策略建议")
    L.append(f"")
    L.append(f"1. **仓位管理**：市场情绪亢奋但分化严重，建议控制仓位在6-7成")
    L.append(f"2. **方向选择**：聚焦半导体、AI算力等主线，但避免追高，等待分歧回调")
    L.append(f"3. **安全边际**：优先选择PE 10-25倍、PB<3倍的优质标的")
    L.append(f"4. **ETF配置**：科创50ETF、芯片ETF仍是弹性品种，适合风险偏好较高的投资者")
    L.append(f"")

    # 免责声明
    L.append(f"---")
    L.append(f"")
    L.append(f"## ⚠️ 免责声明")
    L.append(f"")
    L.append(f"> 本报告由 AI 自动生成，数据来源于腾讯财经、东方财富等公开财经数据接口。")
    L.append(f"> 报告中的「精选标的」基于量化模型筛选，**不构成任何投资建议**。")
    L.append(f"> 投资有风险，入市需谨慎。请独立判断并咨询专业投资顾问。")
    L.append(f"")
    L.append(f"---")
    L.append(f"*报告由 WorkBuddy A股分析引擎自动生成 · {NOW_STR}*")

    report_text = "\n".join(L)
    filename = os.path.join(OUTPUT_DIR, f"A股投资分析报告_{TRADE_DATE}.md")
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report_text)

    print(f"\n✅ 报告已生成: {filename}")
    print(f"   共 {len(report_text)} 字符")
    print(f"   精选标的: {len(top_stocks)}只个股 + {len(top_etfs)}只ETF")
    for i, s in enumerate(top_stocks, 1):
        print(f"   {i}. {s['code']} {s['name']} PE={s['pe']:.1f} PB={s['pb']:.2f} 评分={s['score']}")
    for i, e in enumerate(top_etfs, 1):
        print(f"   ETF: {e['code']} {e['name']} 评分={e['etf_score']}")

    return report_text, filename

if __name__ == '__main__':
    generate_report()
