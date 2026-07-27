#!/usr/bin/env python3
"""OnchainEquities backend: serves static files + /api/news RWA news aggregator.
No external deps (urllib + xml.etree). Run: python server.py [port]"""
import sys, os, json, re, time, math, threading
import concurrent.futures as _cf
import urllib.request, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.etree import ElementTree as ET
from email.utils import parsedate_to_datetime
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('PORT') or (sys.argv[1] if len(sys.argv) > 1 else 8765))

# ---- RWA news feeds (verified working RSS/Atom) ----
FEEDS = [
    # (name, url, lang[, cat])
    # Global tier-1 ORIGINAL-source wires (they originate stories; Korean outlets re-report them —
    # so these should win as the canonical version of any story they share). General-finance feeds:
    # the crypto/RWA relevance gate keeps only their on-topic original reporting.
    ("Bloomberg",     "https://feeds.bloomberg.com/markets/news.rss", "en"),
    ("Bloomberg",     "https://feeds.bloomberg.com/technology/news.rss", "en"),
    ("CNBC",          "https://www.cnbc.com/id/10000664/device/rss/rss.html", "en"),
    ("CoinDesk",      "https://www.coindesk.com/arc/outboundfeeds/rss/", "en"),
    ("Cointelegraph", "https://cointelegraph.com/rss", "en"),
    ("Cointelegraph RWA", "https://cointelegraph.com/rss/tag/rwa", "en"),
    ("Cointelegraph Tokenization", "https://cointelegraph.com/rss/tag/tokenization", "en"),
    ("The Defiant",   "https://thedefiant.io/api/feed", "en"),
    ("The Block",     "https://www.theblock.co/rss.xml", "en"),
    ("Blockworks",    "https://blockworks.com/feed", "en"),
    ("Decrypt",       "https://decrypt.co/feed", "en"),
    ("CryptoBriefing","https://cryptobriefing.com/feed/", "en"),
    ("Bankless",      "https://www.bankless.com/rss/feed", "en"),
    ("Tokeny",        "https://www.tokeny.com/feed/", "en"),
    ("Dune",          "https://dune.com/blog/feed", "en"),
    ("SEC",           "https://www.sec.gov/news/pressreleases.rss", "en"),   # official US regulator
    # Korean digital-asset media — Korean企業 blockchain/tokenization coverage
    ("디지털에셋",     "https://www.digitalasset.works/rss/allArticle.xml", "ko"),
    ("블록미디어",     "https://www.blockmedia.co.kr/feed", "ko"),
    ("토큰포스트",     "https://www.tokenpost.kr/rss", "ko"),
    # Real-time breaking macro/market desk (terminal-sourced headlines). This is the honest,
    # reliable substitute for First Squawk / Walter Bloomberg: those are X accounts whose only
    # free bridge (Twitter's public syndication timeline) has been frozen since Oct-2024, and
    # nitter is dead. Investinglive/ForexLive carries the same class of fast market-moving
    # headlines via proper RSS. 'macro' items use the macro relevance gate, not the crypto gate.
    ("Investinglive", "https://www.forexlive.com/feed/news", "en", "macro"),
]
# macro/big-news relevance gate — only high-impact market-moving headlines pass (not currency ticks)
MACRO_RE = re.compile(
    r'\bfed\b|fomc|federal reserve|rate (?:cut|hike|decision)|interest rate|\bcpi\b|inflation|'
    r'\bpce\b|treasur|\byield|\bsec\b|regulat|tariff|sanction|\bwar\b|ceasefire|central bank|'
    r'\bpboc\b|\becb\b|\bboj\b|\bboe\b|recession|\bgdp\b|jobs report|nonfarm|payroll|debt ceiling|'
    r'default|downgrade|stimulus|\bstocks?\b|equit|nasdaq|s&p|dow jones|crude|\boil\b|\bgold\b|'
    r'bitcoin|crypto|stablecoin|tokeniz', re.I)

# ---- importance scoring ----
HIGH = {  # core RWA tokenized-equity entities
    'tokenized stock':10,'tokenized equity':10,'tokenized securities':9,'tokenized share':9,
    'xstocks':9,'backed finance':8,'dinari':9,'ondo':8,'securitize':7,'backpack':8,
    'robinhood':7,'kraken':6,'superstate':7,'plume':6,'centrifuge':6,'tokeny':6,
    'blackrock':8,'buidl':8,'franklin templeton':7,'benji':6,'coinbase':6,'binance':6,
}
MID = {  # mechanism / asset class
    'rwa':6,'real-world asset':6,'real world asset':6,'tokenization':6,'tokenize':5,
    'tokenized treasury':7,'tokenized fund':6,'tokenized credit':5,'onchain equit':7,
    'on-chain equit':7,'stablecoin':3,'erc-3643':5,'custody':3,'custodian':4,
}
VENUE = {'base':3,'solana':3,'arbitrum':3,'bnb chain':3,'ethereum':2,'ondo chain':4}
REG = {'sec ':6,'regulation':5,'approved':5,'license':5,'mica':5,'etf':5,'institutional':5,
       'nasdaq':5,'dtcc':5,'no-action':6}
MULT = [('billion',1.5),('mainnet',1.3),('launch',1.3),('goes live',1.3),('go live',1.25),
        ('partnership',1.15),('integration',1.12),('hack',1.4),('exploit',1.4),
        ('lawsuit',1.3),('sec charges',1.4),('halt',1.3)]

# ---- Korean-language scoring (applied only to ko-tagged feeds; safe within Hangul text) ----
KO_HIGH = {  # core RWA/tokenization + Korean firms active in blockchain/digital assets
    '토큰증권': 10, '증권형 토큰': 10, '증권토큰': 9, '토큰화': 9, '실물자산': 8, '스테이블코인': 7,
    '디지털자산': 7, '가상자산': 6, '블록체인': 6, '온체인': 6, '스테이킹': 4, '수탁': 5, '커스터디': 5,
    '삼성': 6, '우리은행': 5, '우리카드': 5, '우리금융': 5, '신한': 5, '국민은행': 5, '하나은행': 5,
    '하나금융': 5, '카카오': 6, '토스': 6, '네이버': 6, '미래에셋': 6, '엔에이치엔': 5, 'nhn': 5,
    '엘지': 4, 'sk텔레콤': 5, '케이티': 4, '한화': 5, '비트코인': 3, '이더리움': 3, '리플': 4, '테더': 4,
}
KO_REG = {  # regulatory / policy
    '금융위': 7, '금융위원회': 7, '금감원': 6, '규제': 5, '인가': 5, '라이선스': 5, '가이드라인': 5,
    '증권신고서': 5, '제재': 6, '소송': 5, '승인': 4, '특금법': 6, '자본시장법': 6, '허가': 4, '입법': 5,
}
KO_MULT = [('출시', 1.25), ('발행', 1.2), ('상장', 1.25), ('세계 최초', 1.4), ('국내 최초', 1.35),
           ('파트너', 1.15), ('협력', 1.12), ('진출', 1.2), ('해킹', 1.4), ('중단', 1.2)]
KO_CORE_RE = re.compile('|'.join([  # topical gate for Korean items
    '토큰', '블록체인', '가상자산', '디지털자산', '스테이블코인', '증권형', '실물자산', 'rwa', 'sto',
    '온체인', '수탁', '커스터디', '스테이킹', '비트코인', '이더리움', '리플', '금융위', '규제', '상장',
    '거래소', '메인넷', '지갑', '결제', '증권사', '디파이', '웹3', 'web3']))
KO_REGFLAG_RE = re.compile('|'.join([
    '규제', '금융위', '금감원', '제재', '소송', '인가', '라이선스', '가이드라인', '승인', '특금법',
    '자본시장법', '허가', '입법', '과징금', '수사', '기소', '위법', '불법']))
# daily-recap / price-snapshot / market-column noise — low-signal, drop from the feed.
# (targets recurring column tags; leaves valuable brackets like [단독]/[영상]/[네이버·두나무 M&A] intact)
KO_NOISE_RE = re.compile(
    r'\[\s*(개장시황|마감시황|장중시황|코인\s?시황|코인\s?top|국내증시|해외증시|선물[^\]]*|kol[^\]]*|'
    r'아침코인|주간\s?알트|주간알트|차트\s?분석|마켓\s?워치|특징주|채굴|주간\s?동향|주간알트|'
    r'주요\s?(경제|일정)[^\]]*|오늘의[^\]]*|이번\s?주[^\]]*일정|급등락|주간\s?코인|데일리|주간\s?전망|'
    r'주간\s?리포트|코인\s?시세|가격\s?동향|주간\s?정리|한주\s?동안|시황)', re.I)
# Korea-domestic signals: Korean firms, regulators, market/geography terms. Used to keep Korean
# outlets focused on KOREAN news — their re-reports of GLOBAL stories (no Korea angle) are dropped
# so the global tier-1 ORIGINAL carries the story instead (Korean outlets re-report; originals originate).
KO_DOMESTIC_RE = re.compile('|'.join([
    '삼성', '카카오', '토스', '우리은행', '우리카드', '우리금융', '신한', '하나은행', '하나금융', '국민은행',
    '기업은행', '농협', '미래에셋', '한국투자', '네이버', '엔에이치엔', 'nhn', '코인원', '빗썸', '업비트',
    '두나무', '고팍스', '코빗', '위믹스', '위메이드', '카이아', '클레이', '넷마블', '컴투스', '다날', '쿠팡',
    '엘지', 'lg전자', 'lg씨엔에스', 'lg cns', 'sk텔레콤', 'sk하이닉스', '케이티', '한화', '롯데', '카카오뱅크',
    '금융위', '금감원', '한국은행', '예금보험', '자본시장법', '특금법', '원화', '국내', '한국', '코스피',
    '코스닥', '기재부', '과기부', '전북은행', '카카오페이', '토스뱅크', '케이뱅크', '한국거래소', '예탁결제원']), re.I)

