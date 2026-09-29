# Stock Score Terminal — Public Edition

Python으로 가격 지표·공시·뉴스·리서치를 분석하고 정적 웹 대시보드로 탐색하는 프로젝트입니다.
모멘텀·추세·변동성·낙폭·유동성 지표, 테마별 종목 비교, 문서 요약과 로컬 질의 기능을 포함합니다.

공개 화면의 6개 종목과 모든 수치·리서치 문장은 **합성 데이터**입니다.
실제 시세, 보고서 발췌, 텔레그램 원문, API 자격정보, 과거 비공개 이력은 포함하지 않습니다.

## 키 없이 데모 실행

```sh
python -m http.server 8002 --bind 127.0.0.1 --directory site
```

`http://127.0.0.1:8002`를 엽니다. Python 표준 라이브러리만 필요합니다.
`site/demo-data/`의 예제를 사용하고, 질문은 브라우저 안에서 답변합니다.
Netlify 예제 함수도 합성 데이터만 사용하며 환경변수에 키가 있어도 유료 AI API를 호출하지 않습니다.

## 개인 로컬 분석

Python 3.11+ 환경에서 `python -m pip install -r requirements.txt`를 실행합니다.
`.env.example`을 `.env`로 복사하고 이용 권한이 있는 API만 직접 설정하세요.

- 가격 수집: `download_daily_ohlcv.py`, `update_kr_incremental.py`
- 공시·뉴스: `fetch_disclosures.py`, `fetch_news.py`
- 리서치: `collect_reports.py`, `collect_naver_reports.py`, `collect_telegram.py`
- 점수 계산: `python score_universe.py`
- 리서치 분석: `python analyze_research.py`

각 명령의 `--help`에서 입력 옵션을 확인할 수 있습니다. 원자료는 `data/`, 분석 결과는
`local-output/data/`에 저장되며 모두 Git 추적에서 제외됩니다. 공개 데모 파일을 덮어쓰지 않습니다.
수집 대상 API·채팅방·문서에 대한 접근 및 이용 권한은 실행자가 확인해야 합니다.
외부 자료를 내려받을 수 있다는 사실이 공개 재배포 권한을 의미하지는 않습니다.

Windows의 `update_kr_scores.ps1`, `update_research.ps1`은 로컬 분석만 수행합니다.
자동 Git 커밋·push·Netlify 배포를 수행하지 않습니다. 작업 등록 스크립트는 직접 실행할 때만
예약 작업을 생성합니다. 개인 분석 결과는 공개 사이트로 복사하지 마세요.

## 검사

```sh
python -m unittest discover -s tests -v
node --test tests/*.test.cjs
```

PowerShell에서는 `./tests/check_scripts.ps1`로 스크립트 구문·실패 전파도 확인합니다.
외부 API를 모의 객체로 대체해 테스트하며 수집·배포 예약 작업을 설치하지 않습니다.

## 배포와 라이선스

합성 데모 배포 방법은 [DEPLOY.md](DEPLOY.md)를 참고하세요.
직접 작성한 코드와 합성 예제는 [MIT](LICENSE)입니다. 의존성은 각 라이선스를 따릅니다.
DART·네이버·KRX·Yahoo·Telegram 등 외부 서비스의 데이터나 상표에 대한 권리는
이 라이선스로 부여되지 않습니다. 투자 판단이나 실제 수익률 검증을 제공하는 프로젝트가 아닙니다.
