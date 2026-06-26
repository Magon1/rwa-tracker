#!/usr/bin/env python3
"""OnchainEquities backend: serves static files + /api/news RWA news aggregator.
No external deps (urllib + xml.etree). Run: python server.py [port]"""
import sys, os, json, re, time, math, threading
import urllib.request, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.etree import ElementTree as ET
from email.utils import parsedate_to_datetime
import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('PORT') or (sys.argv[1] if len(sys.argv) > 1 else 8765))

# ---- RWA news feeds (verified working RSS/Atom) ----
FEEDS = [
    ("CoinDesk",      "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Cointelegraph RWA", "https://cointelegraph.com/rss/tag/rwa"),
    ("Cointelegraph Tokenization", "https://cointelegraph.com/rss/tag/tokenization"),
    ("The Defiant",   "https://thedefiant.io/api/feed"),
    ("The Block",     "https://www.theblock.co/rss.xml"),
    ("Blockworks",    "https://blockworks.com/feed"),
    ("Decrypt",       "https://decrypt.co/feed"),
    ("CryptoBriefing","https://cryptobriefing.com/feed/"),
    ("Bankless",      "https://www.bankless.com/rss/feed"),
    ("Tokeny",        "https://www.tokeny.com/feed/"),
    ("Dune",          "https://dune.com/blog/feed"),
]

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

def score(title, summary):
    text = (title + ' ' + summary).lower()
    s = 0.0
    for d in (HIGH, MID, VENUE, REG):
        for k, w in d.items():
            if k in text: s += w
    for term, m in MULT:
        if term in text: s *= m
    return s

_cache = {"t": 0, "data": []}
_lock = threading.Lock()

def fetch_feed(name, url, out):
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
                dt = parsedate_to_datetime(pub) if pub and ',' in pub else datetime.datetime.fromisoformat(pub.replace('Z', '+00:00'))
                ts = dt.timestamp()
            except Exception:
                ts = 0
            out.append({'title': title, 'link': link, 'source': name, 'summary': summary,
                        'ts': ts, 'raw_score': score(title, summary)})
    except Exception as e:
        sys.stderr.write(f"feed err {name}: {e}\n")

def build_news():
    items = []
    threads = []
    for name, url in FEEDS:
        t = threading.Thread(target=fetch_feed, args=(name, url, items)); t.start(); threads.append(t)
    for t in threads: t.join(timeout=10)
    now = time.time()
    # recency decay + corroboration clustering by shared significant words
    def keywords(title):
        return set(w for w in re.findall(r'[a-z]{4,}', title.lower()) if w not in
                   {'with','that','this','from','have','will','what','when','your','about','crypto'})
    clusters = []
    for it in items:
        kw = keywords(it['title'])
        placed = False
        for c in clusters:
            if len(kw & c['kw']) >= 3:
                c['items'].append(it); c['kw'] |= kw; placed = True; break
        if not placed:
            clusters.append({'kw': kw, 'items': [it]})
    ranked = []
    for c in clusters:
        best = max(c['items'], key=lambda x: x['raw_score'])
        age_h = (now - best['ts']) / 3600 if best['ts'] else 72
        decay = math.exp(-age_h / 24) if best['ts'] else 0.2
        final = (best['raw_score'] + 2 * (len(c['items']) - 1)) * decay
        best = dict(best)
        best['age_h'] = round(age_h, 1)
        best['cluster'] = len(c['items'])
        best['score'] = round(final, 1)
        # only keep RWA-relevant items
        if best['raw_score'] >= 6:
            ranked.append(best)
    ranked.sort(key=lambda x: -x['score'])
    for r in ranked:
        r.pop('ts', None); r.pop('raw_score', None)
    top = ranked[:45]
    for r in top:                       # pre-translate to Korean + Chinese (free, server-side)
        r['title_ko'] = _translate(r['title'], 'ko')
        r['summary_ko'] = _translate(r.get('summary', ''), 'ko')
        r['title_zh'] = _translate(r['title'], 'zh-CN')
        r['summary_zh'] = _translate(r.get('summary', ''), 'zh-CN')
    return top

def _translate(text, tl='ko'):
    text = (text or '').strip()
    if not text:
        return ''
    try:
        u = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl="
             + tl + "&dt=t&q=" + urllib.parse.quote(text[:1800]))
        d = json.loads(_get(u, 10))
        out = ''.join(seg[0] for seg in d[0] if seg and seg[0])
        return out or text
    except Exception:
        return text  # graceful fallback to English

def _translate_ko(text):
    return _translate(text, 'ko')

def get_news():
    with _lock:
        return _cache['data']

