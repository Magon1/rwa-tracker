# OnchainEquities — 토크나이즈드 스톡 & RWA 라이브 트래커

Backpack · xStocks · Ondo가 발행한 온체인 주식 토큰의 **24h 볼륨 · 유동성 · 유효 스프레드**를
티커별로 추종하고, **발행사 점유율(볼륨/유동성/종목 수)**을 그래프로 보여주는 대시보드.

현재 버전은 **단일 파일(`index.html`)** 로, Node 없이 브라우저에서 바로 열립니다.

---

## 0. 거래량 1위 = Backpack (tokens.xyz/Sunrise 실측, 2026-06-26)

권위 소스를 **tokens.xyz / Sunrise**(Backpack 발행 인프라, 모든 Solana DEX 풀 집계)로 교체해 재측정한 결과:

| 토큰 | 24h 볼륨 | 유동성 | 발행사 |
|---|---|---|---|
| **SPCX** (SpaceX) | **$57.75M** | $7.54M | Backpack |
| **MU** (Micron) | **$37.08M** | $4.81M | Backpack |
| **SNDK** (SanDisk) | **$17.27M** | $1.12M | Backpack |
| SPYx (S&P500) | $10.47M | $5.33M | xStocks |
| CRCLx (Circle) | $3.90M | $3.94M | xStocks |

- **Backpack 3종목 합 ~$112M/24h** ≫ xStocks 166종목 Solana DEX 합산 ~$29M ≫ **Ondo ≈ $0**.
- **Solana 온체인 DEX 거래량 = Backpack 압도적 1위 (79%)**. 이전 CoinGecko 수치($13M)는 일부 베뉴만 집계해 크게 과소했습니다.

### xStocks·Ondo도 권위 소스로 재검증 (GeckoTerminal, 무키·전 체인)
- **Ondo는 DEX 2차거래가 사실상 0** — GeckoTerminal로 EVM 확인: CRCLon 24h **$81**, TSLAon **$1,312**, MSFTon **$0** (시총 $130M인데도). Ondo는 mint/redeem·기관 모델이라 DEX에서 거의 안 돌아감. → 대시보드 Ondo 볼륨을 ~0으로 정정.
- **xStocks**는 tokens.xyz(전 Solana 풀 집계)가 가장 정확하므로 유지. CEX(Kraken/Bybit) 볼륨은 별도(온체인 아님).
- 교차검증 결론: tokens.xyz는 Solana 전 풀을 잡아 GeckoTerminal보다 완전(예: SPCX tokens.xyz $57.75M vs GeckoTerminal $12.3M). **Solana=tokens.xyz, EVM=GeckoTerminal** 하이브리드가 최적.

### 추가: 한/영 언어 토글
마스트헤드 우상단 **KO/EN 토글** — UI·KPI·콜아웃·섹션·테이블·발행사 카드·뉴스 전부 전환 (localStorage 저장). 모든 텍스트는 `TR` 사전 + 데이터 구조의 `{ko,en}`으로 관리.

### tokens.xyz API (라이브 연동용)
- 공개 API: `https://api.tokens.xyz/v1` · 인증 `x-api-key` 헤더 **필수**(키 없으면 401).
- 핵심 엔드포인트: `GET /v1/assets/curated?list=stocks` (전 종목+볼륨), `GET /v1/assets/resolve?mint=<mint>` → assetId, `GET /v1/assets/:id?include=markets` (24h 볼륨/유동성), `GET /v1/assets/:id/markets?mint=` (풀별), `GET /v1/assets/:id/ohlcv` (히스토리). 문서: docs.tokens.xyz.
- **키 발급 전까지**: 현재 대시보드는 per-stock 페이지(RSC) 파싱으로 추출한 06-26 스냅샷을 임베드. 라이브화하려면 백엔드 프록시 + 키 필요(README 4장).

## 0-1. 구현된 기능