def score(title, summary, lang='en'):
    text = (title + ' ' + summary).lower()
    s = 0.0
    if lang == 'ko':
        for d in (KO_HIGH, KO_REG):
            for k, w in d.items():
                if k in text: s += w
        for term, m in KO_MULT:
            if term in text: s *= m
        return s
    for d in (HIGH, MID, VENUE, REG):
        for k, w in d.items():
            if k in text: s += w
    for term, m in MULT:
        if term in text: s *= m
    return s

# topical gate (word-boundary): an item must genuinely be about crypto/RWA/finance,
# otherwise substring scoring can let off-topic headlines (e.g. sports) slip through.
CORE_RE = re.compile(
    r'token(?:iz|ized|ization)|\brwa\b|real[\s-]?world asset|xstock|backpack|\bondo\b|dinari|'
    r'securitize|backed finance|buidl|on[\s-]?chain equit|onchain equit|\bsec\b|\betfs?\b|'
    r'stablecoin|\bcustod|blackrock|franklin templeton|robinhood|\bkraken\b|nasdaq|\bdtcc\b|'
    r'tokenized (?:stock|equit|securit|treasur|fund|share|bond|credit)|treasur(?:y|ies)|'
    r'\bequit(?:y|ies)\b|\bsecuriti(?:es|zation)\b|brokerage|\bcusip\b|prime broker|'
    r'\bmica\b|money market fund|\bmmf\b|asset manager|institutional')

def is_relevant(title, summary, lang='en'):
    text = (title + ' ' + summary).lower()
    return bool((KO_CORE_RE if lang == 'ko' else CORE_RE).search(text))

# regulation / license / legal-action news → flagged red on the frontend (highest reader priority)
REGFLAG_RE = re.compile(
    r'regulat|licen[sc]|\bsec\b|\bcftc\b|\bdoj\b|\bfca\b|\besma\b|\bmica\b|lawsuit|\bsue[sd]?\b|'
    r'\bcourt\b|\bban\b|banned|sanction|enforce|crackdown|complian|\bfine[sd]?\b|penalt|settlement|'
    r'\bfraud|investigat|subpoena|approv|crimina|illegal|probe|charges|halt(?:ed|s)?\b|delist')
def news_flag(title, summary, lang='en'):
    text = (title + ' ' + summary).lower()
    return 'reg' if (KO_REGFLAG_RE if lang == 'ko' else REGFLAG_RE).search(text) else ''

# Interpretation framework (not fabricated facts): classify a story, then state what it MEANS
# and how the RWA market should read it. First matching rule wins. Attached to important items.
INSIGHT_RULES = [
    (r'\bsec\b.*(approv|clear|green ?light|no[- ]action|allow|permit)|approv.*\bsec\b|cleared to (offer|trade)|registration|transfer agent',
     '규제 당국이 토큰화 상품에 청신호(승인/등록)',
     '규제 명확화는 기관 자금 유입의 최대 전제조건 — RWA 시장 확장에 강한 순풍. 승인받은 발행처는 선점 효과.',
     'A regulator cleared/registered a tokenized product',
     'Regulatory clarity is the #1 unlock for institutional capital — a strong RWA tailwind; the approved issuer gets first-mover advantage.'),
    (r'lawsuit|\bsue[sd]?\b|charges|enforce|fraud|complaint|crackdown|\bban\b|banned|penalt|investigat|hacked?|drained|exploit|delist',
     '규제·법적 리스크 또는 보안 사고',
     '단기 불확실성 요인 — 다만 규제 정비 과정의 일부. 사고가 특정 프로토콜에 국한되면 오히려 견고한 플레이어로 자금 이동.',
     'A legal/regulatory risk or a security incident',
     'Near-term uncertainty — but part of the rule-setting cycle. If contained, capital tends to rotate toward the more robust players.'),
    (r'blackrock|jpmorgan|jp morgan|goldman|morgan stanley|nasdaq|\bdtcc\b|franklin|apollo|state street|\bciti\b|mastercard|\bvisa\b|\bbank\b|invesco|kkr|wisdomtree',
     '대형 전통금융(TradFi) 기관의 온체인 행보',
     '기관 검증 = RWA의 신뢰·규모 확대 신호. 발행액·TVL 성장의 직접 촉매이자, RWA 관련 주식(발행·인프라)에 수혜 가능성.',
     'A major TradFi institution moving on-chain',
     'Institutional validation → credibility & scale for RWA; a direct catalyst for issued value/TVL, and potentially a tailwind for RWA-related equities.'),
    (r'partner|integrat|adds? support|\bdeal\b|collaborat|rail',
     '전통금융–온체인 연결(레일/파트너십) 강화',
     '유통 채널·결제 레일 확장 = RWA 접근성↑, 채택 속도 가속. 네트워크 효과로 승자 굳히기.',
     'A TradFi↔on-chain rail/partnership',
     'Wider distribution & payment rails → easier access, faster adoption; network effects entrench leaders.'),
    (r'record|all[- ]time|\bath\b|largest|\btops?\b|hits? \$|surge|overtak|reaches',
     'RWA 거래량·규모 신기록/모멘텀',
     '수요 확인 신호 — 단, 지속성(신규 자본 유입 vs 기존 자본 회전)을 구분해서 봐야 함. 발행액이 함께 늘면 진짜 확장.',
     'A new RWA volume/size record or momentum',
     'A demand signal — but check durability (new inflows vs. churn). Real expansion is when issued value grows alongside volume.'),
    (r'stablecoin|\busdc\b|\busdt\b|rlusd|pyusd|usyc|tokenized (?:deposit|cash|treasur|bank)',
     '스테이블코인·토큰화 현금/국채 확장',
     '온체인 정산 통화 확대 = RWA 거래의 기반 인프라 성장. 섹터 확장의 선행지표(대시보드 스테이블코인 지표와 연동).',
     'Stablecoin / tokenized-cash / treasury expansion',
     'More on-chain settlement money = base infra for RWA trading — a leading indicator of expansion (tracks the dashboard stablecoin metric).'),
    (r'tokeniz|\blists?\b|goes live|debut|on[- ]?chain|equit|securit',
     '새 토큰화 상품/종목 출시·확대',
     '발행처·종목 경쟁 심화 → 유동성·선택지 확대. 다만 거래는 소수 인기 종목에 집중되는 경향(꼬리 종목 유동성 주의).',
     'A new tokenized product/listing expands',
     'More issuers/tokens → deeper liquidity & choice, but trading concentrates in a few names (watch thin long-tail liquidity).'),
]
def news_insight(title, summary):
    text = (title + ' ' + (summary or '')).lower()
    for rx, km, ki, em, ei in INSIGHT_RULES:
        if re.search(rx, text):
            return {'ko': km, 'ko2': ki, 'en': em, 'en2': ei}
    return None

_cache = {"t": 0, "data": [], "archive": {}, "top5": []}
_lock = threading.Lock()
_NEWS_STORE = os.path.join(BASE, 'news_store.json')
ARCHIVE_MAX = 260          # ~5 pages of 50 + headroom
ARCHIVE_DAYS = 14          # keep two weeks so users can page back through time
# outlet tiers for the Top-5 "impact" proxy (we have no real view counts; corroboration + tier + recency)
SRC_TIER = {'CoinDesk': 2.0, 'Cointelegraph': 1.5, 'The Block': 2.0, 'Decrypt': 1.5,
            'Bloomberg': 2.5, 'CNBC': 2.0, 'Reuters': 2.5, 'The Defiant': 1.5, 'Blockworks': 1.5,
            'SEC': 2.5, 'Investinglive': 1.2, 'Bankless': 1.2, '블록미디어': 1.2, '디지털에셋': 1.2}
# canonical-source preference for clustering: when the same story appears from several outlets,
# show the most ORIGINAL/tier-1 one as the headline (Korean outlets re-report globals → rank lower;
# their Korea-origin stories are single-source, so this never suppresses them).
SRC_RANK = {'SEC': 6, 'Bloomberg': 6, 'Reuters': 6,
            'CoinDesk': 5, 'The Block': 5, 'CNBC': 5, 'WSJ': 5,
            'Cointelegraph': 4, 'Cointelegraph RWA': 4, 'Cointelegraph Tokenization': 4,
            'Decrypt': 4, 'Blockworks': 4, 'The Defiant': 4,
            'Bankless': 3, 'CryptoBriefing': 3, 'Tokeny': 3, 'Dune': 3, 'Investinglive': 3,
            '디지털에셋': 2, '블록미디어': 2, '토큰포스트': 2}
def _rank(x):
    return SRC_RANK.get(x.get('source', ''), 3)

def _key(x):
    return (x.get('link') or '').strip() or ('t:' + (x.get('title') or ''))

def compute_top5(items):
    """Today's most impactful global stories. Honest proxy for '조회수·반응·파급력':
    multi-outlet corroboration (how many desks picked it up) + outlet tier + recency + score."""
    now = time.time()
    def impact(x):
        age_h = (now - (x.get('ts') or now)) / 3600
        rec = math.exp(-age_h / 30.0)                      # ~1.25-day half-life
        corr = max((x.get('cluster', 1) - 1), 0)           # picked up by N extra outlets
        sc = min((x.get('raw_score') or x.get('score') or 0), 30) / 30.0
        flag = 1.0 if x.get('flag') == 'reg' else 0.0
        tier = SRC_TIER.get(x.get('source', ''), 0.6)
        return (corr * 3.5 + sc * 4.0 + flag * 2.0 + tier) * (0.35 + 0.65 * rec)
    # favor globally-relevant stories (drop pure single-currency FX ticks that slipped through)
    cand = [x for x in items if (x.get('ts') or 0) > now - 3 * 86400]
    ranked = sorted(cand, key=impact, reverse=True)
    def kw(x):   # distinguishing words for near-duplicate detection across outlets
        stop = {'the', 'and', 'for', 'with', 'plans', 'says', 'over', 'into', 'from', 'that'}
        return set(w for w in re.findall(r'[a-z]{4,}|[가-힣]{2,}', (x.get('title') or '').lower())
                   if w not in stop)
    out, seen, seen_kw = [], set(), []
    for x in ranked:
        k = _key(x)
        if k in seen:
            continue
        kws = kw(x)
        # skip a story already represented by a higher-ranked near-duplicate (same event, other outlet)
        if any(len(kws & prev) >= 3 for prev in seen_kw):
            continue
        seen.add(k)
        seen_kw.append(kws)
        out.append({'title': x.get('title', ''), 'title_ko': x.get('title_ko', ''),
                    'title_zh': x.get('title_zh', ''), 'link': x.get('link', ''),
                    'source': x.get('source', ''), 'flag': x.get('flag', ''),
                    'cat': x.get('cat', 'crypto'), 'impact': round(impact(x), 1)})
        if len(out) >= 5:
            break
    return out

