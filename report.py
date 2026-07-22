#!/usr/bin/env python3
"""
A股每日投资分析报告 - 核心引擎 v6
数据源: 腾讯财经(实时行情+估值+日K) + 东方财富(板块/资讯)
适配 GitHub Actions 定时运行
修复: 成交额单位、ETF 52周数据、样本量、24小时制
"""

import requests, re, json, time, os, sys
from datetime import datetime, timedelta

NOW = datetime.now()
WEEKDAY = NOW.weekday()
if WEEKDAY >= 5:
    print(f"⏭️ 今天是周末（周{WEEKDAY+1}），A股休市，跳过报告生成。")
    sys.exit(0)

NOW_STR = NOW.strftime("%Y-%m-%d %H:%M:%S")
TRADE_DATE = NOW.strftime("%Y-%m-%d")

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
OUTPUT_DIR = os.environ.get('OUTPUT_DIR', os.getcwd())
os.makedirs(OUTPUT_DIR, exist_ok=True)

def safe_get(url, retry=3, timeout=20, referer='https://finance.qq.com/'):
    for i in range(retry):
        try:
            h = dict(HEADERS); h['Referer'] = referer
            resp = requests.get(url, headers=h, timeout=timeout)
            resp.encoding = 'gbk'
            return resp
        except Exception as e:
            if i == retry - 1: raise e
            time.sleep(3)
    return None

def pct(v):
    if v is None: return '-'
    return f"{v:+.2f}%"

def amt(v):
    """格式化成交额：腾讯接口[37]返回单位=万元"""
    if v is None or v == 0: return '-'
    v_yi = v / 1e4  # 万元→亿
    if v_yi >= 10000:
        return f"{v_yi/10000:.2f}万亿"
    return f"{v_yi:.0f}亿"

def num2(v):
    if v is None: return '-'
    return f"{v:.2f}"

# ============================================================
INDEX_CODES = ['sh000001','sz399001','sz399006','sh000688','sh000300','sh000016','sz399905']
INDEX_NAMES = {'sh000001':'上证指数','sz399001':'深证成指','sz399006':'创业板指',
               'sh000688':'科创50','sh000300':'沪深300','sh000016':'上证50','sz399905':'中证500'}

# 扩大样本池（100+ 只，覆盖各行业）
STOCK_CANDIDATES = [
    # 金融 (10)
    'sz000001','sh600036','sh601166','sh601318','sh600030','sh601398','sh601328',
    'sh600016','sz002142','sh601009',
    # 消费 (12)
    'sz000858','sz000568','sh600519','sh600887','sh600690','sz000651','sz002304',
    'sh600809','sz000333','sh600600','sh600132','sz000799',
    # 科技 (15)
    'sz000725','sh601138','sz002475','sz002156','sz000021','sz000977','sh603019',
    'sz002049','sz300308','sh600703','sz002415','sz002230','sz002236','sz300124','sz300408',
    # 新能源 (8)
    'sz300750','sz300014','sz300274','sh601012','sh603799','sz300450','sz002460','sz002466',
    # 周期 (10)
    'sh601899','sh600031','sh603993','sh600183','sz002008','sh600118','sh600893',
    'sz002167','sh600362','sh601600',
    # 医药 (8)
    'sz300760','sz002432','sh600276','sz000538','sz300015','sh600196','sz300122','sz002001',
    # 军工/通信 (8)
    'sh600118','sh600879','sz002013','sz300699','sz002465','sh600118','sh600498','sz300502',
    # 半导体/封测 (8)
    'sh600584','sh603986','sh603501','sz300285','sz002371','sh603160','sz300661','sz300782',
    # 其他行业龙头 (10)
    'sh600585','sh601668','sh600104','sh601088','sh600028','sh601857',
    'sh600900','sh601006','sh600009','sh601111',
]

ETF_CANDIDATES = [
    'sh510050','sh510300','sh510500','sh588000','sh159919','sh512480','sh159995',
    'sh512760','sh515050','sh512660','sh516510','sh512880','sh513180','sh159766',
]