요청 사항 + rwa.xyz/CoinGecko/DefiLlama/Dune 리서치 기반 추가:
- **검색창** — 주식 검색 시 발행사별로 결과 표시 (예: `AAPL` → AAPLx/xStocks · AAPLon/Ondo)
- **현재 가장 활발한 토큰 TOP 10** — 점유율 섹션 앞에 상시 노출 (종목·발행사·등락·볼륨)
- **발행사 점유율** — 볼륨 → 종목 수 → 시가총액 순 토글 (기본 볼륨)
- **체인별 분포** — 시가총액 vs 거래량 분리 (가치는 ETH/BNB, 거래는 Solana 95.6%)
- **발행사간 같은 종목 가격차** *(신규)* — 한 주식의 발행사별 토큰 가격 괴리 = 차익거래 신호
- **24h 등락** *(신규)* — DefiLlama percentage API 라이브
- **자산군 태그** *(신규)* — 주식 / ETF 구분
- **NYSE 개장 상태** *(신규)* — 실시간 시장시간 배지
- **준비금(PoR)·백킹 배지** *(신규)* — 발행사별 Chainlink PoR / 커스터디 구조
- **최근 상장 피드** *(신규)* — SNDK·MU·SPCX·Ondo 대량상장 타임라인

디자인: 다크 대시보드 → **에디토리얼 라이트**(Fraunces 세리프 + Inter + IBM Plex Mono, 신문/터미널 하이브리드)로 전면 개편.

## 0-2. v2: Python 백엔드 + 3탭 + 라이브 연동

이제 **Python 백엔드**(`server.py`)가 정적 서빙 + 뉴스 집계를 합니다. 실행:
```bash
cd rwa-tracker && python server.py 8765   # → http://localhost:8765
```

**3개 탭**: `Main` / `RWA 뉴스·리서치` / `발행사별 구조`
- **Main**: KPI · 가장 활발 · 발행사 점유율 · 체인별 · **발행사 토큰 시총** · **CEX 비교** · 교차발행사 · 전체 토큰
- **발행사별 구조**: 발행사 CTA 버튼 + 구조 카드 (클릭 → 전체 발행 자산 모달)
- **RWA 뉴스·리서치**: 실시간 뉴스 + 추천 발행사

**라이브 데이터 소스** (CORS 처리):
| 데이터 | 소스 | 방식 |
|---|---|---|
| RWA 뉴스 (45개, 중요도 랭킹) | CoinDesk·Cointelegraph(RWA)·The Block·Blockworks·Decrypt·CryptoBriefing·Tokeny·Dune RSS | **server.py `/api/news`** (RSS 집계·중요도 점수·군집 dedup·5분 캐시) |
| 발행사 토큰 시총 $ONDO·$BP | CoinGecko `simple/price` | 클라이언트 직접 (CORS 개방) |
| Binance Bstock 거래량 (9종목) | Binance `ticker/24hr` | 클라이언트 직접 (CORS 개방) |
| **토큰 24h 볼륨/유동성 (라이브)** | GeckoTerminal(Solana) + tokens.xyz(Backpack 3) | **server.py `/api/live`** — 백그라운드 스레드가 ~3분마다 갱신, 프론트가 30초마다 받아 테이블 업데이트. 마스트헤드에 "볼륨 갱신 Xs 전" 표시. 첫 데이터는 서버 기동 ~1분 후. `assets.json`은 초기 스냅샷(폴백) |
| 가격·등락 | DefiLlama | 클라이언트 직접 |

**$XSTOCKS는 토큰이 없습니다** (Backed Finance 무토큰) — "발행사 토큰 없음" 표기.

**CEX 비교 결과**: Binance Bstock 합계 ~$40.8M (SPCXB $28M·SNDKB $6.6M 등 9종목) < **Backpack 온체인 securities ~$112M** (SPCX/MU/SNDK). 같은 종목도 Backpack 온체인이 우세 (SPCX $57.75M vs $28M).

**추천 추가 발행사**: **Dinari(dShares, Base/Arbitrum, ".d" 접미사)** · **Coinbase(Base, 출시 임박)** · Robinhood(Arbitrum, 제한적) · Binance Bstock(추적 중). Base 진출 시 Dinari·Coinbase가 핵심.

## 0-3. 디자인 테마 (우상단 드롭다운에서 선택)

유명 데이터 사이트 디자인을 참고해 **5개 테마**를 만들었습니다. 마스트헤드 우상단 `◆` 드롭다운에서 전환(localStorage 저장):

| 테마 | 참고 | 분위기 |
|---|---|---|
| **Editorial** (기본) | 신문/매거진 | 따뜻한 페이퍼 + Fraunces 세리프 |
| **Terminal** | Bloomberg | 순흑 배경 + 앰버 + JetBrains Mono, 고밀도 |
| **Nebula** | Dune · Nansen | 청흑 다크 + 바이올렛 + Space Grotesk |
| **Institutional** | DefiLlama · Stripe · Token Terminal | 화이트 + 네이비 + Manrope, 기관용 |
| **Vault** | (오리지널) | 따뜻한 골드 다크 + 세리프, "프라이빗 뱅크" |