def _load_store():
    try:
        with open(_NEWS_STORE, encoding='utf-8') as f:
            items = json.load(f)
        arc = {_key(x): x for x in items}
        items = sorted(arc.values(), key=lambda x: -(x.get('ts') or 0))
        with _lock:
            _cache['archive'] = arc
            _cache['data'] = items
            _cache['top5'] = compute_top5(items)
            _cache['t'] = time.time()
        sys.stderr.write(f"news: loaded {len(items)} archived items from disk\n")
    except Exception:
        pass

def _merge_archive(fresh):
    """Merge a fresh build into the rolling archive so stories persist after they leave the RSS
    window (lets the UI page 1..N back through time). Prune by count + age."""
    now = time.time()
    with _lock:
        arc = _cache.get('archive') or {}
        for it in fresh:
            if (it.get('ts') or 0) > now + 3600:   # clamp bad/future dates so they can't pin to the top
                it['ts'] = now
            k = _key(it)
            if k in arc:
                arc[k].update(it)            # refresh score/cluster/translations, keep first-seen
            else:
                arc[k] = it
        for x in arc.values():               # heal any previously-stored future timestamps
            if (x.get('ts') or 0) > now + 3600:
                x['ts'] = now
        cutoff = now - ARCHIVE_DAYS * 86400
        items = [x for x in arc.values() if (x.get('ts') or now) >= cutoff]
        items.sort(key=lambda x: -(x.get('ts') or 0))
        items = items[:ARCHIVE_MAX]
        _cache['archive'] = {_key(x): x for x in items}
        _cache['data'] = items
        _cache['top5'] = compute_top5(items)
        _cache['t'] = now
    try:
        with open(_NEWS_STORE, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False)
    except Exception as e:
        sys.stderr.write(f"news store save: {e}\n")

def fetch_feed(name, url, out, lang='en', cat='crypto'):
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; OnchainEquities/1.0)',
            'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml, */*'})
        raw = urllib.request.urlopen(req, timeout=8).read()
        root = ET.fromstring(raw)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        items = root.findall('.//item')
        atom = False
        if not items:
            items = root.findall('.//atom:entry', ns); atom = True
        for it in items[:30]:
            if atom:
                title = (it.findtext('atom:title', '', ns) or '').strip()
                link_el = it.find('atom:link', ns)
                link = link_el.get('href') if link_el is not None else ''
                summary = (it.findtext('atom:summary', '', ns) or it.findtext('atom:content', '', ns) or '')
                pub = it.findtext('atom:updated', '', ns) or it.findtext('atom:published', '', ns)
            else:
                title = (it.findtext('title', '') or '').strip()
                link = (it.findtext('link', '') or '').strip()
                summary = (it.findtext('description', '') or '')
                pub = it.findtext('pubDate', '') or it.findtext('{http://purl.org/dc/elements/1.1/}date', '')
            if not title: continue
            summary = re.sub('<[^>]+>', '', summary)[:300]
            ts = 0
            try:
                pub = (pub or '').strip()
                dt = parsedate_to_datetime(pub) if ',' in pub else datetime.datetime.fromisoformat(pub.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    # naive timestamp (no tz in the feed) — assume the outlet's local zone, else the
                    # server (UTC) would read a KST time as 9h in the FUTURE. Korean feeds → KST.
                    tz = datetime.timezone(datetime.timedelta(hours=9)) if lang == 'ko' else datetime.timezone.utc
                    dt = dt.replace(tzinfo=tz)
                ts = dt.timestamp()
                if ts > time.time() + 3600:   # guard: never let a bad/future date float to the top
                    ts = time.time()
            except Exception:
                ts = 0
            out.append({'title': title, 'link': link, 'source': name, 'summary': summary,
                        'ts': ts, 'lang': lang, 'cat': cat, 'raw_score': score(title, summary, lang)})
    except Exception as e:
        sys.stderr.write(f"feed err {name}: {e}\n")

def build_news():
    items = []
    threads = []
    for feed in FEEDS:
        name, url, lang = feed[0], feed[1], feed[2]
        cat = feed[3] if len(feed) > 3 else 'crypto'
        t = threading.Thread(target=fetch_feed, args=(name, url, items, lang, cat)); t.start(); threads.append(t)
    for t in threads: t.join(timeout=10)
    now = time.time()
    # corroboration clustering: merge the SAME story arriving from different feeds/titles.
    def keywords(title):
        return set(w for w in re.findall(r'[가-힣]{2,}|[a-z]{4,}', title.lower()) if w not in
                   {'with','that','this','from','have','will','what','when','your','about','crypto',
                    'says','into','over','after','than','plans','launch','launches','crypto’s',
                    # Korean generic domain words — non-distinguishing, must not drive clustering
                    '스테이블코인','스테이블','토큰','토큰화','블록체인','비트코인','이더리움','가상자산',
                    '디지털','디지털자산','자산','코인','발행','시장','규제','금융','투자','서비스','출시',
                    '도입','진출','관련','온체인','거래소','거래','결제','증권','기술','사업','계획','추진',
                    '지원','강화','확대','협력','참여','추진','도전','전망','예정','공개','한다','했다'})
    def norm_title(t):   # keep Hangul too, else every Korean title collapses to '' and cross-merges
        return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9가-힣 ]', '', (t or '').lower())).strip()
    clusters = []
    for it in items:
        kw = keywords(it['title']); nt = norm_title(it['title'])
        # keep the query string — many CMSs (e.g. digitalasset.works ?idxno=) put the article id there;
        # only drop tracking params, else every article collapses onto one base URL.
        link = (it.get('link') or '').strip()
        link = re.sub(r'([?&])(utm_[^=&]*|ref|fbclid|gclid|igshid)=[^&]*', r'\1', link)
        link = re.sub(r'[?&]+$', '', link).rstrip('/')
        placed = False
        for c in clusters:
            jac = (len(kw & c['fkw']) / len(kw | c['fkw'])) if (kw or c['fkw']) else 0
            # merge if: identical title / same URL / strong keyword overlap / high title similarity
            if (nt and nt == c['nt']) or (link and link == c['link']) or len(kw & c['fkw']) >= 3 or jac >= 0.5:
                c['items'].append(it); c['kw'] |= kw; placed = True; break
        if not placed:
            clusters.append({'kw': set(kw), 'fkw': kw, 'nt': nt, 'link': link, 'items': [it]})
    ranked = []
    for c in clusters:
        # canonical article = highest-rank ORIGINAL source (tie-break by score), so a global tier-1
        # original represents the story rather than a Korean re-report that clustered with it.
        best = max(c['items'], key=lambda x: (_rank(x), x['raw_score']))
        top_raw = max(x['raw_score'] for x in c['items'])   # score the story on its best evidence
        age_h = (now - best['ts']) / 3600 if best['ts'] else 72
        decay = math.exp(-age_h / 24) if best['ts'] else 0.2
        final = (top_raw + 2 * (len(c['items']) - 1)) * decay
        best = dict(best)
        best['age_h'] = round(age_h, 1)
        best['cluster'] = len(c['items'])
        best['score'] = round(final, 1)
        lg = best.get('lang', 'en')
        cat = best.get('cat', 'crypto')
        if lg == 'ko':
            if KO_NOISE_RE.search(best['title']):   # skip daily-recap / price-snapshot columns
                continue
            # Korean outlet is the canonical source here → no global original clustered with it.
            # Keep it only if it's a KOREAN story; drop global re-reports (global tier-1 feeds carry those).
            if not KO_DOMESTIC_RE.search(best['title'] + ' ' + best.get('summary', '')):
                continue
        best['flag'] = news_flag(best['title'], best.get('summary', ''), lg)
        # important items get an interpretation (meaning + RWA implication): reg-flagged,
        # corroborated by 2+ sources, or high-scoring
        if best['flag'] == 'reg' or best['cluster'] >= 2 or best['score'] >= 15:
            ins = news_insight(best['title'], best.get('summary', ''))
            if ins:
                best['insight'] = ins
        if cat == 'macro':
            # breaking macro/big-news lane: use the macro gate (crypto keywords not required)
            if MACRO_RE.search((best['title'] + ' ' + best.get('summary', '')).lower()):
                ranked.append(best)
        # crypto lane: keep only items that pass BOTH the score AND the topical gate
        elif best['raw_score'] >= 6 and is_relevant(best['title'], best.get('summary', ''), lg):
            ranked.append(best)
    # show newest first (common sense for a news feed); relevance filter + dedup already applied above
    ranked.sort(key=lambda x: -(x.get('ts') or 0))
    # soft-cap each lane so no single desk crowds out the others: Korean, breaking-macro, and
    # global crypto/RWA. Keep the newest of each up to its cap, then re-sort newest-first.
    KO_CAP, MACRO_CAP = 16, 8
    ko = [r for r in ranked if r.get('lang') == 'ko'][:KO_CAP]
    macro = [r for r in ranked if r.get('lang') != 'ko' and r.get('cat') == 'macro'][:MACRO_CAP]
    other = [r for r in ranked if r.get('lang') != 'ko' and r.get('cat') != 'macro']
    top = ko + macro + other
    top.sort(key=lambda x: -(x.get('ts') or 0))
    top = top[:50]
    # keep ts + raw_score: the archive orders/pages by ts and ranks Top-5 impact by raw_score
    for r in top:                       # localize into all 3 languages, respecting the source language
        if r.get('lang') == 'ko':       # Korean source: keep original as KO, translate out to EN/ZH
            r['title_ko'] = r['title']; r['summary_ko'] = r.get('summary', '')
            r['title'] = _translate(r['title_ko'], 'en', 'ko')
            r['summary'] = _translate(r['summary_ko'], 'en', 'ko')
            r['title_zh'] = _translate(r['title_ko'], 'zh-CN', 'ko')
            r['summary_zh'] = _translate(r['summary_ko'], 'zh-CN', 'ko')
            if r.get('insight') is None:            # Korean items: derive insight from the EN translation
                ins = news_insight(r['title'], r.get('summary', ''))
                if ins: r['insight'] = ins
        else:                            # English source: translate into KO + ZH
            r['title_ko'] = _translate(r['title'], 'ko')
            r['summary_ko'] = _translate(r.get('summary', ''), 'ko')
            r['title_zh'] = _translate(r['title'], 'zh-CN')
            r['summary_zh'] = _translate(r.get('summary', ''), 'zh-CN')
    return top

