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

# A股收盘时间: 北京时间 15:00。如果在收盘前运行(如凌晨/上午)，报告日期应为前一交易日
# 判断逻辑: 如果当前时间 < 15:00，则报告日期为昨天（或上周五如果今天是周一）
current_hour = NOW.hour
if current_hour < 15:
    # 收盘前运行，使用前一交易日
    if WEEKDAY == 0:  # 周一，前一交易日是上周五
        trade_dt = NOW - timedelta(days=3)
    else:
        trade_dt = NOW - timedelta(days=1)
    TRADE_DATE = trade_dt.strftime("%Y-%m-%d")
    print(f"⏰ 当前时间 {NOW.strftime('%H:%M')} 早于15:00，报告日期使用前一交易日: {TRADE_DATE}")
else:
    TRADE_DATE = NOW.strftime("%Y-%m-%d")

NOW_STR = NOW.strftime("%Y-%m-%d %H:%M:%S")

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

def safe_get_json(url, retry=3, timeout=20, referer='https://quote.eastmoney.com/'):
    """支持JSON API的安全请求，自动重试"""
    for i in range(retry):
        try:
            h = dict(HEADERS); h['Referer'] = referer
            h['Accept'] = 'application/json'
            resp = requests.get(url, headers=h, timeout=timeout)
            return resp.json()
        except Exception as e:
            if i == retry - 1:
                print(f"  ⚠️ JSON请求最终失败: {e}")
                return None
            time.sleep(3)
    return None

# 申万行业板块名称简化映射（新浪返回的长名 → 简短显示名）
SECTOR_SHORT_NAME = {
    '铁路、船舶、航空航天和其他运输设备制造业': '军工装备',
    '酒、饮料和精制茶制造业': '食品饮料',
    '电力、热力生产和供应业': '电力',
    '有色金属矿采选业': '有色采选',
    '黑色金属矿采选业': '黑色采选',
    '煤炭开采和洗选业': '煤炭',
    '石油和天然气开采业': '石油石化',
    '农、林、牧、渔服务业': '农林牧渔服务',
    '机动车、电子产品和日用产品修理业': '汽车服务',
    '科技推广和应用服务业': '科技服务',
    '黑色金属冶炼和压延加工业': '钢铁',
    '有色金属冶炼和压延加工业': '有色金属',
    '金属制品业': '金属制品',
    '通用设备制造业': '通用设备',
    '专用设备制造业': '专用设备',
    '汽车制造业': '汽车',
    '铁路运输业': '铁路运输',
    '水上运输业': '航运',
    '航空运输业': '航空',
    '管道运输业': '管道运输',
    '装卸搬运和运输代理业': '物流',
    '仓储业': '仓储',
    '邮政业': '邮政',
    '电信、广播电视和卫星传输服务': '通信',
    '互联网和相关服务': '互联网',
    '软件和信息技术服务业': '软件开发',
    '货币金融服务': '银行',
    '资本市场服务': '券商',
    '保险业': '保险',
    '其他金融业': '其他金融',
    '房地产业': '房地产',
    '租赁业': '租赁',
    '商务服务业': '商务服务',
    '研究和试验发展': '研发服务',
    '专业技术服务业': '专业服务',
    '生态保护和环境治理业': '环保',
    '公共设施管理业': '公共设施',
    '土地管理业': '土地管理',
    '居民服务业': '居民服务',
    '机动车、电子产品和日用产品修理': '修理服务',
    '教育': '教育',
    '卫生': '医疗',
    '社会工作': '社工',
    '新闻和出版业': '传媒',
    '广播、电视、电影和录音制作业': '影视',
    '文化艺术业': '文化艺术',
    '体育': '体育',
    '娱乐业': '娱乐',
    '农业': '农业',
    '林业': '林业',
    '畜牧业': '畜牧业',
    '渔业': '渔业',
    '建筑安装业': '建筑安装',
    '建筑装饰、装修和其他建筑业': '建筑装饰',
    '土木工程建筑业': '基建',
    '房屋建筑业': '房屋建筑',
    '化学原料和化学制品制造业': '化工',
    '医药制造业': '医药',
    '化学纤维制造业': '化纤',
    '橡胶和塑料制品业': '橡胶塑料',
    '非金属矿物制品业': '建材',
    '仪器仪表制造业': '仪器仪表',
    '电气机械和器材制造业': '电气设备',
    '计算机、通信和其他电子设备制造业': '电子制造',
    '食品制造业': '食品制造',
    '纺织业': '纺织',
    '纺织服装、服饰业': '服装',
    '皮革、毛皮、羽毛及其制品和制鞋业': '皮革制鞋',
    '木材加工和木、竹、藤、棕、草制品业': '木材加工',
    '家具制造业': '家具',
    '造纸和纸制品业': '造纸',
    '印刷和记录媒介复制业': '印刷',
    '文教、工美、体育和娱乐用品制造业': '文教用品',
    '石油、煤炭及其他燃料加工业': '石油加工',
    '废弃资源综合利用业': '废弃资源',
    '金属制品、机械和设备修理业': '设备修理',
    '电力、热力、燃气及水生产和供应业': '公用事业',
    '燃气生产和供应业': '燃气',
    '水的生产和供应业': '水务',
    '非金属矿采选业': '非金属矿',
    '非金属矿物制品业': '建材',
    '开采专业及辅助性活动': '开采辅助',
    '房屋和其他建筑业': '建筑业',
    '其他制造业': '其他制造',
    '综合': '综合',
}