테마는 CSS 변수 + `body` 클래스로 구현했고, **pill/badge는 `color-mix`**, **차트는 CSS 변수를 읽어** 자동 적응합니다. 마음에 드는 걸 고르시면 그걸 기본값으로 고정하고 디테일을 다듬겠습니다.

## 0-4. 추가 기능 제안 (검토용)

다음에 붙일 만한 것들을 가치·난이도순으로 정리했습니다 — 원하는 것 골라주세요:

1. **NAV 프리미엄/디스카운트** ⭐ — 토큰 가격 vs 실주식 가격 괴리(%). 차익거래 핵심 지표, 경쟁 사이트도 잘 안 보여줌. (실주식 시세 피드 필요: Finnhub/Polygon 무료티어)
2. **Dinari(Base) 실데이터 추가** ⭐ — Base 진출 대비. dShares를 GeckoTerminal(base)로 라이브 연동.
3. **히스토리컬 추세** ⭐ — server.py가 매일 assets.json 스냅샷 저장 → 발행액/볼륨/점유율 시계열 차트 + 일별 변화.
4. **알림** — 볼륨 급증·스프레드 급등·신규 상장 시 브라우저/텔레그램 알림.
5. **워치리스트** — 관심 종목 즐겨찾기(localStorage) + 상단 고정.
6. **차익거래 스캐너** — 발행사간·CEX간 가격차를 실시간 정렬해 기회 표시(현 cross-issuer 확장).
7. **홀더 수 & 증가율** — 토큰별 홀더 수(Solana RPC/Dune) — 실수요 신호.
8. **mint/redeem 플로우** — Ondo 등 발행·소각 이벤트 추적(발행액이 왜 크고 거래는 작은지 시각화).
9. **CSV/JSON 내보내기 + 임베드 위젯** — 데이터 다운로드 및 외부 임베드.
10. **자동 갱신 cron** — assets.json을 매일 자동 재수집(현재 06-26 스냅샷 → 라이브 유지).

## 0-5. 개선점 리포트 (내가 파악한 것)

**제품/UX**
1. **신뢰 라벨 일관성** — 볼륨 측정 기준이 발행사별로 다름(Backpack·xStocks=DEX 스왑, Ondo=온체인 전송). 각 수치에 출처 툴팁/배지를 더 명확히.
2. **데이터 신선도 차이** — 가격·Binance·뉴스는 라이브, 토큰 볼륨은 ~3분 갱신, Ondo 전송량·발행액은 스냅샷. "마지막 갱신" 표시를 섹션별로.
3. **모바일 반응형** — 테이블 가로스크롤·hero 2단→1단은 되지만, 모바일 전용 카드뷰가 필요.
4. **에러/로딩 상태** — API 실패 시 조용히 폴백. "데이터 지연" 토스트/스켈레톤 추가.
5. **접근성** — 색상 대비(특히 다크 테마 mut 텍스트), 키보드 내비, aria 라벨.

**데이터/신뢰**
6. **Ondo 전송량 ETH만 측정** — BNB·Solana 전송량 미포함(전체는 더 큼). 멀티체인 합산 필요.
7. **per-token 발행액은 GeckoTerminal 추정** — RWA.xyz 집계와 불일치. RWA.xyz Enterprise나 issuer API로 교정.
8. **자동 갱신 cron** — assets.json·Ondo 스냅샷을 매일 자동 재수집(현재 수동).

**성능**
9. 단일 index.html이 커짐(~70KB+). 빌드 분리·코드 스플리팅 고려.
10. 차트 재생성(테마 전환 시) 최적화.

## 0-6. 글로벌 유입(트래픽) 전략

**즉시 적용됨**
- ✅ **SEO 메타** (description·keywords·robots), **OG/Twitter 카드**(og.svg), 다국어 locale 태그 → 검색·소셜 공유 노출
- ✅ **공유 버튼** (navigator.share / 링크 복사)
- ✅ **한/영 + 한국어 뉴스 자동번역** → 글로벌·한국 동시 공략

