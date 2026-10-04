# 한글패치 허브 관리

## 새 패치 추가

1. 새 공개 저장소에 `kr-patch` topic을 붙입니다.
2. `patches.yml`에 저장소 이름과 게임 정보를 추가합니다.
3. 매일 KST 06:17에 자동 반영됩니다. 급하면 Actions의 **Update Korean patch hub → Run workflow**를 실행합니다.

아카이브는 `kr-localization-archive` topic으로 분류합니다. fork·archived·비공개 저장소는 수집하지 않습니다. 패치로 보이는 이름만으로는 목록에 넣지 않습니다.

## 게임 정보 예시

```yaml
example-kr-patch:
  title: 게임 한글 제목
  original: 原題
  series: 새 시리즈
  platforms: [PC, Switch]
  genre: 어드벤처
  release_jp: "2020-02-27"
  product_id: "0100123456780000"
  base_update: Ver.1.0.2
  guide_url: https://example.com/guide/
  status: auto
  note: ""
```

`status`는 `auto`(기본), `wip`, `released`, `paused` 중 하나입니다. `auto`는 공개된 패치 릴리스가 있으면 배포, 없으면 작업 중으로 판정합니다. topic만 있고 메타데이터가 없어도 목록에 포함하며 경고를 표시합니다. 새 기종·시리즈는 필터에 자동으로 추가됩니다.

버전·다운로드·최근 푸시·stars·topic은 메타데이터에 쓰지 않습니다. 태그가 `v`와 숫자로 시작하면 패치, 그 외에는 도구 릴리스입니다. draft는 제외하고 prerelease는 최신 정식 버전에서 제외합니다. 다운로드 합계에는 prerelease를 포함한 모든 공개 패치 릴리스 첨부파일을 합산하며 도구는 제외합니다.

## 로컬 실행

Python 3.11 이상에서 저장소 루트에서 실행합니다. YAML 읽기에만 PyYAML을 사용하며 HTTP·JSON·테스트는 표준 라이브러리입니다.

```shell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/build_hub.py --dry-run
python scripts/build_hub.py
python scripts/build_hub.py --check
python -m http.server 8000 --directory docs --bind 127.0.0.1
```

Windows 터미널에서 한글 출력이 깨지면 `python -X utf8`로 실행합니다. `GITHUB_TOKEN` 환경변수가 있으면 GitHub 요청에만 사용하며 없으면 공개 API를 비인증으로 읽습니다. 토큰을 파일이나 명령 인수에 기록하지 마세요.

`--dry-run`은 파일을 쓰지 않고 요약·경고·README diff를 출력합니다. `--check`는 파일을 쓰지 않고 차이가 있으면 1, 일치하면 0, 수집·설정 오류이면 2를 반환합니다. `generated_at`만 달라졌을 때는 기존 시각과 출력 파일을 유지합니다. API 수집 실패 시 기존 JSON·README는 보존하고 실패 처리합니다.

## 프로필과 Pages

프로필 저장소는 `Dollars-Archive/Dollars-Archive` 하나입니다. `Dollars-Archive.github.io` 사용자 사이트 저장소는 만들지 않습니다. 기존 README가 있으면 `KR-PATCH-HUB:START`와 `KR-PATCH-HUB:END` 사이만 갱신하며, 마커가 없으면 마지막에 추가합니다.

Pages의 소스는 `main`의 `/docs`이며 주소는 `https://dollars-archive.github.io/Dollars-Archive/`입니다. 기존 패치·아카이브 Pages는 변경하지 않습니다.

### Pages 자동 갱신

워크플로는 `contents: write`와 사용자 승인된 `pages: write`를 사용합니다. [GitHub 공식 문서](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)에 따르면 `GITHUB_TOKEN`으로 push한 커밋은 Pages 빌드를 시작하지 않으므로 수집·커밋 단계 후 빌드를 명시적으로 요청합니다.