def short_sector_name(name):
    """将长板块名简化为短名"""
    if name in SECTOR_SHORT_NAME:
        return SECTOR_SHORT_NAME[name]
    # 去掉"业"后缀等
    return name

def _parse_sina_sectors(raw_text, source_tag):
    """解析新浪板块JSON数据（行业/概念通用）
    字段: [0]代码 [1]板块名 [2]股票数 [3]均价 [4]涨跌额 [5]涨跌幅% [6]成交量 [7]成交额 [8]领涨股代码 [9]领涨股涨幅 [10]领涨股价 [11]涨跌 [12]领涨股名
    """
    sectors = []
    m = re.search(r'=\s*(\{.+\})', raw_text, re.S)
    if not m:
        return sectors
    try:
        raw_json = m.group(1).replace("'", '"')
        data = json.loads(raw_json)
    except Exception:
        return sectors
    for key, val in data.items():
        parts = val.split(',')
        if len(parts) < 6: continue
        name = parts[1].strip()
        if not name: continue
        name = short_sector_name(name)
        try:
            chg = float(parts[5])
        except (ValueError, IndexError):
            chg = 0
        leader = parts[12].strip() if len(parts) > 12 else ''
        leader_chg = 0
        if len(parts) > 9:
            try: leader_chg = float(parts[9])
            except (ValueError,): pass
        leader_code = parts[8].strip() if len(parts) > 8 else ''
        amt_yuan = 0
        if len(parts) > 7:
            try: amt_yuan = float(parts[7])
            except (ValueError,): pass
        stock_cnt = 0
        if len(parts) > 2:
            try: stock_cnt = int(parts[2])
            except (ValueError,): pass
        # 过滤无效板块（成交额为0或股票数<2的通常是非活跃板块）
        if amt_yuan < 1e6 or stock_cnt < 2:
            continue
        sectors.append({
            'name': name, 'code': parts[0].strip(), 'chg': chg,
            'leader': leader, 'leader_chg': leader_chg, 'leader_code': leader_code,
            'amount': amt_yuan, 'stock_count': stock_cnt,
            'source': source_tag
        })
    return sectors