**다음 단계 (권장 로드맵)**
1. **콘텐츠 SEO** — 발행사·종목별 정적 페이지(`/backpack`, `/spcx`) 생성 → "tokenized SpaceX" 등 롱테일 검색 유입. server.py가 SSR로 메타 주입.
2. **다국어 확장** — 뉴스 번역을 中文·日本語·Español로 확대(translate API에 tl만 추가), UI도 단계적. RWA는 아시아·LATAM 수요 큼.
3. **공유형 콘텐츠** — "오늘의 토큰화 주식 리포트" 자동 생성 이미지(OG) + X(트위터) 자동 포스팅 봇(매일 거래량 1위·무버스).
4. **임베드 위젯** — `<iframe>` 임베드용 미니 위젯(점유율·무버스) → 다른 사이트/블로그에 퍼져 백링크·유입.
5. **데이터 API 공개** — `/api/live`·`/api/news`를 공개 API로 → 개발자 생태계·디스코드 봇 유입.
6. **알림/구독** — 이메일/텔레그램 "신규 상장·볼륨 급등" 알림 → 재방문·리텐션.
7. **커뮤니티 진입점** — 발행사(Backpack/Ondo) 공식 리트윗 유도, RWA 디스코드/서브레딧 공유, Product Hunt 런칭.
8. **퍼포먼스/PWA** — Lighthouse 최적화 + PWA(홈 화면 추가) → 모바일 리텐션.

## 1. 바로 실행하기

```bash
# 방법 A: 그냥 파일 열기 (가장 간단, CDN/일부 API만 동작)
#   index.html 더블클릭

# 방법 B: 로컬 정적 서버 (권장 — fetch/CORS가 더 잘 동작)
cd rwa-tracker
python -m http.server 8765
#   → http://localhost:8765
```

- 우상단 **🔑 Birdeye 키** 버튼에 무료 키를 넣으면 mint별 24h 볼륨·유동성이 라이브로 갱신됩니다.
- 30초마다 자동 새로고침. **↻ 새로고침**으로 수동 갱신.

---

## 2. 데이터 소스 (검증 완료)

| 데이터 | 소스 | 키 | CORS(브라우저 직접) | 상태 |
|---|---|---|---|---|
| xStocks 티커·Solana mint | `api.backed.fi/api/v2/public/assets` | ❌ | 보통 가능 | ✅ 권위 소스 |
| 토큰 가격 (mint별) | `coins.llama.fi/prices/current/solana:<mint>` | ❌ | ✅ 가능 | ✅ **현재 라이브 동작** |
| 24h 볼륨 · 유동성 (mint별) | Birdeye `public-api.birdeye.so/defi/token_overview` | ✅ 무료 1rps | 제한적 | 🔑 키 입력 시 |
| "most active" 랭킹 | Birdeye `/defi/tokenlist?sort_by=v24hUSD` | ✅ | 제한적 | 🔑 |
| 발행사별 집계(xStocks) | Dune query `5374994` `/api/v1/query/5374994/results` | ✅ 무료크레딧 | ❌ 백엔드 | 미연동 |
| 발행사 AUM/점유율 권위 | RWA.xyz `api.rwa.xyz/v4/assets` | 💰 Enterprise | ❌ | 미연동 |
| 뉴스/규제 RSS | Google News RSS 등 | ❌ | ❌ 백엔드 필요 | 큐레이션 |

### 현실적 한계 (정직하게)
1. **Backpack은 토크나이즈드 주식 오더북 공개 API가 없습니다.** `api.backpack.exchange`는 크립토 전용,
   Backpack Securities는 별도 지역제한 브로커리지(미·영·UAE·일·EU 미제공). → 본 사이트는 Backpack의
   **온체인 SPL securities 토큰**을 다른 발행사처럼 추종하고, "스프레드"는 **DEX 유동성 기반 유효 스프레드(bps)**로 표기.
   진짜 best bid/ask 스프레드가 필요하면 Backpack securities 프론트엔드를 스크래핑하거나 파트너 API가 있어야 함.
2. **Birdeye 무료 티어는 1 req/sec.** 종목이 많으면 순차 호출 + 캐시 필수 (코드에 1.1s 딜레이 내장).
3. **뉴스 RSS·Dune·RWA.xyz는 CORS 때문에 브라우저에서 직접 못 부릅니다.** → 아래 백엔드 프록시 필요.

---

## 3. 검증된 갯수 (2026-06-25/26 기준)