def _news_loop():
    while True:
        try:
            data = build_news()
            if data:
                with _lock:
                    _cache['t'] = time.time(); _cache['data'] = data
                sys.stderr.write(f"news: refreshed {len(data)} items (translated)\n")
        except Exception as e:
            sys.stderr.write(f"news loop: {e}\n")
        time.sleep(300)

# ---- live volume/liquidity refresher (GeckoTerminal Solana + tokens.xyz) ----
def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    return urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', 'ignore')

BP_MINTS = {'SPCX': 'SPCXxcqXj6e5dJDVNovHN8744zkbhM2bYudU45BimGb',
            'MU': 'MUxEsUKSMACyw5fZf68wxf5FLnZVhtU9CwH8uNNGay1',
            'SNDK': 'SNDKbwMUQvZhnLnxLduradgLHG5KrPuKwpnrkkGRhfH',
            'DRAM': 'DRAMjSWR7HRfJKjRkvQWYL2bcaejaVhuxEcjf4pAY4Cw'}  # Roundhill Memory ETF (new)
TXYZ = {'spacex': 'SPCX', 'micron': 'MU', 'sandisk': 'SNDK'}
OV_VOL = {'SPYx': (10.47e6, 5.33e6), 'CRCLx': (3.90e6, 3.94e6), 'NVDAx': (3.43e6, 3.61e6),
          'QQQx': (2.97e6, 3.21e6), 'SPCXx': (2.92e6, 1.28e6), 'TSLAx': (2.61e6, 3.63e6)}
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

_TXP = re.compile(r'"price":([0-9.eE+\-]+),"liquidity":([0-9.eE+\-]+),"volume1hUSD":([0-9.eE+\-]+),"volume24hUSD":([0-9.eE+\-]+)')
_TXM = re.compile(r'"(?:baseMint|tokenMint|mint|address)":"([1-9A-HJ-NP-Za-km-z]{32,44})"')
def _txyz(slug, mint):
    try:
        s = _get(f"https://www.tokens.xyz/{slug}?solana={mint}").replace('\\"', '"')
        mints = [(mm.start(), mm.group(1)) for mm in _TXM.finditer(s)]
        best = None
        for mm in _TXP.finditer(s):
            px, liq, v1, v24 = map(float, mm.groups())
            near = [x for (p, x) in mints if p < mm.start()]
            if near and near[-1] == mint and (best is None or v24 > best[0]):
                best = (v24, liq, px)
        return best
    except Exception:
        return None

def _build_live():
    global _addr_map
    if _addr_map is None:
        _addr_map = _build_addr_map()
    addrs = list(_addr_map.values())
    by_addr = _gt_multi(addrs)
    data = {}
    for sym, addr in _addr_map.items():
        g = by_addr.get(addr.lower())
        if g: data[sym] = {**g, 'chain': 'Solana'}
    for sym, (v, l) in OV_VOL.items():  # keep accurate tokens.xyz vol for top xStocks
        if sym in data: data[sym]['vol'] = v; data[sym]['liq'] = l
    for slug, sym in TXYZ.items():      # Backpack: accurate Solana DEX aggregate
        b = _txyz(slug, BP_MINTS[sym])
        if b: data.setdefault(sym, {}).update({'vol': b[0], 'liq': b[1], 'px': b[2], 'chain': 'Solana'})
    for sym in data:                    # tag issuer so the frontend can auto-add new tokens
        data[sym]['issuer'] = 'Backpack' if sym in _bp_syms else 'xStocks'
    return data

def _live_loop():
    while True:
        try:
            d = _build_live()
            if d:
                with _lock:
                    _live['t'] = time.time(); _live['data'] = d
                sys.stderr.write(f"live: refreshed {len(d)} tokens\n")
        except Exception as e:
            sys.stderr.write(f"live loop: {e}\n")
        time.sleep(180)

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
def _logo_urls(typ, val):
    if typ == 't':
        v = val.upper()
        return [f"https://financialmodelingprep.com/image-stock/{v}.png",
                f"https://assets.parqet.com/logos/symbol/{v}?format=png",
                f"https://xstocks-metadata.backed.fi/logos/tokens/{v}x.png"]
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
                self._send(200, json.dumps({'generated': int(time.time()), 'items': get_news()}), 'application/json')
            except Exception as e:
                self._send(500, json.dumps({'error': str(e)}), 'application/json')
            return
        if path == '/api/live':
            with _lock:
                self._send(200, json.dumps({'generated': int(_live['t']), 'tokens': _live['data']}), 'application/json')
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
    threading.Thread(target=_news_loop, daemon=True).start()
    threading.Thread(target=_live_loop, daemon=True).start()
    ThreadingHTTPServer(('0.0.0.0', PORT), H).serve_forever()