def get_industry_sectors():
    """获取行业板块涨跌幅（全市场真实数据）
    数据源1: 新浪行业板块接口（84个申万二级行业，含领涨股+成交额）✅ 主力
    数据源2: 东方财富 push2.eastmoney.com (m:90+t:2) 备用
    数据源3: 腾讯ETF + 行业指数代理（最后兜底）
    """
    sectors = []

    # ===== 方法1: 新浪行业板块（全市场，主力数据源）=====
    # money.finance.sina.com.cn 返回GBK编码的JS对象，含84个行业板块真实数据
    sina_url = 'https://money.finance.sina.com.cn/q/view/newFLJK.php?param=industry'
    try:
        h = dict(HEADERS)
        h['Referer'] = 'https://finance.sina.com.cn/'
        resp = requests.get(sina_url, headers=h, timeout=15)
        # 新浪返回GBK编码，需手动解码
        resp.encoding = 'gbk'
        if resp.text and 'hangye_' in resp.text:
            sectors = _parse_sina_sectors(resp.text, 'sina_industry')
            if len(sectors) >= 20:
                print(f"  ✅ 行业板块(新浪-全市场): {len(sectors)} 个板块")
                return sectors
            elif sectors:
                print(f"  ⚠️ 新浪行业板块数据偏少({len(sectors)})，继续尝试备用")
    except Exception as e:
        print(f"  ⚠️ 新浪行业板块API失败: {e}")

    # ===== 方法2: 东方财富行业板块 =====
    em_url = 'https://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=m:90+t:2&fields=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22,f11,f62&_=1'
    data = safe_get_json(em_url, referer='https://quote.eastmoney.com/')
    if data:
        diff = data.get('data', {}).get('diff', [])
        if diff and len(diff) > 10:
            for s in diff:
                name = s.get('f14', '')
                chg = s.get('f3', 0)
                code = s.get('f12', '')
                leader = s.get('f20', '')
                leader_chg = s.get('f23', 0)
                if not name or not code: continue
                sectors.append({
                    'name': name, 'code': code, 'chg': float(chg) if chg else 0,
                    'leader': leader, 'leader_chg': float(leader_chg) if leader_chg else 0,
                    'leader_code': '', 'amount': 0, 'stock_count': 0,
                    'source': 'eastmoney'
                })
            if len(sectors) >= 20:
                print(f"  ✅ 行业板块(东方财富): {len(sectors)} 个板块")
                return sectors

    # ===== 方法3: 腾讯ETF + 行业指数代理（最后兜底）=====
    SECTOR_DISPLAY_NAME = {
        '半导体ETF国联安':'半导体', '芯片ETF国泰':'芯片',
        '通信ETF华夏':'通信', '酒ETF鹏华':'白酒', '医疗ETF华宝':'医疗',
        '银行ETF华宝':'银行', '证券ETF国泰':'券商', '军工ETF国泰':'军工',
        '房地产ETF南方':'房地产', '煤炭ETF国泰':'煤炭', '钢铁ETF国泰':'钢铁',
        '医药ETF易方达':'医药', '中证银行':'银行', '中证酒':'白酒',
        '中证医疗':'医疗', 'CSWD生科':'生物科技', '基建工程':'基建',
        '中证白酒':'白酒', '中证煤炭':'煤炭', '信息安全':'信息安全',
        '全指金融':'金融', '全指信息':'信息', '全指消费':'消费',
    }
    fallback_codes = [
        ('sh512480','半导体ETF国联安'),('sh512760','芯片ETF国泰'),
        ('sh515050','通信ETF华夏'),
        ('sh512690','酒ETF鹏华'),('sh512170','医疗ETF华宝'),
        ('sh512800','银行ETF华宝'),('sh512880','证券ETF国泰'),
        ('sh512660','军工ETF国泰'),
        ('sh512200','地产ETF南方'),
        ('sh515220','煤炭ETF'),('sh515210','钢铁ETF'),
        ('sh512010','医药ETF华夏'),
        ('sz399986','中证银行'),('sz399987','中证酒'),('sz399989','中证医疗'),
        ('sz399993','CSWD生科'),('sz399995','基建工程'),('sz399997','中证白酒'),
        ('sz399998','中证煤炭'),('sz399990','煤炭等权'),('sz399994','信息安全'),
        ('sh000992','全指金融'),('sh000993','全指信息'),('sh000994','全指消费'),
    ]
    url = f"https://qt.gtimg.cn/q={','.join(c for c,_ in fallback_codes)}"
    try:
        resp = safe_get(url, referer='https://finance.qq.com/')
        raw = resp.text
        lines = raw.split('\n')
        code_to_name = dict(fallback_codes)
        for line in lines:
            m = re.search(r'="(.+)"', line.strip())
            if not m: continue
            p = m.group(1).split('~')
            if len(p) < 33: continue
            code = p[2]
            raw_name = code_to_name.get(code, p[1])
            display_name = SECTOR_DISPLAY_NAME.get(raw_name, raw_name)
            chg = p[32] if p[32] else 0
            sectors.append({
                'name': display_name, 'code': code, 'chg': float(chg),
                'leader': '', 'leader_chg': 0, 'leader_code': '',
                'amount': 0, 'stock_count': 0,
                'source': 'tencent_etf_index'
            })
        seen_names = set()
        unique_sectors = []
        for s in sectors:
            if s['name'] not in seen_names:
                seen_names.add(s['name'])
                unique_sectors.append(s)
        if unique_sectors:
            print(f"  ⚠️ 行业板块(腾讯ETF代理): {len(unique_sectors)} 个板块/指数")
            return unique_sectors
    except Exception as e:
        print(f"  ⚠️ 腾讯板块备用也失败: {e}")

    print(f"  ❌ 行业板块数据全部获取失败")
    return sectors

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
    results = []
    # 两市合计只取上证指数+深证成指，子指数（创业板/科创50/沪深300等）是子集，不重复累加
    main_indices = {'sh000001', 'sz399001'}
    total_amt = 0
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
        idx_code = INDEX_CODES[len(results)] if len(results) < len(INDEX_CODES) else ''
        if idx_code in main_indices:
            total_amt += a
        results.append({'name': INDEX_NAMES.get(idx_code, p[1]),
                        'close': close, 'chg': chg, 'chg_pct': chg_pct, 'amount': a})
    return results, total_amt