| 발행사 | 토큰 갯수 | 체인 | 시가총액(RWA.xyz) | 비고 |
|---|---|---|---|---|
| **Ondo** | **439 티커** (ETH 439 + BNB 439 = 878 EVM, + Solana 200+) | 멀티체인 | $899.4M (57.25%) | 시총 1위 |
| **xStocks** | **166** (전 종목 Solana + ETH/BNB/Optimism/Ink/XLayer/Ton 등) | 멀티체인 | $507.7M (32.32%) | 볼륨 1위 (SPYx 월 $3.49B) |
| **Backpack** | **3** (SPCX·MU·SNDK) | Solana만 | ~$17.6M | 토큰당 회전율 최고 |

**섹터 전체:** $1.52B 시총 · 2,480 종목 · 월 거래량 $8.02B (RWA.xyz 2026-06-25).
**체인별 시총:** Ethereum ~$614M · Solana ~$443M · BNB ~$432M.
**체인별 거래량:** Solana ~95.6% (거래는 Solana, 가치는 ETH/BNB에 분리).

검증된 갯수·mint 소스:
- xStocks: `api.backed.fi/api/v2/public/assets` 페이지네이션 → 166개, 전부 Solana 배포 확인
- Ondo: `github.com/ondoprotocol/ondo-global-markets-token-list` → 439 티커 × (chainId 1+56)
- Backpack mints (Solscan/CoinGecko 검증):
  - `SPCX → SPCXxcqXj6e5dJDVNovHN8744zkbhM2bYudU45BimGb`
  - `MU → MUxEsUKSMACyw5fZf68wxf5FLnZVhtU9CwH8uNNGay1`
  - `SNDK → SNDKbwMUQvZhnLnxLduradgLHG5KrPuKwpnrkkGRhfH`

> ⚠️ 일부 토큰의 온체인 라이브 가격(MU $1,194, SNDK $2,220, SPYx $739 등)은 실주식 1주 가격과 다릅니다 —
> 토큰 단위가 1:1이 아니거나 DEX 유동성이 얇아 생기는 **실제 온체인 가격 아티팩트**입니다(조작 아님).
> 신규 토큰 추가 = `ASSETS`에 한 줄(주소·`ck` 체인키 포함) 추가하면 가격이 자동 라이브 연동됩니다.

---

## 4. 프로덕션 승격 경로 (백엔드 프록시)

브라우저에서 직접 못 부르는 소스(Birdeye 키 은닉, Dune, RWA.xyz, 뉴스 RSS)와 CORS를 해결하려면
얇은 백엔드가 필요합니다. Node 설치 후:

```
rwa-tracker-pro/
├─ app/
│  ├─ page.tsx                # 현 index.html을 컴포넌트로 이식
│  └─ api/
│     ├─ overview/route.ts    # 모든 소스 집계 (서버사이드, 키 은닉)
│     ├─ birdeye/route.ts     # mint별 volume/liquidity (캐시 5분)
│     ├─ dune/route.ts        # query 5374994 결과 프록시
│     └─ news/route.ts        # Google News RSS 파싱 → JSON
├─ lib/{issuers,birdeye,backed,defillama,aggregate}.ts
└─ .env.local                 # BIRDEYE_API_KEY, DUNE_API_KEY (서버 전용)
```

핵심 서버 로직(의사코드):
```ts
// /api/overview
const assets = await getBackedAssets();          // 무키
const enriched = await birdeyeBatch(assets.map(a=>a.mint)); // 키 은닉, 캐시
const byIssuer = groupBy(enriched, 'issuer');
return { kpis, share:{volume,liquidity,count}, leaderboard, table };
```

배포: 프론트는 Vercel, 라이브 갱신은 서버사이드 캐시(또는 Redis) + WebSocket/SSE.
키는 **절대 클라이언트 노출 금지** — 현재 단일파일 버전의 localStorage 키 입력은 데모용입니다.

---

## 5. 다음 작업 후보
- [ ] Backpack securities 온체인 mint 주소 확보 → `ASSETS`에 채워 라이브화
- [ ] 백엔드 프록시(`/api/birdeye`, `/api/news`) 추가로 키 은닉 + RSS 라이브
- [ ] 점유율 시계열을 시뮬레이션 대신 일별 스냅샷 DB로 교체 (TimescaleDB/Postgres)
- [ ] Dune query 연동으로 xStocks 발행사 집계 교차검증
- [ ] 알림(스프레드 급등/볼륨 스파이크) + 종목 상세 페이지

---
*정보 제공용이며 투자 자문이 아닙니다. 온체인 데이터는 지연·부정확할 수 있습니다.*
