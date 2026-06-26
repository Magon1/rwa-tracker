# 배포 가이드 / Deploy

이 앱은 **Python 표준 라이브러리만** 사용하는 단일 서버(`server.py`)입니다. 외부 패키지 설치가 필요 없습니다.
서버는 `$PORT` 환경변수(없으면 8765)에서 `0.0.0.0`에 바인딩됩니다.

## 옵션 A — 즉시 공개 URL (계정 불필요, 임시)
이 PC에서 서버가 켜져 있는 동안만 유효한 공개 HTTPS 주소를 만듭니다.

```bash
# cloudflared 다운로드 후
cloudflared tunnel --url http://localhost:8765
```
→ `https://<무작위>.trycloudflare.com` 주소가 출력됩니다. 누구나 접속 가능.
단점: PC가 꺼지거나 터널을 닫으면 중단되고, 주소가 매번 바뀝니다. (데모/공유용)

## 옵션 B — 영구 무료 배포 (권장, 계정 1회 필요)
컨테이너(Dockerfile)로 어디든 올라갑니다. 가장 간단한 곳은 **Render** 무료 플랜.

1. 이 폴더를 GitHub 저장소로 푸시 (이미 `git init` + commit 완료):
   ```bash
   git remote add origin https://github.com/<you>/onchain-equities.git
   git push -u origin main
   ```
2. https://render.com → New → **Web Service** → 위 저장소 선택
3. Render가 `render.yaml`(Docker) 자동 인식 → **Create**. 2~3분 후
   `https://onchain-equities.onrender.com` 같은 영구 주소 발급.

Railway / Fly.io / Koyeb 도 동일한 Dockerfile로 바로 배포됩니다.

## 참고
- 무료 플랜은 유휴 시 슬립 → 첫 접속이 느릴 수 있음(콜드스타트).
- 뉴스 한국어/중국어 번역, 라이브 거래량, 로고 프록시는 모두 서버가 외부 API를
  호출하므로 **정적 호스팅(Netlify/Vercel static/GitHub Pages)에는 올릴 수 없습니다.**
  반드시 Python을 실행하는 호스트가 필요합니다.