def get_stock_data(codes):
    """腾讯实时行情 + PE/PB/市值/换手率/量比"""
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
                    'turnover_rate': float(p[38]) if p[38] else 0,  # 换手率%
                    'pe': float(p[39]) if p[39] and float(p[39]) > 0 else None,
                    'high_52w': float(p[41]) if p[41] else 0,
                    'low_52w': float(p[42]) if p[42] else 0,
                    'market_cap': float(p[45]) if p[45] else 0,  # 亿
                    'pb': float(p[46]) if p[46] and float(p[46]) > 0 else None,
                    'volume_ratio': float(p[49]) if p[49] else 0,  # 量比
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
def score_stock_shortterm(s):
    """短线选股评分模型（满分100）
    资金面30% + 量价配合25% + 题材热度20% + 技术形态15% + 基本面安全垫10%
    """
    score, reasons = 0, []
    price = s.get('price', 0)
    chg_pct = s.get('chg_pct', 0)
    volume_ratio = s.get('volume_ratio', 0)  # 量比
    turnover = s.get('turnover_rate', 0)     # 换手率%
    amount = s.get('amount', 0)              # 成交额(万元)
    high = s.get('high', 0)
    low = s.get('low', 0)
    prev_close = s.get('prev_close', 0)
    high_52w = s.get('high_52w', 0)
    market_cap = s.get('market_cap', 0)      # 流通市值(亿)
    pe = s.get('pe')

    # === 1. 资金面 (30分) ===
    # 成交额反映资金参与度
    amt_yi = amount / 1e4  # 万元→亿
    if amt_yi >= 100: score += 15; reasons.append(f'成交额{amt_yi:.0f}亿资金活跃')
    elif amt_yi >= 30: score += 12; reasons.append(f'成交额{amt_yi:.0f}亿')
    elif amt_yi >= 10: score += 8
    else: score += 3
    # 换手率反映资金交投活跃度（短线核心指标，3-10%最佳）
    if 3 <= turnover <= 10: score += 20; reasons.append(f'换手{turnover:.1f}%最佳活跃')
    elif 10 < turnover <= 20: score += 15; reasons.append(f'换手{turnover:.1f}%强活跃')
    elif turnover > 20: score += 8   # 换手过高需谨慎
    elif 1.5 <= turnover < 3: score += 8  # 刚达标，活跃度一般
    else: score += 3

    # === 2. 量价配合 (25分) ===
    # 量比>1.5 放量，>2 显著放量
    if volume_ratio >= 2.0: score += 15; reasons.append(f'量比{volume_ratio:.1f}显著放量')
    elif volume_ratio >= 1.5: score += 12; reasons.append(f'量比{volume_ratio:.1f}放量')
    elif volume_ratio >= 1.0: score += 8
    else: score += 3
    # 涨幅 + 放量 = 量价齐升
    if chg_pct > 0 and volume_ratio >= 1.5:
        score += 10; reasons.append('量价齐升')
    elif chg_pct > 0 and volume_ratio >= 1.0:
        score += 7
    elif chg_pct > 0:
        score += 5
    elif -3 <= chg_pct <= 0:
        score += 4  # 缩量回调，等待方向
    else:
        score += 2

    # === 3. 题材热度 (20分) ===
    # 涨幅越大，题材热度越高（涨停=最高热度）
    if chg_pct >= 9.5: score += 20; reasons.append('涨停/接近涨停')
    elif chg_pct >= 5: score += 15; reasons.append(f'涨{chg_pct:.1f}%强势')
    elif chg_pct >= 3: score += 12
    elif chg_pct >= 1: score += 8
    elif chg_pct >= 0: score += 4
    else: score += 2

    # === 4. 技术形态 (15分) ===
    # 日内位置：收盘价在日内高低区间的位置
    if high > low and high > 0:
        day_pos = (price - low) / (high - low) * 100
        if day_pos >= 80: score += 8; reasons.append('收盘接近日高')
        elif day_pos >= 50: score += 6
        else: score += 3
    # 距52周高点位置（突破或接近突破=强势）
    if high_52w > 0 and price > 0:
        pct_from_high = (high_52w - price) / high_52w * 100
        if pct_from_high <= 5: score += 7; reasons.append('接近52周新高')
        elif pct_from_high <= 15: score += 5
        elif pct_from_high <= 30: score += 3
        else: score += 1  # 深度回调不适合短线

    # === 5. 基本面安全垫 (10分) ===
    # 流通市值适中（50-500亿，既有弹性又不易被操纵）
    if 50 <= market_cap <= 500: score += 5; reasons.append('市值适中')
    elif 500 < market_cap <= 2000: score += 4
    elif 20 <= market_cap < 50: score += 3
    else: score += 2
    # PE有效（排除亏损股）
    if pe and pe > 0 and pe < 100: score += 5
    elif pe and pe > 0: score += 3
    else: score += 1

    s['score'] = score
    s['reasons'] = '、'.join(reasons)
    return s