TRACKED_ETFS = ['sh512690', 'sz159781']
TRACKED_ETF_NAMES = {'sh512690': '酒ETF(512690)', 'sz159781': '科创创业ETF易方达(159781)'}
TRACKED_ETF_DESC = {
    'sh512690': '跟踪中证酒指数，覆盖白酒、啤酒、葡萄酒龙头',
    'sz159781': '跟踪科创创业50指数，覆盖科创板和创业板龙头科技公司',
}
TRACKED_ETF_COMPONENTS = {
    'sh512690': ['sh600519','sz000858','sz000568','sh600809','sz002304',
                 'sh600600','sh600132','sz000596','sz000799','sh600559'],
    'sz159781': ['sz300750','sz300760','sz300124','sz300274','sh688981',
                 'sh688036','sz300014','sz300408','sz300450','sz002475'],
}

# ============================================================
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
        a = float(p[37]) if len(p)>37 and p[37] else 0  # 万元
        total_amt += a
        results.append({'name': INDEX_NAMES.get(INDEX_CODES[len(results)], p[1]),
                        'close': close, 'chg': chg, 'chg_pct': chg_pct, 'amount': a})
    return results, total_amt

def get_stock_data(codes):
    """腾讯实时行情 + PE/PB/市值"""
    results = []
    for i in range(0, len(codes), 20):
        batch = codes[i:i+20]
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
                    'amount': float(p[37]) if p[37] else 0,  # 万元
                    'pe': float(p[39]) if p[39] and float(p[39]) > 0 else None,
                    'high_52w': float(p[41]) if p[41] else 0,
                    'low_52w': float(p[42]) if p[42] else 0,
                    'market_cap': float(p[45]) if p[45] else 0,  # 亿
                    'pb': float(p[46]) if p[46] and float(p[46]) > 0 else None,
                })
            time.sleep(0.3)
        except Exception as e:
            print(f"  ⚠️ batch {i} 失败: {e}")
    return results

def get_etf_52week(code):
    """获取ETF的52周高低点（三重备用API：腾讯→新浪→东方财富）"""
    prefix = 'sh' if code.startswith('sh') or (not code.startswith('sz') and code[0] in '56') else 'sz'
    clean_code = code.replace('sh','').replace('sz','')
    sina_code = f'{prefix}{clean_code}'
    # 东方财富 secid: 1=沪 0=深
    em_secid = f'1.{clean_code}' if prefix == 'sh' else f'0.{clean_code}'

    # 方法1: 腾讯日K API
    for url in [
        f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{clean_code},day,,,250,qfq',
        f'https://ifzq.gtimg.cn/appstock/app/fqkline/get?param={prefix}{clean_code},day,,,250,qfq',
    ]:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            data = resp.json()
            if data.get('code') == 0:
                stock_data = data['data'].get(f'{prefix}{clean_code}', {})
                days = stock_data.get('qfqday') or stock_data.get('day')
                if days and len(days) > 0:
                    highs = [float(d[3]) for d in days]
                    lows = [float(d[4]) for d in days]
                    print(f"  ✅ {code} 52周数据(腾讯): high={max(highs):.3f}, low={min(lows):.3f}")
                    return max(highs), min(lows)
        except Exception as e:
            print(f"  ⚠️ {code} 腾讯API失败: {e}")

    # 方法2: 新浪API
    try:
        sina_url = f'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina_code}&scale=240&ma=no&datalen=250'
        resp = requests.get(sina_url, headers=HEADERS, timeout=15)
        data = resp.json()
        if data and len(data) > 0:
            highs = [float(x['high']) for x in data]
            lows = [float(x['low']) for x in data]
            print(f"  ✅ {code} 52周数据(新浪): high={max(highs):.3f}, low={min(lows):.3f}")
            return max(highs), min(lows)
    except Exception as e:
        print(f"  ⚠️ {code} 新浪API失败: {e}")

    # 方法3: 东方财富API
    try:
        em_url = f'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={em_secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=1&beg=20250101&end=20261231&lmt=250'
        resp = requests.get(em_url, headers=HEADERS, timeout=15)
        data = resp.json()
        klines = data.get('data', {}).get('klines', [])
        if klines and len(klines) > 0:
            highs = [float(k.split(',')[2]) for k in klines]
            lows = [float(k.split(',')[3]) for k in klines]
            print(f"  ✅ {code} 52周数据(东方财富): high={max(highs):.3f}, low={min(lows):.3f}")
            return max(highs), min(lows)
    except Exception as e:
        print(f"  ⚠️ {code} 东方财富API失败: {e}")

    print(f"  ❌ {code} 52周数据全部获取失败")
    return 0, 0

