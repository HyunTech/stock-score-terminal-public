# 합성 데모 배포

배포 대상은 `site/` 하나입니다. GitHub 저장소 공개와 웹 서비스 배포는 별개이며,
이 공개본을 만드는 과정에서는 운영 서비스나 예약 작업을 생성하지 않습니다.

## Netlify

이 공개 저장소를 연결하면 `netlify.toml`의 publish 디렉터리 `site`를 사용합니다.
OpenAI·DART·Telegram 등 API 키를 배포 환경에 넣을 필요가 없습니다.
예제 `/api/ask` 함수도 합성 데이터로만 응답합니다.

## 정적 호스팅

`site/` 내용만 게시하면 됩니다. GitHub Pages에서는 Actions 업로드 대상으로 `site/`를 지정하거나
지원되는 정적 호스팅의 게시 루트를 `site`로 선택하세요. 별도 서버 함수 없이 로컬 질문 기능이 동작합니다.
Vercel에서도 Output Directory를 `site`로 지정하세요.

## 개인 분석 결과

`data/`, `local-output/`, `.env`, 로그·인증 파일은 배포 대상이 아닙니다.
새로 수집한 데이터는 이용 조건을 검토하기 전 공개 파일에 복사하지 마세요.
제공된 업데이트 스크립트에는 자동 배포나 Git push가 없습니다.