# ---- professional finance/crypto glossary ----
# Free Google Translate literalizes jargon (vault→금고, mint→조폐국, rally→집회…).
# Fix: protect glossary terms with placeholders (verified to survive translation: "XQV7XQ"),
# then restore the proper domain term per language. Specific/longer patterns MUST come first.
GLOSS = [
    # phrase-level (most specific first)
    (r'defi vaults?',              'DeFi 볼트',        'DeFi 金库'),
    (r'yield farming',             '일드 파밍',         '收益耕作'),
    (r'liquidity pools?',          '유동성 풀',         '流动性池'),
    (r'tokenized stocks?|tokenized equit(?:y|ies)', '토큰화 주식', '代币化股票'),
    (r'tokenized treasur(?:y|ies)','토큰화 국채',       '代币化国债'),
    (r'security tokens?',          '증권형 토큰',       '证券型代币'),
    (r'governance tokens?',        '거버넌스 토큰',     '治理代币'),
    (r'smart contracts?',          '스마트 컨트랙트',   '智能合约'),
    (r'order ?books?',             '오더북',            '订单簿'),
    (r'market makers?',            '마켓메이커',        '做市商'),
    (r'broker-?dealers?',          '브로커딜러',        '经纪交易商'),
    (r'prediction markets?',       '예측 시장',         '预测市场'),
    (r'proof[ -]of[ -]reserves?',  '준비금 증명',       '储备证明'),
    (r'proof[ -]of[ -]stake',      '지분증명(PoS)',     '权益证明(PoS)'),
    (r'proof[ -]of[ -]work',       '작업증명(PoW)',     '工作量证明(PoW)'),
    (r'mint/redeem|mint-and-redeem','발행/상환',        '铸造/赎回'),
    (r'bull markets?',             '강세장',            '牛市'),
    (r'bear markets?',             '약세장',            '熊市'),
    (r'gas fees?',                 '가스비',            'Gas费'),
    (r'rug ?pulls?',               '러그풀',            'Rug Pull'),
    (r'meme ?coins?',              '밈코인',            '迷因币'),
    (r'fee switch',                '수수료 스위치',     '费用开关'),
    (r'layer[ -]?2\b|l2\b',        '레이어2',           'Layer2'),
    # single terms
    (r'vaults?',                   '볼트',              '金库'),
    (r'restaking',                 '리스테이킹',        '再质押'),
    (r'staking',                   '스테이킹',          '质押'),
    (r'airdrops?',                 '에어드랍',          '空投'),
    (r'minting|mints?',            '민팅',              '铸造'),
    (r'stablecoins?',              '스테이블코인',      '稳定币'),
    (r'liquidity',                 '유동성',            '流动性'),
    (r'perpetuals?|perps?',        '무기한 선물',       '永续合约'),
    (r'slippage',                  '슬리피지',          '滑点'),
    (r'on-?chain',                 '온체인',            '链上'),
    (r'off-?chain',                '오프체인',          '链下'),
    (r'tokenization',              '토큰화',            '代币化'),
    (r'custodians?',               '수탁기관',          '托管机构'),
    (r'custody',                   '커스터디',          '托管'),
    (r'rall(?:y|ies)',             '랠리',              '上涨行情'),
    (r'validators?',               '밸리데이터',        '验证者'),
    (r'mainnet',                   '메인넷',            '主网'),
    (r'testnet',                   '테스트넷',          '测试网'),
    (r'halving',                   '반감기',            '减半'),
    (r'redemptions?',              '상환',              '赎回'),
    (r'delist(?:ing|ed|s)?',       '상장폐지',          '下架'),
    (r'exploits?',                 '익스플로잇',        '漏洞攻击'),
    (r'buybacks?',                 '바이백',            '回购'),
    (r'rollups?',                  '롤업',              'Rollup'),
    (r'wrapped',                   '랩드',              '封装'),
    (r'bridges?',                  '브리지',            '跨链桥'),
]
_GLOSS_RE = [(re.compile(r'\b(?:' + p + r')\b', re.I), ko, zh) for p, ko, zh in GLOSS]
# company/protocol names Google mistranslates as common nouns (Strategy→전략, Jupiter→목성,
# Backpack→배낭, Circle→원…). Case-SENSITIVE match; restored verbatim in every language.
_ENTITIES = ['Backpack', 'Jupiter', 'Circle', 'Strategy', 'Sunrise', 'Backed', 'Phantom',
             'Kamino', 'Raydium', 'Mirror', 'Sonic', 'Sky']
_ENT_RE = re.compile(r'\b(' + '|'.join(_ENTITIES) + r')\b')
# placeholder + optional trailing Korean particle (josa) so we can re-agree it with the
# restored word's final consonant (받침): 온체인+가 → 온체인이, 강세장+를 → 강세장을
_PH_RE = re.compile(r'XQV\s*(\d+)\s*XQ(으로|이|가|을|를|은|는|과|와|로)?', re.I)

# English names: particle follows Korean PRONUNCIATION (Circle=서클→이, Backpack=백팩→이)
_ENT_JOSA = {'Backpack': (True, False), 'Circle': (True, True), 'Phantom': (True, False),
             'Raydium': (True, False), 'Sonic': (True, False)}   # (has-batchim, ends-in-ㄹ)

def _josa_fix(term, josa):
    if not josa:
        return ''
    if term in _ENT_JOSA:
        b, rieul = _ENT_JOSA[term]
        jong = 8 if rieul else (1 if b else 0)
    else:
        jong = None
        for ch in reversed(term):      # last Hangul syllable decides the particle form
            o = ord(ch)
            if 0xAC00 <= o <= 0xD7A3:
                jong = (o - 0xAC00) % 28
                break
    b = (jong is not None and jong != 0)   # Latin/digit endings → treat as no-batchim
    if josa in ('이', '가'):  return '이' if b else '가'
    if josa in ('을', '를'):  return '을' if b else '를'
    if josa in ('은', '는'):  return '은' if b else '는'
    if josa in ('과', '와'):  return '과' if b else '와'
    if josa in ('으로', '로'): return '로' if (not b or jong == 8) else '으로'
    return josa

def _translate(text, tl='ko', sl='en'):
    text = (text or '').strip()
    if not text:
        return ''
    # 1) protect entity names (verbatim) + glossary terms so the MT can't literalize them
    lang_i = 0 if tl.startswith('ko') else 1
    repl = []
    def _sub(m, term):
        repl.append(term)
        return f'XQV{len(repl)-1}XQ'
    prot = _ENT_RE.sub(lambda m: _sub(m, m.group(0)), text)   # keep names as-is (Strategy, Jupiter…)
    if sl == 'en':                 # glossary is English→target; only apply when source IS English
        for rx, ko, zh in _GLOSS_RE:
            term = (ko, zh)[lang_i]
            if not term:
                continue
            prot = rx.sub(lambda m, t=term: _sub(m, t), prot)
    try:
        u = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=" + sl + "&tl="
             + tl + "&dt=t&q=" + urllib.parse.quote(prot[:1800]))
        d = json.loads(_get(u, 10))
        out = ''.join(seg[0] for seg in d[0] if seg and seg[0])
        if not out:
            return text
        out = re.sub(r'XQ(?=XQV)', 'XQ ', out, flags=re.I)   # re-split glued adjacent placeholders
        # 2) restore terms; for Korean, re-agree the trailing particle with the word's 받침
        def _restore(m):
            i = int(m.group(1)); josa = m.group(2) or ''
            if i >= len(repl):
                return m.group(0)
            term = repl[i]
            if tl.startswith('ko'):
                return term + _josa_fix(term, josa)
            return term + (josa or '')
        out = _PH_RE.sub(_restore, out)
        return out
    except Exception:
        return text  # graceful fallback to English

def _translate_ko(text):
    return _translate(text, 'ko')

