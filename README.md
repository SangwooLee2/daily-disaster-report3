# 전국 재난·통신·교통 일일 현황 보고

매일 07:00 KST에 Google 뉴스 RSS로 전국의 재난·재해, 유무선 통신망 두절, 교통 두절 관련 기사를 모으고, Gemini API를 1회 호출해 사건으로 묶고 분류한 뒤 웹페이지로 발행합니다. 요구사항은 [PRD.md](PRD.md)를 참고하세요.

## 구조

```
main.py                 실행 진입점 (collect / build / sample)
report/collect.py       Google 뉴스 RSS 수집, Gemini 1회 호출, 근거 기사 연결
report/normalize.py     검증, 출처 없는 항목 제외, 기간 필터, 중복 제거, 심각도 보정
report/build.py         data/*.json → site/ 정적 페이지
templates/              페이지 템플릿
samples/sample.json     화면 확인용 샘플 (가상 사례)
data/YYYY-MM-DD.json    날짜별 보고 원본 (자동 커밋)
.github/workflows/      매일 07:00 KST 자동 실행 + GitHub Pages 배포
```

## 로컬 실행

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python main.py sample            # 샘플로 화면 확인 → site/index.html
# .env의 GEMINI_API_KEY= 뒤에 Google AI Studio 키를 넣는다 (.env는 git에 올라가지 않음)
# .env는 이 폴더를 먼저 찾고, 없는 값은 상위 폴더의 .env에서 읽는다
.venv/bin/python main.py collect           # 실제 수집 → data/오늘.json
.venv/bin/python main.py build             # data/ 전체로 site/ 생성
```

## 배포 (GitHub)

1. GitHub에 저장소를 만들고 이 폴더를 push합니다.
2. **Settings → Secrets and variables → Actions**
   - Secret `GEMINI_API_KEY`: Google AI Studio 키
   - (선택) Variable `GEMINI_MODEL`: 사용할 모델 이름. 비우면 `gemini-3.8-flash`
3. **Settings → Pages → Source**를 `GitHub Actions`로 바꿉니다.
4. **Actions → daily-report → Run workflow**로 한 번 수동 실행해서 확인합니다.
5. 이후에는 매일 07:00 KST에 자동으로 실행됩니다. GitHub cron은 수 분 늦을 수 있습니다.

## 게시 규칙

- 출처는 RSS에 실제로 있는 기사에서만 가져오고, 근거 기사가 없는 항목은 게시하지 않습니다 (환각 방지).
- 집계 기간(전날 07:00 ~ 당일 07:00) 이전에 끝난 항목은 제외합니다.
- 심각도는 Gemini 판단에 키워드 규칙을 더해 **올리기만** 합니다 (예: "경보", "사망", "전면 통제" → 긴급).
- Gemini가 혼잡(503)하거나 한도(429)에 걸리면 예비 모델(`gemini-3.5-flash` → `gemini-3.1-flash-lite`)로 넘어가며 최대 4바퀴, 8분까지 재시도합니다. 예비 모델은 `GEMINI_FALLBACK_MODELS`로 바꿀 수 있습니다.
- 수집에 실패해도 페이지는 발행하고 "수집 실패"를 표시합니다.