`main`·`/docs` 소스와 PAT 없는 구성을 유지합니다. [빌드 요청 API](https://docs.github.com/en/rest/pages/pages#request-a-github-pages-build)는 Pages 쓰기 권한을 요구합니다. 데이터 변화가 없으면 커밋하지 않으며, 이전 배포 실패에서도 회복할 수 있도록 성공한 수집 뒤에는 빌드 요청을 실행합니다.

## 선택 사항: 릴리스 직후 갱신 요청

매시 23분 자동 실행과 수동 실행으로 수집합니다. 즉시 갱신이 꼭 필요한 경우에만 패치 저장소의 릴리스 워크플로에서 다음 요청을 보낼 수 있습니다. 기본 `GITHUB_TOKEN`은 다른 저장소로 dispatch할 수 없으므로 대상 프로필 저장소의 Contents 쓰기 권한을 가진 별도 토큰이 필요합니다. 기본 설치에는 PAT를 요구하거나 패치 저장소 워크플로를 수정하지 않습니다.

```yaml
# 예시만 제공하며 패치 저장소에는 적용하지 않습니다.
- name: Request hub update
  env:
    GH_TOKEN: ${{ secrets.HUB_DISPATCH_TOKEN }}
  run: |
    gh api --method POST repos/Dollars-Archive/Dollars-Archive/dispatches \
      -f event_type=kr-patch-updated
```

## 관리 경고

최신 정식 패치 릴리스에 첨부파일이 없을 때, 작업 중 상태가 30일 넘게 푸시되지 않았을 때, 메타데이터·topic·description이 없을 때, 설치 가이드가 HTTP 200이 아닐 때, 배포 상태 README에 `/releases` 링크가 없을 때 경고를 수집합니다. 관련 아카이브의 빈 description도 수집합니다. 사용자 요청에 따라 공개 허브와 프로필 README에는 관리 경고를 표시하지 않으며, JSON과 실행 로그에서만 확인할 수 있습니다. 패치 저장소의 코드·README·릴리스·설정은 수정하지 않습니다.

## 게임 표지

`patches.yml`의 해당 게임에 `launchbox_url: https://gamesdb.launchbox-app.com/games/details/...` 한 줄을 추가합니다. 다음 자동 실행에서 Japan 앞표지를 우선 선택하고, 없으면 같은 게임·기종의 다른 지역 앞표지를 선택합니다. 발견하지 못한 게임이나 앞표지는 비워 두며 스크린샷·재구성 표지로 대체하지 않습니다.

표지는 `docs/covers/<repo>.webp`에 가로 최대 320px로 저장합니다. 출처 페이지·이미지·종류·지역·최초 수집 시각은 `docs/data/covers.json`에서 확인합니다. 출처가 같은 캐시 파일은 다시 요청하지 않습니다. 다시 받으려면 `python scripts/build_hub.py --refresh-covers`를 실행합니다.

수동 표지는 `cover: docs/covers/custom.webp` 또는 HTTPS 이미지 주소로 지정할 수 있으며 LaunchBox 선택보다 우선합니다. 수동 파일도 작은 앞표지만 사용하세요. 표지 실패는 목록 수집을 중단하지 않으며 기존 캐시를 사용할 수 있으면 유지합니다. 표지 경고도 공개 화면에는 표시하지 않습니다. `--dry-run`·`--check`는 이미지도 저장하지 않습니다.

EVE rebirth terror는 Switch판 소개에 사용된 4Gamer의 El Dia 제공 이미지를 사용합니다. 다운로드 전용 Switch판의 홍보 이미지이며 PS4 패키지 표지가 아닙니다. `cover_source`, `cover_type`, `cover_region`으로 수동 이미지의 출처·종류·지역을 기록합니다. 티어즈 투 티아라 2와 TOD Reloaded는 각각 PS3·Switch 북미 앞표지를 사용하며 일본판 지원 여부는 기존 패치 설명을 확인하세요.

## 다운로드 실시간 조회와 누적 장부

프로필 README는 GitHub Actions가 매시간 `23 * * * *`에 갱신합니다. 다운로드 수가 1이라도 바뀌면 기존 자동 갱신 메시지로 커밋하고, 변화가 없으면 커밋하지 않습니다. GitHub 예약 실행은 지연될 수 있으며 push·수동 실행은 별도로 가능합니다.

허브는 수집된 JSON을 먼저 표시한 뒤 공개 GitHub API로 다운로드 수만 갱신합니다. 최대 3개 요청을 동시에 보내며 같은 브라우저 탭에서는 저장소별 응답을 10분 캐시합니다. 더 최신 장부가 배포되면 이전 캐시를 무효화하여 오래된 숫자를 카운터 초기화로 오인하지 않습니다. 페이지네이션·초안 제외·`^v\d` 패치 태그 규칙은 수집 스크립트와 같습니다. API 오류·시간 초과·비인증 한도 초과 때는 수집값을 유지하며 공개 오류나 관리 경고를 띄우지 않습니다. 일부 저장소만 성공하면 하단에 일부 최신·일부 수집값이라고 표시합니다. 새로 연 탭은 별도 세션일 수 있습니다.

`docs/data/download-ledger.json`은 집계를 시작한 시점 이후 관측한 다운로드를 저장합니다. 키는 `repo/tag/파일명`이며 asset_id·last_count·carried·removed를 기록합니다. ID 변경이나 카운터 감소 때 이전 값을 carried에 더하고, 삭제된 파일·릴리스도 관측값을 남깁니다. 집계 시작 전에 이미 삭제된 다운로드와 두 수집 사이에 생성·삭제되어 한 번도 관측하지 못한 다운로드는 복원할 수 없습니다. 장부 시작일을 프로필과 허브에 표시합니다.

`patches.json`에 저장소별 장부와 현재값·이월값을 넣어 페이지에서도 같은 계산을 적용합니다. 현재 첨부파일의 개별 수치는 GitHub 현재값이고 프로젝트·전체 합계는 보존된 누적값입니다. 첨부파일이 릴리스 공개보다 하루 넘게 늦게 생성되면 내부 `asset-reuploaded` 경고를 수집합니다.

검증: `python -m unittest discover -s tests -v`와 `node --test tests/test_downloads.cjs`.