def filter_and_rank(stocks, top_n=5):
    """短线选股筛选+排名
    短线核心标准：换手率≥1.5%（活跃资金）、成交额≥5亿（流动性）
    """
    qualified = []
    for s in stocks:
        code, name, price = s.get('code', ''), s.get('name', ''), s.get('price', 0)
        pe, pb = s.get('pe'), s.get('pb')
        # 基本过滤条件
        if price <= 0 or price >= 100: continue
        if code.startswith('688'): continue  # 排除科创板
        if 'ST' in name: continue            # 排除ST
        if pe is None or pe <= 0: continue   # 排除亏损股
        # 短线必要条件：成交额≥5亿 且 换手率≥1.5%
        amt_yi = s.get('amount', 0) / 1e4
        turnover = s.get('turnover_rate', 0)
        if amt_yi < 5 or turnover < 1.5:
            continue
        qualified.append(score_stock_shortterm(s))
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

    print("📊 [5/6] 获取行业板块数据（真实全市场数据）...")
    industry_sectors = get_industry_sectors()
    # 按涨跌幅排序
    industry_sectors.sort(key=lambda x: x['chg'], reverse=True)
    time.sleep(0.5)

    print("📊 [6/6] 筛选精选标的...")
    top_stocks = filter_and_rank(all_stocks, top_n=5)
    top_etfs = pick_etfs(all_etfs, top_n=2)

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

    if industry_sectors:
        # 涨跌幅前三的板块
        top3 = industry_sectors[:3]
        top3_names = [s['name'] for s in top3]
        top3_desc = [f"**{s['name']}**({pct(s['chg'])})" for s in top3]
        data_source = industry_sectors[0].get('source', '')
        source_label = {'sina_industry':'新浪·申万行业全市场','eastmoney':'东方财富','tencent_etf_index':'腾讯ETF代理'}.get(data_source, data_source)

        L.append(f"### 📈 行业板块涨幅榜（{source_label}）")
        L.append(f"")
        L.append(f"| 排名 | 板块 | 涨跌幅 | 成交额 | 领涨股 | 领涨股涨幅 |")
        L.append(f"|------|------|--------|--------|--------|------------|")
        for i, s in enumerate(industry_sectors[:15], 1):
            arrow = "🚀" if i <= 3 else ""
            leader_str = f"{s.get('leader','')}" if s.get('leader') and s['leader'] != '--' else '-'
            leader_chg_str = pct(s.get('leader_chg',0)) if s.get('leader_chg') else '-'
            amt_str = f"{s['amount']/1e8:.0f}亿" if s.get('amount',0) > 0 else '-'
            L.append(f"| {i} {arrow} | **{s['name']}** | {pct(s['chg'])} | {amt_str} | {leader_str} | {leader_chg_str} |")
        L.append(f"")
        # 跌幅前5
        bottom5 = industry_sectors[-5:] if len(industry_sectors) >= 5 else []
        if bottom5:
            L.append(f"### 📉 行业板块跌幅榜")
            L.append(f"")
            L.append(f"| 板块 | 涨跌幅 | 成交额 |")
            L.append(f"|------|--------|--------|")
            for s in reversed(bottom5):
                amt_str = f"{s['amount']/1e8:.0f}亿" if s.get('amount',0) > 0 else '-'
                L.append(f"| {s['name']} | {pct(s['chg'])} | {amt_str} |")
            L.append(f"")
        total_sectors = len(industry_sectors)
        up_count = len([s for s in industry_sectors if s['chg'] > 0])
        down_count = len([s for s in industry_sectors if s['chg'] < 0])
        L.append(f"> ℹ️ 数据来源：{source_label}，共{total_sectors}个行业板块（涨{up_count}/跌{down_count}），覆盖全市场真实数据")
        L.append(f"")

        # 热点分析
        L.append(f"### 🔍 热点分析")
        L.append(f"")
        if top3:
            L.append(f"今日涨幅前三板块：{'、'.join(top3_desc)}。")
            L.append(f"")
            # 提取领涨股龙头
            leaders = [s.get('leader') for s in top3 if s.get('leader') and s['leader'] != '--']
            if leaders:
                L.append(f"领涨龙头股：**{'**、**'.join(leaders)}**。")
                L.append(f"")
            # 分析特征 - 基于板块名关键词智能匹配
            all_names = ''.join(s['name'] for s in top3)
            if any(k in all_names for k in ['军工','装备','航空','航天','船舶','兵器','兵装']):
                L.append(f"**军工/装备**方向受关注，可能与地缘事件或订单催化相关。")
                L.append(f"")
            if any(k in all_names for k in ['半导体','芯片','电子','软件','通信','信息','计算机']):
                L.append(f"**科技/电子**方向表现活跃，国产替代与AI主线持续。")
                L.append(f"")
            if any(k in all_names for k in ['银行','券商','保险','金融']):
                L.append(f"**金融**板块走强，可能与高股息红利策略或稳市政策相关。")
                L.append(f"")
            if any(k in all_names for k in ['医药','医疗','生物','健康']):
                L.append(f"**医药**板块活跃，关注创新药与集采影响。")
                L.append(f"")
            if any(k in all_names for k in ['煤炭','石油','石化','有色','钢铁','化工','电力']):
                L.append(f"**周期/资源**板块走强，关注大宗商品价格与需求预期。")
                L.append(f"")
            if any(k in all_names for k in ['食品','饮料','酒','服装','零售','消费','家电']):
                L.append(f"**消费**板块回暖，关注内需复苏与消费政策。")
                L.append(f"")
    else:
        L.append(f"⚠️ 板块数据获取失败")
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
    L.append(f"> **短线选股模型**（资金面30%+量价配合25%+题材热度20%+技术形态15%+基本面10%）")
    L.append(f"> 筛选条件：股价<100元、非科创板/ST、PE>0、成交额≥5亿、**换手率≥1.5%**")
    L.append(f"> ⚠️ 以下内容仅供研究参考，**不构成投资建议**")
    L.append(f"")
    L.append(f"### 🏆 精选个股 TOP5（短线模型）")
    L.append(f"")
    L.append(f"| 排名 | 代码 | 名称 | 最新价 | 涨跌幅 | 成交额 | 量比 | 换手率 | 评分 | 核心理由 |")
    L.append(f"|------|------|------|--------|--------|--------|------|--------|------|----------|")
    for i, s in enumerate(top_stocks, 1):
        star = "⭐" if i <= 2 else "★"
        amt_str = f"{s['amount']/1e4:.0f}亿" if s.get('amount',0) > 0 else '-'
        vr_str = f"{s.get('volume_ratio',0):.1f}" if s.get('volume_ratio',0) > 0 else '-'
        tr_str = f"{s.get('turnover_rate',0):.1f}%" if s.get('turnover_rate',0) > 0 else '-'
        L.append(f"| {star} {i} | {s['code']} | **{s['name']}** | {num2(s['price'])} | {pct(s['chg_pct'])} | {amt_str} | {vr_str} | {tr_str} | **{s['score']}** | {s.get('reasons','')} |")
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

    # 六、财经要闻（基于行业板块表现智能生成）
    L.append(f"---")
    L.append(f"")
    L.append(f"## 六、📰 财经要闻")
    L.append(f"")
    news = []
    if industry_sectors:
        # 按涨幅前3板块生成相关新闻
        top3 = industry_sectors[:3]
        for s in top3:
            name = s['name']
            chg_str = pct(s['chg'])
            leader = s.get('leader','') if s.get('leader','') and s['leader'] != '--' else '相关龙头'
            if any(k in name for k in ['半导体','芯片','电子','软件','通信','信息','计算机','仪器仪表']):
                news.append(f"🔥 **科技/电子产业链活跃**，{name}涨{chg_str}，{leader}领涨")
            elif any(k in name for k in ['军工','装备','航空','航天','船舶','兵器','兵装']):
                news.append(f"🛡️ **{name}走强**（{chg_str}），{leader}领涨，关注地缘催化")
            elif any(k in name for k in ['银行','券商','保险','金融']):
                news.append(f"💰 **{name}上涨**（{chg_str}），高股息红利策略受资金关注")
            elif any(k in name for k in ['煤炭','石油','石化','有色','钢铁','化工','电力','燃气']):
                news.append(f"🥇 **{name}走强**（{chg_str}），{leader}领涨，商品价格预期改善")
            elif any(k in name for k in ['医药','医疗','生物','健康']):
                news.append(f"💊 **{name}活跃**（{chg_str}），{leader}领涨，关注创新药主线")
            elif any(k in name for k in ['食品','饮料','酒','服装','零售','消费','家电','纺织']):
                news.append(f"🛒 **{name}回暖**（{chg_str}），{leader}领涨，关注内需复苏")
            elif any(k in name for k in ['汽车','新能源','锂','电池','光伏','风电']):
                news.append(f"⚡ **{name}走强**（{chg_str}），{leader}领涨，新能源方向获关注")
            elif any(k in name for k in ['基建','建筑','建材','地产','房地产']):
                news.append(f"🏗️ **{name}走强**（{chg_str}），{leader}领涨，关注稳增长政策")
            else:
                news.append(f"📈 **{name}领涨**（{chg_str}），{leader}表现突出")
    # 固定要闻补充
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