def get_news(page=1, size=50, q=''):
    """Return a paged (and optionally searched) slice of the rolling archive + Top-5 + meta."""
    with _lock:
        data = list(_cache['data'])
        top5 = list(_cache['top5'])
    q = (q or '').strip().lower()
    if q:
        def hit(x):
            hay = ' '.join(str(x.get(k, '')) for k in
                           ('title', 'title_ko', 'title_zh', 'summary', 'summary_ko', 'summary_zh', 'source'))
            return q in hay.lower()
        data = [x for x in data if hit(x)]
    total = len(data)
    size = max(1, min(size, 50))
    pages = max(1, (total + size - 1) // size)
    page = max(1, min(page, pages))
    start = (page - 1) * size
    now = time.time()
    items = []
    for x in data[start:start + size]:
        x = dict(x)
        ts = x.get('ts') or 0
        if ts:                       # recompute age at serve time so it stays accurate over time
            x['age_h'] = round(max(0.0, (now - ts) / 3600), 1)
        items.append(x)
    return {'generated': int(_cache['t']), 'total': total, 'page': page, 'pages': pages,
            'size': size, 'query': q, 'top5': top5, 'items': items}

def _news_loop():
    while True:
        try:
            fresh = build_news()
            if fresh:
                _merge_archive(fresh)
                with _lock:
                    n = len(_cache['data'])
                sys.stderr.write(f"news: +{len(fresh)} fresh, archive now {n} items (translated)\n")
        except Exception as e:
            sys.stderr.write(f"news loop: {e}\n")
        time.sleep(240)

# ---- live volume/liquidity refresher (GeckoTerminal Solana + tokens.xyz) ----
def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    return urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', 'ignore')

BP_MINTS = {'SPCX': 'SPCXxcqXj6e5dJDVNovHN8744zkbhM2bYudU45BimGb',
            'MU': 'MUxEsUKSMACyw5fZf68wxf5FLnZVhtU9CwH8uNNGay1',
            'SNDK': 'SNDKbwMUQvZhnLnxLduradgLHG5KrPuKwpnrkkGRhfH',
            'DRAM': 'DRAMjSWR7HRfJKjRkvQWYL2bcaejaVhuxEcjf4pAY4Cw',   # Roundhill Memory ETF
            'SKHY': 'SKHYhSjuRWHgikq8eRKbtBbpABgJSkd7ytQV14i9EQ3',   # SK Hynix — Nasdaq IPO 07-10, tokenized day one
            'BOT':  'BoTx8y9ynfdxf5ZjWtCoBVkff52qKA82ysaLU8ZM6d8T',  # RoboStrategy
            'INTC': 'iNTCy1qTsUEZQe3DSocLz1ZXXai34Gdw8THQh5rxFaF',   # Intel
            'HOOD': 'HooDYv5RewLRiMLnEVq3VJqdqxhuE6c5eYvqejMC3e9A'}  # Robinhood
_addr_map = None
_bp_syms = set(BP_MINTS)
_live = {'t': 0, 'data': {}}

def _discover_backpack():
    # auto-detect new Backpack Securities tokens via CoinGecko category (future-proof)
    out = {}
    try:
        cats = json.loads(_get("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category=backpack-securities-ecosystem&per_page=50", 15))
        for c in cats:
            try:
                d = json.loads(_get(f"https://api.coingecko.com/api/v3/coins/{c['id']}?localization=false&tickers=false&market_data=false&community_data=false&developer_data=false", 15))
                mint = (d.get('platforms') or {}).get('solana')
                if mint: out[d['symbol'].upper()] = mint
                time.sleep(0.5)
            except Exception:
                pass
    except Exception as e:
        sys.stderr.write(f"discover bp: {e}\n")
    return out

def _build_addr_map():
    m = {}
    try:
        page = 0
        while True:
            d = json.loads(_get(f"https://api.backed.fi/api/v2/public/assets?first=200&page={page}"))
            for n in d['nodes']:
                sol = next((dep['address'] for dep in n['deployments'] if dep.get('network') == 'Solana'), None)
                if sol: m[n['symbol']] = sol
            if not d['page'].get('hasNextPage'): break
            page += 1
    except Exception as e:
        sys.stderr.write(f"addrmap: {e}\n")
    for s, mint in BP_MINTS.items(): m[s] = mint
    for s, mint in _discover_backpack().items():  # auto-detect new Backpack tokens
        m[s] = mint; _bp_syms.add(s)
    return m

def _gt_multi(addrs):
    out = {}
    for k in range(0, len(addrs), 30):
        url = "https://api.geckoterminal.com/api/v2/networks/solana/tokens/multi/" + ','.join(addrs[k:k+30])
        for attempt in range(3):
            try:
                for tok in json.loads(_get(url)).get('data', []):
                    a = tok['attributes']; ad = (a.get('address') or '').lower()
                    mc = a.get('market_cap_usd') or a.get('fdv_usd')
                    out[ad] = {'vol': float(a.get('volume_usd', {}).get('h24') or 0),
                               'liq': float(a.get('total_reserve_in_usd') or 0),
                               'mc': float(mc) if mc else None,
                               'px': float(a['price_usd']) if a.get('price_usd') else None}
                break
            except urllib.error.HTTPError as e:
                if e.code == 429: time.sleep(12 * (attempt + 1)); continue
                break
            except Exception:
                break
        time.sleep(4)
    return out

# DexScreener single-token aggregate — FALLBACK ONLY (it omits private/prop AMMs like ZeroFi,
# so it under-counts; but a slightly-low live number beats a frozen/empty page when GT is blocked).
def _dex_token(mint):
    try:
        prs = json.loads(_get("https://api.dexscreener.com/latest/dex/tokens/" + mint, 12)).get('pairs') or []
    except Exception:
        return None
    if not prs:
        return None
    vol = liq = 0.0; px = None; mc = None; topliq = -1.0
    for p in prs:
        if p.get('chainId') != 'solana' or (p.get('baseToken', {}) or {}).get('address') != mint:
            continue
        vol += (p.get('volume', {}) or {}).get('h24', 0) or 0
        l = (p.get('liquidity', {}) or {}).get('usd', 0) or 0
        liq += l
        if l > topliq and p.get('priceUsd'):
            topliq = l; px = float(p['priceUsd'])
            m = p.get('marketCap') or p.get('fdv'); mc = float(m) if m else None
    return {'vol': vol, 'liq': liq, 'px': px, 'mc': mc}

DEX_FALLBACK = ['SPCX', 'MU', 'SNDK', 'DRAM', 'SKHY', 'BOT', 'INTC', 'HOOD', 'SPYx', 'CRCLx', 'NVDAx', 'QQQx', 'SPCXx', 'TSLAx',
                'METAx', 'AAPLx', 'AMZNx', 'COINx', 'MSTRx', 'GOOGLx', 'HOODx', 'NFLXx', 'MSFTx']

def _build_live():
    global _addr_map
    if _addr_map is None or len(_addr_map) < 50:   # rebuild if the first build partially failed
        _addr_map = _build_addr_map()
    addrs = list(_addr_map.values())
    by_addr = _gt_multi(addrs)
    data = {}
    for sym, addr in _addr_map.items():
        g = by_addr.get(addr.lower())
        if g: data[sym] = {**g, 'chain': 'Solana'}
    # Primary volume source = GeckoTerminal token-level h24 (sums ALL pools incl. private/prop AMMs
    # like ZeroFi/SolFi that fill ~40-65% of Jupiter-routed volume). If GT is rate-limiting our
    # egress IP (shared on Render) the whole map comes back near-empty — fall back to DexScreener
    # for the headline tokens so the site never shows a frozen snapshot as live.
    if len(data) < 10:
        sys.stderr.write(f"live: GT sparse ({len(data)}) -> DexScreener fallback\n")
        for sym in DEX_FALLBACK:
            mint = BP_MINTS.get(sym) or _addr_map.get(sym)
            if not mint: continue
            dx = _dex_token(mint)
            if dx and (dx['vol'] or dx['liq']):
                d = data.setdefault(sym, {})
                d['vol'] = dx['vol']; d['liq'] = dx['liq']; d['chain'] = 'Solana'
                if dx.get('px'): d['px'] = dx['px']
                if dx.get('mc'): d['mc'] = dx['mc']
            time.sleep(0.25)
    for sym in data:                    # tag issuer so the frontend can auto-add new tokens
        data[sym]['issuer'] = 'Backpack' if sym in _bp_syms else 'xStocks'
    return data

def _live_loop():
    while True:
        ok = False
        try:
            d = _build_live()
            if d:
                with _lock:
                    _live['t'] = time.time(); _live['data'] = d
                ok = True
                sys.stderr.write(f"live: refreshed {len(d)} tokens\n")
            else:
                sys.stderr.write("live: empty result (all sources failed) — keeping previous cache\n")
        except Exception as e:
            sys.stderr.write(f"live loop: {e}\n")
        time.sleep(60 if ok else 150)   # 60s fresh cadence; back off when sources are failing

# ---- US equity earnings calendar (Nasdaq) — upcoming dates for tokenized-stock tickers ----
_earn = {'t': 0, 'data': []}
EARN_WATCH = {'NVDA','TSLA','AAPL','MSFT','META','AMZN','GOOGL','GOOG','MU','SNDK','COIN','MSTR','SKHY',
              'CRCL','INTC','AMD','HOOD','PLTR','AVGO','NFLX','SMCI','MSTR','QCOM','ORCL','CRM'}
def build_earnings():
    import datetime as _dt
    out = {}
    base = _dt.datetime.utcnow().date()
    empty_streak = 0
    # scan the full next ~4 weeks of weekdays so the client can group by week (this/next/…).
    for off in range(0, 32):
        day = base + _dt.timedelta(days=off)
        if day.weekday() >= 5:                      # skip weekends
            continue
        ds = day.isoformat()
        try:
            d = json.loads(_get("https://api.nasdaq.com/api/calendar/earnings?date=" + ds, 10))
            rows = (d.get('data') or {}).get('rows') or []
        except Exception:
            rows = []
        hit = False
        for r in rows:
            sym = (r.get('symbol') or '').upper()
            if sym in EARN_WATCH and sym not in out:   # each ticker reports once → keep soonest date
                out[sym] = {'symbol': sym, 'name': r.get('name', sym), 'date': ds,
                            'time': r.get('time', ''), 'eps': r.get('epsForecast', '')}
                hit = True
        # once we've collected a healthy set, stop after a quiet stretch (covers ~3 weeks of names)
        empty_streak = 0 if hit else empty_streak + 1
        if len(out) >= 18 and empty_streak >= 4:
            break
        time.sleep(0.2)
    return sorted(out.values(), key=lambda x: x['date'])

def _earn_loop():
    while True:
        got = False
        try:
            d = build_earnings()
            if d:
                with _lock:
                    _earn['t'] = time.time(); _earn['data'] = d
                got = True
                sys.stderr.write(f"earnings: {len(d)} upcoming\n")
            else:
                sys.stderr.write("earnings: empty (calendar fetch failed?) — will retry in 15min\n")
        except Exception as e:
            sys.stderr.write(f"earnings loop: {e}\n")
        time.sleep(6 * 3600 if got else 900)   # 6h after success; retry every 15min while empty

# ---- RWA-related US equities: the "picks-and-shovels" plays (issuers, exchanges, licensed infra) ----
# Curated + ticker-verified (Nasdaq quote). Live price/%chg/mcap from Nasdaq. Informational, not advice.
_rwa = {'t': 0, 'data': []}
RWA_STOCKS = [
    # sym,   category,    Korean note,                                          English note
    ('COIN', 'onchain', '최대 미국 거래소 · 토큰화·커스터디·USDC 지분',            'Largest US exchange · tokenization, custody, USDC stake'),
    ('CRCL', 'onchain', 'USDC 발행 · 토큰화 국채 USYC($2B+)',                    'USDC issuer · tokenized T-bill USYC ($2B+)'),
    ('HOOD', 'onchain', '토큰화 주식 발행 · 자체 온체인 레일(Arbitrum)',          'Issues tokenized stocks · own on-chain rails'),
    ('SECZ', 'onchain', '토큰화 플랫폼 · NYSE Digital 백본 · $4B+ AUM (7/2 상장)', 'Tokenization platform · NYSE Digital backbone · $4B+ AUM (IPO Jul 2)'),
    ('FIGR', 'onchain', 'HELOC 토큰 $20B — 단일 RWA 최대 자산',                  'HELOC token $20B — largest single RWA'),
    ('GLXY', 'onchain', '크립토 금융 · 토큰화 인프라(Solana 대출)',              'Crypto finance · tokenization infra (Solana lending)'),
    ('SOFI', 'onchain', '핀테크 · 토큰화·크립토 진출',                          'Fintech · tokenization/crypto push'),
    ('BLK',  'asset',   'BUIDL $2.5B+ — 최대 토큰화 국채 펀드',                  'BUIDL $2.5B+ — largest tokenized treasury fund'),
    ('BEN',  'asset',   'Franklin — BENJI 토큰화 MMF',                          'Franklin — BENJI tokenized money-market fund'),
    ('APO',  'asset',   'Apollo — ACRED 토큰화 사모신용',                        'Apollo — ACRED tokenized private credit'),
    ('HLNE', 'asset',   'Hamilton Lane — Securitize 통해 펀드 토큰화',            'Hamilton Lane — funds tokenized via Securitize'),
    ('WT',   'asset',   'WisdomTree — 토큰화 펀드 라인(WisdomTree Prime)',        'WisdomTree — tokenized fund suite (Prime)'),
    ('KKR',  'asset',   'KKR — 토큰화 사모펀드(Securitize)',                     'KKR — tokenized private fund (Securitize)'),
    ('IVZ',  'asset',   'Invesco — 토큰화 MMF 신청',                            'Invesco — filed tokenized money-market fund'),
    ('NDAQ', 'infra',   '나스닥 — 거래소·상장·시장 인프라',                       'Nasdaq — exchange, listing & market infra'),
    ('ICE',  'infra',   'NYSE 모회사 · Securitize와 디지털 거래 MOU',             'NYSE parent · Securitize digital-trading MOU'),
    ('CME',  'infra',   'CME — 파생 거래소',                                     'CME — derivatives exchange'),
    ('CBOE', 'infra',   'Cboe — 거래소',                                         'Cboe — exchange'),
    ('TW',   'infra',   'Tradeweb — 채권 전자거래 인프라',                        'Tradeweb — electronic fixed-income infra'),
    ('V',    'pay',     'Visa — 스테이블코인 결제 파일럿',                        'Visa — stablecoin settlement pilots'),
    ('MA',   'pay',     'Mastercard — 스테이블코인·토큰화',                       'Mastercard — stablecoin & tokenization'),
    ('PYPL', 'pay',     'PayPal — PYUSD 스테이블코인',                           'PayPal — PYUSD stablecoin'),
    ('JPM',  'bank',    'JPMorgan — Kinexys 토큰화 예금',                        'JPMorgan — Kinexys tokenized deposits'),
    ('GS',   'bank',    'Goldman — 토큰화 플랫폼(GS DAP)',                       'Goldman — tokenization platform (GS DAP)'),
    ('MS',   'bank',    'Morgan Stanley — 기관 디지털자산',                       'Morgan Stanley — institutional digital assets'),
    ('STT',  'bank',    'State Street — 디지털 수탁',                            'State Street — digital custody'),
    ('SCHW', 'bank',    'Schwab — 크립토·토큰화 진출',                           'Schwab — crypto/tokenization entry'),
    ('IBKR', 'bank',    'Interactive Brokers — 토큰화 접근',                     'Interactive Brokers — tokenization access'),
    ('MSTR', 'treasury','BTC 트레저리 원조 — "토큰보다 더 오른 주식" 사례',         'Original BTC treasury — the "stock beat the token" case'),
]
def _rwa_one(item):
    sym, cat, ko, en = item
    o = {'sym': sym, 'cat': cat, 'note_ko': ko, 'note_en': en}
    prev = None
    try:
        d = json.loads(_get(f"https://api.nasdaq.com/api/quote/{sym}/info?assetclass=stocks", 8))
        dd = d.get('data') or {}; pd = dd.get('primaryData') or {}
        o['name'] = dd.get('companyName') or sym
        o['price'] = _money(pd.get('lastSalePrice'))
        pc = (pd.get('percentageChange') or '').replace('%', '').replace('+', '').replace(',', '').strip()
        try: o['chg'] = float(pc)
        except Exception: o['chg'] = None
        o['range52'] = ((dd.get('keyStats') or {}).get('fiftyTwoWeekHighLow') or {}).get('value')
        o['_net'] = _money((pd.get('netChange') or '').replace('+', ''))
    except Exception:
        pass
    try:
        s = json.loads(_get(f"https://api.nasdaq.com/api/quote/{sym}/summary?assetclass=stocks", 8))
        sd = (s.get('data') or {}).get('summaryData') or {}
        o['mcap'] = _money((sd.get('MarketCap') or {}).get('value'))
        o['sector'] = (sd.get('Sector') or {}).get('value')
        prev = _money((sd.get('PreviousClose') or {}).get('value'))
    except Exception:
        pass
    if o.get('chg') is None and o.get('_net') is not None and prev:   # fallback %chg from net/prevClose
        o['chg'] = round(o['_net'] / prev * 100, 2)
    o.pop('_net', None)
    return o

def build_rwastocks():
    with _cf.ThreadPoolExecutor(max_workers=8) as ex:
        rows = list(ex.map(_rwa_one, RWA_STOCKS))
    return [r for r in rows if r.get('price')]

def _rwa_loop():
    while True:
        got = False
        try:
            d = build_rwastocks()
            if d:
                with _lock:
                    _rwa['t'] = time.time(); _rwa['data'] = d
                got = True
                sys.stderr.write(f"rwastocks: {len(d)} priced\n")
        except Exception as e:
            sys.stderr.write(f"rwa loop: {e}\n")
        time.sleep(120 if got else 180)   # 2min when healthy (feels near-live); 3min retry on failure

# ---- RWA sector-expansion metrics: stablecoin supply (proxy for on-chain capital) + RWA TVL ----
_sector = {'t': 0, 'data': {}}
def _yahoo_hist(sym, rng='6mo'):
    try:
        d = json.loads(_get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d", 10))
        r = d['chart']['result'][0]
        ts = r['timestamp']; cl = r['indicators']['quote'][0]['close']
        return {time.strftime('%m/%d', time.gmtime(int(t))): c for t, c in zip(ts, cl) if c is not None}
    except Exception:
        return {}

def build_rwa_series():
    # Reconstruct a mcap-weighted RWA-equity index from real price history (no fragile storage;
    # survives restarts, backfilled). Rebased to 100 at window start. BTC-USD as comparison.
    with _lock:
        weights = {r['sym']: (r.get('mcap') or 0) for r in _rwa['data']}
    syms = list(weights) or [x[0] for x in RWA_STOCKS]
    hist = {}
    with _cf.ThreadPoolExecutor(max_workers=8) as ex:
        for sym, h in zip(syms, ex.map(_yahoo_hist, syms)):
            if len(h) >= 20:
                hist[sym] = h
    if not hist:
        return None
    btcd = _yahoo_hist('BTC-USD')
    dates = sorted({d for h in hist.values() for d in h},
                   key=lambda s: (int(s[:2]), int(s[3:])))[-90:]
    base = {}
    for sym, h in hist.items():
        for dt in dates:
            if dt in h:
                base[sym] = h[dt]; break
    idx = []
    for dt in dates:
        num = wsum = 0.0
        for sym, h in hist.items():
            if dt in h and base.get(sym):
                w = weights.get(sym, 0) or 1
                num += w * (h[dt] / base[sym]); wsum += w
        idx.append(round(num / wsum * 100, 2) if wsum else None)
    bbase = next((btcd[dt] for dt in dates if dt in btcd), None)
    btc = [round(btcd[dt] / bbase * 100, 2) if (dt in btcd and bbase) else None for dt in dates]
    return {'dates': dates, 'index': idx, 'btc': btc, 'members': len(hist)}

def build_sector():
    out = {}
    try:  # total stablecoin supply + 90-day series (DefiLlama, free)
        ch = json.loads(_get("https://stablecoins.llama.fi/stablecoincharts/all", 25))
        pts = [[int(r['date']), round((r.get('totalCirculatingUSD', {}) or {}).get('peggedUSD', 0) / 1e9, 1)]
               for r in ch if (r.get('totalCirculatingUSD') or {}).get('peggedUSD')]
        series = pts[-90:]
        total = series[-1][1] if series else None
        d30 = series[-31][1] if len(series) >= 31 else (series[0][1] if series else None)
        d7 = series[-8][1] if len(series) >= 8 else None
        out['stable'] = {'total': total, 'series': series,
                         'chg30': round((total - d30) / d30 * 100, 1) if (total and d30) else None,
                         'net7': round(total - d7, 1) if (total and d7) else None}   # weekly net mint/burn ($B)
    except Exception as e:
        sys.stderr.write(f"sector stable: {e}\n")
    try:  # on-chain RWA protocol TVL (DefiLlama category=RWA) + tvl-weighted 7d change + treasury subset
        prot = json.loads(_get("https://api.llama.fi/protocols", 30))
        rwa = [p for p in prot if p.get('category') == 'RWA']
        tot = sum(p.get('tvl', 0) or 0 for p in rwa)
        w = sum((p.get('tvl', 0) or 0) for p in rwa if p.get('change_7d') is not None)
        c7 = (sum((p.get('tvl', 0) or 0) * (p.get('change_7d') or 0) for p in rwa if p.get('change_7d') is not None) / w) if w else None
        top = sorted(rwa, key=lambda x: -(x.get('tvl', 0) or 0))[:6]
        TRE = ('treasur', 'buidl', 'usyc', 'ousg', 'benji', 'ustb', 'tbill', 'money market', 'fobxx')
        tre = sum((p.get('tvl', 0) or 0) for p in rwa if any(k in (p.get('name', '') or '').lower() for k in TRE))
        out['rwatvl'] = {'total': round(tot / 1e9, 2), 'count': len(rwa),
                         'chg7': round(c7, 1) if c7 is not None else None,
                         'treasury': round(tre / 1e9, 2),
                         'top': [{'name': p.get('name'), 'tvl': round((p.get('tvl', 0) or 0) / 1e9, 2)} for p in top]}
    except Exception as e:
        sys.stderr.write(f"sector rwatvl: {e}\n")
    try:  # mcap-weighted RWA-equity index time-series (Yahoo backfill) + BTC comparison
        ser = build_rwa_series()
        if ser:
            out['idxseries'] = ser
    except Exception as e:
        sys.stderr.write(f"sector series: {e}\n")
    out['generated'] = int(time.time())
    return out

def _sector_loop():
    while True:
        got = False
        try:
            d = build_sector()
            if d.get('stable') or d.get('rwatvl'):
                with _lock:
                    _sector['t'] = time.time(); _sector['data'] = d
                got = True
                sys.stderr.write("sector: refreshed\n")
        except Exception as e:
            sys.stderr.write(f"sector loop: {e}\n")
        time.sleep(1800 if got else 600)   # 30min (slow-moving); 10min retry on failure

# ---- CEX securities spread: Backpack (.US order book) vs Binance (tokenized-stock pairs), both LIVE ----
_cex = {'t': 0, 'data': {}}
_bn_stock_syms = None  # discovered once (ticker -> binance symbol)
# allowlist so we never pick up a crypto whose symbol ends in 'B' (e.g. SHIB)
EQUITY_TICKERS = {'SPCX','NVDA','TSLA','MSTR','CRCL','SNDK','AMD','INTC','EWY','MU','AAPL','META',
                  'GOOGL','AMZN','MSFT','COIN','HOOD','QQQ','SPY','PLTR','SMCI','NFLX','AVGO','SKHY'}

def _spread_bps(bid, ask):
    try:
        bid = float(bid); ask = float(ask)
        if bid > 0 and ask > 0 and ask >= bid:
            return round((ask - bid) / ((ask + bid) / 2) * 1e4, 1)
    except Exception:
        pass
    return None

def _discover_binance_stocks():
    try:
        d = json.loads(_get("https://api.binance.com/api/v3/exchangeInfo", 25))
        out = {}
        for s in d.get('symbols', []):
            if s.get('status') != 'TRADING' or s.get('quoteAsset') != 'USDT':
                continue
            b = s.get('baseAsset', '')
            if b.endswith('B') and b[:-1] in EQUITY_TICKERS:
                out[b[:-1]] = s['symbol']
        return out
    except Exception as e:
        sys.stderr.write(f"bn discover: {e}\n"); return {}

def _backpack_securities():
    # Backpack Exchange CEX order-book securities: symbols like 'SPCX.US_USDC'
    try:
        m = json.loads(_get("https://api.backpack.exchange/api/v1/markets", 20))
        return [x['symbol'] for x in m if '.US' in x.get('symbol', '') and x.get('quoteSymbol') == 'USDC']
    except Exception as e:
        sys.stderr.write(f"bp sec: {e}\n"); return []

def build_cex():
    global _bn_stock_syms
    rows = {}
    # --- Binance: tokenized-stock pairs, order-book spread + 24h quote volume ---
    if _bn_stock_syms is None:
        _bn_stock_syms = _discover_binance_stocks() or {}
    bn = _bn_stock_syms
    if bn:
        syms = json.dumps(list(bn.values()), separators=(',', ':'))
        books, t24 = {}, {}
        try:
            books = {x['symbol']: x for x in json.loads(_get(
                "https://api.binance.com/api/v3/ticker/bookTicker?symbols=" + urllib.parse.quote(syms), 20))}
            t24 = {x['symbol']: x for x in json.loads(_get(
                "https://api.binance.com/api/v3/ticker/24hr?symbols=" + urllib.parse.quote(syms), 25))}
        except Exception as e:
            sys.stderr.write(f"bn quote: {e}\n")
        for tk, sym in bn.items():
            r = rows.setdefault(tk, {'ticker': tk})
            bt = books.get(sym)
            if bt:
                r['bn_spread'] = _spread_bps(bt.get('bidPrice'), bt.get('askPrice'))
                r['bn_price'] = float(bt.get('askPrice') or 0) or None
            td = t24.get(sym)
            if td:
                r['bn_vol'] = float(td.get('quoteVolume') or 0)
    # --- Backpack: CEX .US order-book securities, real bid/ask (populated in US market hours) ---
    # /api/v1/tickers now includes .US markets (verified 07-24) → ONE batch call gives 24h volume
    # + change% for every listed security; per-symbol depth still needed for the live spread.
    bp_tk = {}
    try:
        for x in json.loads(_get("https://api.backpack.exchange/api/v1/tickers", 15)):
            if '.US' in x.get('symbol', ''):
                bp_tk[x['symbol']] = x
    except Exception as e:
        sys.stderr.write(f"bp tickers: {e}\n")
    for sym in _backpack_securities():
        tk = sym.split('.')[0]
        r = rows.setdefault(tk, {'ticker': tk}); r['bp_listed'] = True
        try:
            dep = json.loads(_get("https://api.backpack.exchange/api/v1/depth?symbol=" + urllib.parse.quote(sym), 12))
            bids = dep.get('bids') or []; asks = dep.get('asks') or []
            bb = float(bids[-1][0]) if bids else 0   # backpack depth: best bid = last of bids
            ba = float(asks[0][0]) if asks else 0    #                  best ask = first of asks
            r['bp_spread'] = _spread_bps(bb, ba)
            if bb and ba: r['bp_price'] = (bb + ba) / 2
        except Exception:
            pass
        t = bp_tk.get(sym)
        if t:
            if t.get('quoteVolume'): r['bp_vol'] = float(t['quoteVolume'])
            if t.get('lastPrice') and not r.get('bp_price'): r['bp_price'] = float(t['lastPrice'])
            if t.get('priceChangePercent') is not None:
                try: r['bp_chg'] = round(float(t['priceChangePercent']) * 100, 2)
                except Exception: pass
    return {'generated': int(time.time()),
            'rows': sorted(rows.values(), key=lambda r: -((r.get('bn_vol') or 0) + (r.get('bp_vol') or 0))),
            'bn_count': len(bn),
            'bp_count': sum(1 for r in rows.values() if r.get('bp_listed'))}

def _cex_loop():
    while True:
        try:
            d = build_cex()
            if d:
                with _lock:
                    _cex['t'] = time.time(); _cex['data'] = d
                sys.stderr.write(f"cex: {len(d.get('rows', []))} tickers (bn {d.get('bn_count')}, bp {d.get('bp_count')})\n")
        except Exception as e:
            sys.stderr.write(f"cex loop: {e}\n")
        time.sleep(60)

# ---- securities spread vs Nasdaq: Backpack universe (paginated) + Nasdaq benchmark + Binance/Backpack venues ----
SEC_PAGE = 30
_sec = {'sorted': [], 't': 0}     # full Backpack securities universe, comparable tickers first
_nq_cache = {}                    # ticker -> (ts, quote)

def _money(s):
    try:
        v = float(str(s).replace('$', '').replace(',', '').strip())
        return v or None
    except Exception:
        return None

def _load_universe():
    try:
        s = json.loads(_get("https://api.backpack.exchange/api/v1/securities", 25))
        out = []
        for x in s:
            tk = (x.get('asset') or '').split('.')[0]
            if tk:
                out.append({'ticker': tk, 'name': x.get('name', tk)})
        return out
    except Exception as e:
        sys.stderr.write(f"universe: {e}\n"); return []

def _cex_map():
    with _lock:
        rows = (_cex['data'] or {}).get('rows', [])
    return {r['ticker']: r for r in rows}

def _ensure_universe():
    if _sec['sorted'] and time.time() - _sec['t'] < 3600:
        return
    uni = _load_universe()
    cm = _cex_map()
    covered = set(cm.keys())   # tickers Binance/Backpack list -> show first (the comparable ones)
    uni.sort(key=lambda r: (0 if r['ticker'] in covered else 1, r['ticker']))
    if uni:
        _sec['sorted'] = uni; _sec['t'] = time.time()

def _nasdaq_quote(tk):
    now = time.time()
    c = _nq_cache.get(tk)
    if c and now - c[0] < 60:
        return c[1]
    out = None
    for ac in ('stocks', 'etf'):
        try:
            d = json.loads(_get(f"https://api.nasdaq.com/api/quote/{urllib.parse.quote(tk)}/info?assetclass={ac}", 8))
            pd = (d.get('data') or {}).get('primaryData') or {}
            bid = _money(pd.get('bidPrice')); ask = _money(pd.get('askPrice')); last = _money(pd.get('lastSalePrice'))
            if last or (bid and ask):
                out = {'bid': bid, 'ask': ask, 'last': last,
                       'spread': _spread_bps(bid, ask) if (bid and ask) else None}
                break
        except Exception:
            continue
    _nq_cache[tk] = (now, out)
    return out

def build_spreads(page):
    _ensure_universe()
    uni = _sec['sorted']
    total = len(uni)
    pages = max(1, (total + SEC_PAGE - 1) // SEC_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = uni[page * SEC_PAGE:(page + 1) * SEC_PAGE]
    cm = _cex_map()
    # fetch Nasdaq quotes for the 30 visible tickers concurrently (cached 60s)
    nq = {}
    if chunk:
        with _cf.ThreadPoolExecutor(max_workers=8) as ex:
            for tk, q in zip([r['ticker'] for r in chunk],
                             ex.map(lambda r: _nasdaq_quote(r['ticker']), chunk)):
                nq[tk] = q
    rows = []
    for r in chunk:
        tk = r['ticker']; c = cm.get(tk, {}); n = nq.get(tk)
        rows.append({
            'ticker': tk, 'name': r['name'],
            'nasdaq': ({'px': n.get('last') or (((n.get('bid') or 0) + (n.get('ask') or 0)) / 2 or None),
                        'spread': n.get('spread')} if n else None),
            'binance': ({'spread': c.get('bn_spread'), 'px': c.get('bn_price'), 'vol': c.get('bn_vol')}
                        if (c.get('bn_spread') is not None or c.get('bn_vol')) else None),
            'backpack': ({'spread': c.get('bp_spread'), 'px': c.get('bp_price'), 'vol': c.get('bp_vol'),
                          'chg': c.get('bp_chg'), 'ob': True} if c.get('bp_listed') else {'ob': False}),
        })
    return {'generated': int(time.time()), 'page': page, 'pages': pages, 'total': total,
            'page_size': SEC_PAGE, 'rows': rows}

# ---- logo proxy + cache: ?t=ticker (stock) / ?d=domain (issuer) / ?c=chain ----
_logo_cache = {}
def _fetch_url(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = urllib.request.urlopen(req, timeout=8).read()
        if data and len(data) > 120:
            ct = 'image/jpeg' if url.lower().split('?')[0].endswith('.jpg') else 'image/png'
            return data, ct
    except Exception:
        pass
    return None, None
# ticker -> official domain, for a high-quality Clearbit logo fallback on newer/obscure names
LOGO_DOMAIN = {
    'SECZ': 'securitize.io', 'FIGR': 'figure.com', 'GLXY': 'galaxy.com', 'HLNE': 'hamiltonlane.com',
    'WT': 'wisdomtree.com', 'TW': 'tradeweb.com', 'CBOE': 'cboe.com', 'IBKR': 'interactivebrokers.com',
    'APO': 'apollo.com', 'IVZ': 'invesco.com', 'BEN': 'franklintempleton.com', 'STT': 'statestreet.com',
    'KKR': 'kkr.com', 'NDAQ': 'nasdaq.com', 'ICE': 'ice.com', 'SOFI': 'sofi.com', 'GLXY ': 'galaxy.com',
    'CRCL': 'circle.com', 'COIN': 'coinbase.com', 'HOOD': 'robinhood.com', 'MSTR': 'strategy.com',
    'SCHW': 'schwab.com', 'PYPL': 'paypal.com', 'CME': 'cmegroup.com',
}
def _logo_urls(typ, val):
    if typ == 't':
        v = val.upper()
        urls = [f"https://financialmodelingprep.com/image-stock/{v}.png",
                f"https://assets.parqet.com/logos/symbol/{v}?format=png"]
        dom = LOGO_DOMAIN.get(v)
        if dom:                                    # try the company's real logo before the xStocks guess
            urls.append(f"https://logo.clearbit.com/{dom}")
            urls.append(f"https://www.google.com/s2/favicons?domain={dom}&sz=128")
        urls.append(f"https://xstocks-metadata.backed.fi/logos/tokens/{v}x.png")
        return urls
    if typ == 'd':
        return [f"https://www.google.com/s2/favicons?domain={val.lower()}&sz=128"]
    if typ == 'c':
        v = val.lower()
        return [f"https://icons.llamao.fi/icons/chains/rsz_{v}.jpg",
                f"https://icons.llamao.fi/icons/chains/rsz_{v}.png"]
    return []

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if isinstance(body, str): body = body.encode('utf-8')
        self.wfile.write(body)
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/api/news':
            try:
                q = urllib.parse.parse_qs(self.path.split('?', 1)[1]) if '?' in self.path else {}
                page = int((q.get('page', ['1']))[0] or 1)
                size = int((q.get('size', ['50']))[0] or 50)
                query = (q.get('q', ['']))[0]
                self._send(200, json.dumps(get_news(page, size, query)), 'application/json')
            except Exception as e:
                self._send(500, json.dumps({'error': str(e)}), 'application/json')
            return
        if path == '/api/live':
            with _lock:
                self._send(200, json.dumps({'generated': int(_live['t']), 'tokens': _live['data']}), 'application/json')
            return
        if path == '/api/cex':
            with _lock:
                self._send(200, json.dumps(_cex['data'] or {'rows': [], 'generated': 0}), 'application/json')
            return
        if path == '/api/spreads':
            try:
                q = urllib.parse.parse_qs(self.path.split('?', 1)[1]) if '?' in self.path else {}
                page = int((q.get('page', ['0']))[0])
                self._send(200, json.dumps(build_spreads(page)), 'application/json')
            except Exception as e:
                self._send(500, json.dumps({'error': str(e), 'rows': []}), 'application/json')
            return
        if path == '/api/earnings':
            with _lock:
                self._send(200, json.dumps({'generated': int(_earn['t']), 'items': _earn['data']}), 'application/json')
            return
        if path == '/api/rwastocks':
            with _lock:
                self._send(200, json.dumps({'generated': int(_rwa['t']), 'items': _rwa['data']}), 'application/json')
            return
        if path == '/api/sector':
            with _lock:
                self._send(200, json.dumps(_sector['data'] or {}), 'application/json')
            return
        if path == '/api/geo':
            # Country from the CDN edge (Cloudflare sets CF-IPCountry; others vary). Used only to
            # auto-pick UI language (KR->ko, CN->zh, else en). No IP stored.
            cc = (self.headers.get('CF-IPCountry')
                  or self.headers.get('X-Vercel-IP-Country')
                  or self.headers.get('X-Country-Code') or '').upper()
            if cc in ('XX', 'T1'):
                cc = ''
            self._send(200, json.dumps({'country': cc}), 'application/json')
            return
        if path == '/api/logo':
            q = urllib.parse.parse_qs(self.path.split('?', 1)[1]) if '?' in self.path else {}
            typ = 't' if 't' in q else 'd' if 'd' in q else 'c' if 'c' in q else None
            val = re.sub(r'[^A-Za-z0-9.\-]', '', (q.get(typ, ['']))[0]) if typ else ''
            key = f"{typ}:{val.lower()}" if typ else ''
            if val and key not in _logo_cache:
                _logo_cache[key] = (None, None)
                for u in _logo_urls(typ, val):
                    d, ct = _fetch_url(u)
                    if d:
                        _logo_cache[key] = (d, ct); break
            data, ct = _logo_cache.get(key, (None, None))
            if data:
                self.send_response(200); self.send_header('Content-Type', ct)
                self.send_header('Cache-Control', 'max-age=86400'); self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers(); self.wfile.write(data)
            else:
                self.send_response(404); self.end_headers()
            return
        # static
        rel = path.lstrip('/') or 'index.html'
        fp = os.path.normpath(os.path.join(BASE, rel))
        if not fp.startswith(BASE) or not os.path.isfile(fp):
            self._send(404, 'not found', 'text/plain'); return
        ctype = {'html':'text/html','js':'application/javascript','json':'application/json',
                 'css':'text/css','png':'image/png','svg':'image/svg+xml'}.get(fp.rsplit('.',1)[-1], 'application/octet-stream')
        with open(fp, 'rb') as f:
            self._send(200, f.read(), ctype + ('; charset=utf-8' if ctype.startswith('text') or 'json' in ctype or 'javascript' in ctype else ''))

if __name__ == '__main__':
    print(f"OnchainEquities backend on http://localhost:{PORT}  (/api/news + /api/live)")
    _load_store()   # restore the rolling news archive so history survives restarts within a run
    threading.Thread(target=_news_loop, daemon=True).start()
    threading.Thread(target=_live_loop, daemon=True).start()
    threading.Thread(target=_cex_loop, daemon=True).start()
    threading.Thread(target=_earn_loop, daemon=True).start()
    threading.Thread(target=_rwa_loop, daemon=True).start()
    threading.Thread(target=_sector_loop, daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0', PORT), H).serve_forever()
