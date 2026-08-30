# 소상공인 정책 레이더 (bizpolicy)

소상공인 정책 뉴스를 매일 자동 수집해 논조를 관측하고, 월간 브리프·기획 리포트를
생성하는 파이프라인. [youthpolicy](https://github.com/baebong3/youthpolicy)와 동일한 틀.

**공개 페이지**: https://baebong3.github.io/bizpolicy/

## 구성
| 파일 | 역할 |
|---|---|
| `collect_biz_news.py` | 네이버 뉴스 API 수집 → 게이트·주제(7종)·시도·부처 태깅·감성 → `biz_news.json` 누적 |
| `build_db.py` | `biz_news.json` → `news.db` (누적·멱등, 리포트 생성기 호환 스키마) |
| `monthly_brief.py` | 지수형 월간 브리프 (`python monthly_brief.py 2026-09 --db news.db --out reports`) |
| `feature_report.py` | 기획기사형 월간 리포트 (`editorial/<월>.json` 원고 필요) |
| `make_index.py` | 공개 페이지(index.html) 재생성 |
| `.github/workflows/daily.yml` | 매일 07:20 KST 수집→적재→(월초)브리프→인덱스→커밋 |

## 최초 설정 (5분)
1. 이 폴더를 GitHub 새 저장소 `bizpolicy`(Public)로 push
2. **Settings → Secrets and variables → Actions** 에 `NAVER_ID`, `NAVER_SECRET` 등록
   (youthpolicy에서 쓰는 네이버 검색 API 키 그대로 사용 가능)
3. **Settings → Pages** → Source: `Deploy from a branch`, Branch: `main` / `(root)` → Save
4. **Actions 탭 → bizpolicy-daily → Run workflow** 로 첫 수집 수동 실행
   → 몇 분 뒤 https://baebong3.github.io/bizpolicy/ 에서 확인

## 운영
- 수집·적재·인덱스는 전자동. 지수형 브리프는 매월 1일 전월호가 자동 생성됨
- 기획 리포트는 `editorial/_template.json`을 복사해 `editorial/2026-09.json` 작성 후
  `python feature_report.py 2026-09 --db news.db --out reports`
- **첫 달 유의**: 감성 사전은 소상공인 문맥으로 새로 맞춘 초기판이므로, 표본 100건쯤
  수기 대조 후 NSI를 대외 인용할 것. 관측 개시월은 DB에서 자동 인식됨
- 인용은 기사 **제목**에 한정(본문 요약은 수집·집계에만 사용) — 리포트 각주에 자동 명시