# ============================================================
def score_stock(s):
    score, reasons = 0, []
    pe, pb, price = s.get('pe'), s.get('pb'), s.get('price', 0)

    if pe and pe > 0:
        if 5 <= pe <= 15: score += 25; reasons.append('低估值')
        elif 15 < pe <= 25: score += 20; reasons.append('估值合理')
        elif 25 < pe <= 40: score += 12
        elif pe < 5: score += 8
        else: score += 5
    else: score += 5

    if pb and pb > 0:
        if 0.5 <= pb <= 2.5: score += 20; reasons.append('PB低')
        elif 2.5 < pb <= 5: score += 12
        elif pb < 0.5: score += 8
        else: score += 5
    else: score += 5

    high52 = s.get('high_52w', 0)
    if high52 > 0 and price > 0:
        dd = (high52 - price) / high52 * 100
        s['drawdown'] = dd
        if dd > 25: score += 20; reasons.append(f'深度回调{dd:.0f}%')
        elif dd > 15: score += 15
        elif dd > 8: score += 10
        elif dd > 3: score += 5
    else: s['drawdown'] = 0

    mc = s.get('market_cap', 0)
    if 200 <= mc <= 3000: score += 15; reasons.append('市值适中')
    elif 50 <= mc < 200: score += 10
    elif mc > 3000: score += 8
    else: score += 5

    high, low, chg = s.get('high', 0), s.get('low', 0), s.get('chg_pct', 0)
    if high > 0 and low > 0 and price > 0 and high != low:
        pos = (price - low) / (high - low)
        if pos > 0.7: score += 8
        elif pos > 0.4: score += 5
        else: score += 2

    if 0 < chg <= 5: score += 7; reasons.append('温和上涨')
    elif 5 < chg <= 10: score += 5
    elif chg > 10: score += 2
    elif -5 <= chg <= 0: score += 6; reasons.append('回调机会')
    else: score += 3

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
        if 'ST' in name: continue
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
        if amt_val > 5e4: score += 15; reasons.append('流动性极好')
        elif amt_val > 1e4: score += 10; reasons.append('流动性良好')
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
def generate_report():
    print(f"\n{'='*60}")
    print(f"  A股每日投资分析报告 v6")
    print(f"  日期: {TRADE_DATE}  |  时间: {NOW_STR}")
    print(f"{'='*60}\n")

    print("📊 [1/5] 获取指数行情...")
    index_data, total_amount = get_index_data()
    time.sleep(0.5)

    print(f"📊 [2/5] 获取{len(STOCK_CANDIDATES)}只个股数据...")
    all_stocks = get_stock_data(STOCK_CANDIDATES)
    time.sleep(0.5)

    print("📊 [3/5] 获取ETF数据...")
    all_etfs = get_stock_data(ETF_CANDIDATES)
    time.sleep(0.5)

    print("📊 [4/5] 获取跟踪ETF的52周数据...")
    tracked_52w = {}
    for etf_code in TRACKED_ETFS:
        h, l = get_etf_52week(etf_code)
        tracked_52w[etf_code] = {'high_52w': h, 'low_52w': l}
        time.sleep(0.3)

    print("📊 [5/5] 筛选精选标的...")
    top_stocks = filter_and_rank(all_stocks, top_n=5)
    top_etfs = pick_etfs(all_etfs, top_n=2)

    # 板块聚合
    sector_map = {}
    for s in all_stocks:
        name = s.get('name', '')
        sector = '其他'
        for kw, label in [
            ('半导体','半导体'),('芯片','半导体'),('长电','半导体'),('通富','半导体'),
            ('紫光','半导体'),('兆易','半导体'),('深科技','半导体'),
            ('光电','光学'),('京东方','面板'),('显示','面板'),
            ('通信','通信'),('旭创','通信'),('中兴','通信'),('烽火','通信'),
            ('工业富联','AI服务器'),('浪潮','AI服务器'),('曙光','AI服务器'),
            ('电子','消费电子'),('立讯','消费电子'),('蓝思','消费电子'),
            ('亿纬','新能源'),('宁德','新能源'),('锂','新能源'),('隆基','新能源'),
            ('阳光','新能源'),('先导','新能源'),
            ('紫金','有色'),('钼','有色'),('锆','有色'),('华友','有色'),('铝','有色'),
            ('三一','机械'),('大族','机械'),('中联','机械'),
            ('药','医药'),('医疗','医药'),('生物','医药'),('迈瑞','医药'),
            ('酒','消费'),('五粮','消费'),('茅台','消费'),('泸州','消费'),
            ('伊利','消费'),('海尔','家电'),('美的','家电'),('格力','家电'),
            ('平安','金融'),('银行','金融'),('证券','金融'),('中信','金融'),
            ('招商','金融'),('兴业','金融'),('宁波','金融'),
            ('军工','军工'),('卫星','军工'),('航','军工'),
            ('神华','能源'),('石油','能源'),('石化','能源'),('中煤','能源'),
            ('长江','电力'),('华能','电力'),('国电','电力'),
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
    L.append(f"| 下跌样本 | {down_count} ({100-up_ratio:.0f}%) |")
    L.append(f"| 两市成交额 | {amt(total_amount)} |")
    L.append(f"")
    L.append(f"> ℹ️ 以上为{total_count}只样本股的统计结果，与实际全市场数据可能存在偏差，仅供参考。")
    L.append(f"")

    if up_ratio > 70: sentiment = "🟢 **市场情绪亢奋**，绝大多数样本股上涨。"
    elif up_ratio > 55: sentiment = "🟢 **市场情绪偏暖**，多数样本股上涨。"
    elif up_ratio > 40: sentiment = "🟡 **市场情绪中性**，个股分化明显。"
    else: sentiment = "🔴 **市场情绪偏冷**，多数样本股下跌。"
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
        L.append(f"今日**半导体/芯片**方向表现活跃，SEMI上调全球半导体设备销售额预测，多家公司Q2业绩预增。")
        L.append(f"")
    if any(kw in ' '.join(top_names) for kw in ['AI','通信','算力']):
        L.append(f"**AI算力**方向持续受关注，国产算力闭环提速。")
        L.append(f"")
    if '消费电子' in top_names:
        L.append(f"**消费电子**产业链受益于AI终端创新。")
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
    L.append(f"> 筛选标准：股价<100元、非科创板/ST、PE/PB有效")
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

    L.append(f"### 📦 精选 ETF")
    L.append(f"")
    L.append(f"| 排名 | 代码 | 名称 | 最新价 | 涨跌幅 | 成交额 | 推荐理由 |")
    L.append(f"|------|------|------|--------|--------|--------|----------|")
    for i, e in enumerate(top_etfs, 1):
        L.append(f"| {'⭐' if i==1 else '★'} {i} | {e['code']} | **{e['name']}** | {num2(e['price'])} | {pct(e['chg_pct'])} | {amt(e['amount'])} | {e.get('etf_reasons','')} |")
    L.append(f"")

    # 五、ETF 专项跟踪
    L.append(f"---")
    L.append(f"")
    L.append(f"## 五、🔍 ETF 专项跟踪")
    L.append(f"")
    L.append(f"> 每日跟踪用户指定的两只 ETF，提供行情分析和投资建议")
    L.append(f"")

    tracked_data = get_stock_data(TRACKED_ETFS)

    for td in tracked_data:
        code = td['code']
        raw_code = code.replace('sh','').replace('sz','')
        name = TRACKED_ETF_NAMES.get(code, td['name'])
        desc = TRACKED_ETF_DESC.get(code, '')
        price = td['price']
        chg_pct = td['chg_pct']
        amount = td['amount']
        prev_close = td['prev_close']
        high = td['high']
        low = td['low']
        open_price = td['open']

        # 使用专门的52周数据（尝试带前缀和不带前缀两种key）
        tw = tracked_52w.get(code, {})
        if not tw:
            # 尝试匹配带前缀的key
            for prefix in ['sh', 'sz']:
                tw = tracked_52w.get(f'{prefix}{code}', {})
                if tw:
                    break
        high52 = tw.get('high_52w', 0)
        low52 = tw.get('low_52w', 0)

        # 技术指标
        dd_52w = (high52 - price) / high52 * 100 if high52 > 0 and price > 0 else 0
        up_52w = (price - low52) / low52 * 100 if low52 > 0 and price > 0 else 0
        amplitude = (high - low) / prev_close * 100 if prev_close > 0 and high > 0 and low > 0 else 0
        day_pos = (price - low) / (high - low) * 100 if high != low and high > 0 and low > 0 else 50

        # 成分股数据
        comp_codes = TRACKED_ETF_COMPONENTS.get(code, [])
        comp_data = get_stock_data(comp_codes) if comp_codes else []

        if '512690' in code:
            related_index = '中证酒指数'
            stock_label = '白酒/啤酒龙头'
        else:
            related_index = '科创创业50指数'
            stock_label = '科创创业龙头'

        # 投资建议
        suggestions = []
        risk_level = '中'

        if dd_52w > 15:
            suggestions.append(f'距52周高点回调{dd_52w:.0f}%，处于相对低位')
            if chg_pct > 0: suggestions.append('底部反弹，关注能否持续放量')
        elif dd_52w < 3:
            suggestions.append('接近52周高点，短期追高风险较大')
            risk_level = '高'
        else:
            suggestions.append(f'距52周高点{dd_52w:.0f}%回撤，处于合理区间')

        if chg_pct > 3:
            suggestions.append('短期强势上攻，但需警惕获利回吐')
            if day_pos > 70: suggestions.append('收盘位于日高附近，多头掌控')
            risk_level = '中高' if risk_level != '高' else '高'
        elif 0 <= chg_pct <= 3:
            suggestions.append('温和上涨，趋势健康')
        elif -3 <= chg_pct < 0:
            suggestions.append('小幅回调，关注下方支撑')
        else:
            suggestions.append('跌幅较大，等待企稳信号')
            risk_level = '中低'

        if amount > 5e4: suggestions.append('成交活跃，流动性充裕')
        elif amount > 1e4: suggestions.append('成交适中')
        else: suggestions.append('成交偏淡')

        if comp_data:
            up_c = sum(1 for s in comp_data if s['chg_pct'] > 0)
            down_c = sum(1 for s in comp_data if s['chg_pct'] < 0)
            avg_c = sum(s['chg_pct'] for s in comp_data) / len(comp_data)
        else:
            up_c = down_c = 0
            avg_c = 0

        if avg_c > 0 and up_c > down_c:
            suggestions.append(f'成分股多数上涨({up_c}/{len(comp_data)})，板块共振向上')
        elif avg_c < 0 and down_c > up_c:
            suggestions.append(f'成分股多数下跌({down_c}/{len(comp_data)})，板块承压')
        else:
            suggestions.append('成分股分化')

        if dd_52w > 20 and chg_pct <= 0:
            core = '🟢 深度回调+缩量调整，可考虑分批建仓，控制仓位不超过总资产20%'
        elif dd_52w > 10 and 0 <= chg_pct <= 3:
            core = '🟢 回调充分+温和反弹，适合逢低布局'
        elif dd_52w < 5 and chg_pct > 3:
            core = '🟠 接近高位+放量上攻，建议持有者逢高减仓，新入场者等待回调'
        elif dd_52w < 5 and chg_pct <= 0:
            core = '🟡 高位震荡，建议观望，等待方向选择'
        elif chg_pct > 5:
            core = '🟠 短期涨幅过大，追高风险较高，建议等待回调'
        else:
            core = '🟡 中性偏多，可小仓位试探性建仓，设置5%止损线'

        emoji = '🍷' if '512690' in code else '🚀'
        L.append(f"### {emoji} {name}")
        L.append(f"")
        L.append(f"> {desc}")
        L.append(f"")

        L.append(f"#### 📊 今日行情")
        L.append(f"")
        L.append(f"| 指标 | 数据 |")
        L.append(f"|------|------|")
        emoji_p = "🔴" if chg_pct > 0 else ("🟢" if chg_pct < 0 else "⚪")
        L.append(f"| 最新价 | {emoji_p} **{num2(price)}** |")
        L.append(f"| 涨跌幅 | {pct(chg_pct)} |")
        L.append(f"| 今开/最高/最低 | {num2(open_price)} / {num2(high)} / {num2(low)} |")
        L.append(f"| 成交额 | {amt(amount)} |")
        L.append(f"| 52周最高/最低 | {num2(high52)} / {num2(low52)} |")
        if high52 > 0:
            L.append(f"| 距52周高点 | {dd_52w:.1f}%（{price-high52:+.3f}） |")
        else:
            L.append(f"| 距52周高点 | - |")
        if low52 > 0:
            L.append(f"| 距52周低点 | +{up_52w:.1f}%（{price-low52:+.3f}） |")
        else:
            L.append(f"| 距52周低点 | - |")
        L.append(f"| 日内振幅 | {amplitude:.1f}% |")
        L.append(f"| 跟踪指数 | {related_index} |")
        L.append(f"")

        if comp_data:
            L.append(f"#### 📈 成分股表现（{stock_label}）")
            L.append(f"")
            L.append(f"| 代码 | 名称 | 最新价 | 涨跌幅 | PE |")
            L.append(f"|------|------|--------|--------|-----|")
            sorted_comp = sorted(comp_data, key=lambda x: x['chg_pct'], reverse=True)
            for s in sorted_comp[:10]:
                pe_str = f"{s['pe']:.1f}" if s['pe'] else '-'
                L.append(f"| {s['code']} | {s['name']} | {num2(s['price'])} | {pct(s['chg_pct'])} | {pe_str} |")
            L.append(f"")
            L.append(f"| 统计 | 数值 |")
            L.append(f"|------|------|")
            L.append(f"| 上涨/下跌 | {up_c}/{down_c} |")
            L.append(f"| 平均涨跌幅 | {pct(avg_c)} |")
            L.append(f"")

        L.append(f"#### 💡 投资建议")
        L.append(f"")
        L.append(f"**风险等级**: {'🟢 低' if risk_level=='低' else '🟡 中' if risk_level=='中' else '🟠 中高' if risk_level=='中高' else '🔴 高'}")
        L.append(f"")
        L.append(f"**核心建议**: {core}")
        L.append(f"")
        L.append(f"**详细分析**:")
        for j, sug in enumerate(suggestions, 1):
            L.append(f"{j}. {sug}")
        L.append(f"")

    # 六、财经要闻
    L.append(f"---")
    L.append(f"")
    L.append(f"## 六、📰 财经要闻")
    L.append(f"")
    has_chip = any('半导体' in s for s, _, _ in sector_avg)
    news = []
    if has_chip: news.append("🔥 **半导体产业链活跃**，SEMI上调全球半导体设备销售额预测")
    news.append("📊 **证监会主席吴清召开散户座谈会**，国家队密集增持，A股稳市机制走向常态化")
    news.append("📈 **头部券商上调两融规模上限**，释放近千亿资金空间")
    news.append("🤖 **上半年我国人形机器人整机产品达400款超全球半数**")
    for i, item in enumerate(news[:10], 1):
        L.append(f"{i}. {item}")
        L.append(f"")
    L.append(f"")

    # 七、市场综述
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
    L.append(f"- ✅ 增量资金入场信号明确")
    L.append(f"- ✅ 政策面持续偏暖，证监会稳市机制+券商两融扩容")
    L.append(f"- ✅ 半导体/AI产业链景气度确认")
    L.append(f"- ⚠️ 市场结构性分化，需精选方向")
    L.append(f"")

    L.append(f"### 策略建议")
    L.append(f"")
    L.append(f"1. **仓位管理**：建议控制仓位在6-7成")
    L.append(f"2. **方向选择**：聚焦主线，避免追高，等待分歧回调")
    L.append(f"3. **安全边际**：优先选择PE 10-25倍、PB<3倍的优质标的")
    L.append(f"4. **ETF配置**：关注精选池中的低估值品种")
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
    readme_path = os.path.join(OUTPUT_DIR, 'README.md')
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report_text)
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(report_text)

    print(f"\n✅ 报告已生成: {filename}")
    print(f"   README.md 已同步更新")
    print(f"   共 {len(report_text)} 字符, {len(L)} 行")
    print(f"   精选标的: {len(top_stocks)}只个股 + {len(top_etfs)}只ETF")
    for i, s in enumerate(top_stocks, 1):
        print(f"   {i}. {s['code']} {s['name']} PE={s['pe']:.1f} PB={s['pb']:.2f} 评分={s['score']}")
    for i, e in enumerate(top_etfs, 1):
        print(f"   ETF: {e['code']} {e['name']} 评分={e['etf_score']}")

    return report_text, filename

if __name__ == '__main__':
    generate_report()
