# hapchija (합치자)

레시피 하나로 여러 글꼴을 하나로 합치는 도구입니다. 라틴 고정폭에 한글이나
일본어를 얹어 프로그래밍용 글꼴을 만드는 데 씁니다.

[Monoplex KR](https://github.com/y-kim/monoplex)의 빌드 스크립트에서 갈라져
나왔습니다. 그쪽은 IBM Plex Mono + IBM Plex Sans KR 전용이었는데, 무엇을 어떻게
합칠지를 JSON 레시피로 빼서 다른 조합에도 쓸 수 있게 했습니다.

## 필요한 것

pip 으로 설치되지 않는 것이 둘 있습니다.

| | 쓰임 | 설치 |
|---|---|---|
| FontForge | 글리프 합성 | `apt install fontforge python3-fontforge` / `pacman -S fontforge` |
| ttfautohint | 힌팅 (레시피가 쓸 때만) | 배포판 패키지 또는 AUR |

FontForge 는 파이썬 바인딩이 있으면 그대로 쓰고, 없으면 `fontforge -script` 로
넘겨서 씁니다.

Docker 를 쓰면 둘 다 들어 있는 이미지가 있습니다.

```bash
docker run --rm -v "$(pwd):/work" ghcr.io/yuru7/composite-font-builder \
  bash -c "cd /work && PYTHONPATH=tools/src python3 -m hapchija build --recipe recipes/foo.json"
```

## 설치

```bash
pip install git+https://github.com/y-kim/hapchija     # 그냥 쓰기
pip install -e ./tools                                # 서브모듈로 두고 고쳐 쓰기
PYTHONPATH=tools/src python3 -m hapchija              # 설치 없이
```

## 쓰기

```bash
hapchija list                                  # 레시피 목록
hapchija options --recipe recipes/foo.json     # 이 레시피가 -w/-s/--variant 에 받는 값
hapchija build --recipe recipes/foo.json       # 전체 빌드
hapchija build --recipe recipes/foo.json --quick                # Regular 하나만
hapchija build --recipe recipes/foo.json -w 400,700 -s italic   # 두께와 기울임으로 고르기
hapchija build --recipe recipes/foo.json --variant nerd         # 변종 골라 만들기
```

두께(`-w`), 기울임(`-s`), 변종(`--variant`)은 서로 독립인 선택자입니다. 셋 다
쉼표로 여러 개를 적을 수 있고, 안 적으면 전부 만듭니다.

| | 받는 값 | `normal` 의 뜻 |
|---|---|---|
| `-w`, `--weight` | 숫자(400)나 레시피의 두께 이름(bold, text) | 400 |
| `-s`, `--style` | `normal`, `italic` | 곧게 선 것 |
| `--variant` | 레시피 소스의 `when` 이름(nerd) | 변종 없는 기본 빌드 |

`--quick` 은 `-w normal -s normal` 의 줄임말입니다. 변종은 건드리지 않으니
하나만 보려면 `--quick --variant normal` 처럼 같이 적습니다.

## 레시피

레시피 하나가 글꼴 하나를 정의합니다.

```json
{
  "target":  { "em": {"ascent": 880, "descent": 120},
               "vertical": {"ascent": 950, "descent": 225, "typoLineGap": 80},
               "halfWidth": 528, "panose": {...} },
  "styles":  [ {"name": "Regular", "file": "Regular", "weight": 400,
                "panoseWeight": 5, "italic": false} ],
  "sources": [
    {"id": "latin", "role": "base",    "path": "Plex-{monoSrc}.ttf", "fit": {...}},
    {"id": "kr",    "role": "cjk",     "path": "Sans-{krSrc}.ttf",   "fit": {...}},
    {"id": "nerd",  "role": "symbols", "path": "Nerd.ttf", "when": "nerd"}
  ],
  "finalize": { "hinting": [...], "os2": {...} }
}
```

`narrowToHalf` 는 레시피 최상위에 한 번 적는 기호 폭 정책입니다. `cps` 와
`ranges` 에 적은 코드포인트를 CJK 소스에서 반각으로 만듭니다. 잉크 폭이
`maxInk` 를 넘으면 가로세로 같은 비율로 줄이고 반각에 가운데 놓습니다. 뼈대
소스는 이미 반각이라 건드리지 않습니다. 코드포인트를 아예 빼려면
`finalize.removeCodepoints` 에 적습니다.

`alignBox` 는 기호들을 같은 크기 상자에 넣고 세로 중심을 맞춥니다. 원이나
사각형으로 둘러싼 연산자처럼 서로 크기와 높이가 같아야 하는 글자들이 소스마다
갈릴 때 씁니다. `size` 는 잉크를 그 크기에 맞추고, `yCenter` 는 세로 중심을
옮깁니다. 숫자 하나면 정사각형이고 `[가로, 세로]` 면 그 상자입니다. 폭은
건드리지 않습니다.

`compose` op 는 같은 글꼴의 글리프를 옮기고 줄여 붙여 새 글리프를 만듭니다.
겹문장부호 ‼ ⁇ 처럼 CJK 소스의 전각 글리프를 줄여 넣으면 어색한 글자를 라틴
소스의 `!` `?` 로 만들 때 씁니다. 부품마다 `cp`(또는 cmap 에 없는 부품을 위한 `glyph` 이름), `dx`, `dy`,
`scale`(백분율, 자기 중심 기준)을 적고 `width` 를 주면 가운데 놓습니다. 배정 단계는 compose 로
만든 코드포인트를 그 소스 것으로 봅니다.

`output.familyName` 이 영문 가족 이름이고, 현지어 이름은
`output.localizedFamilyName` 에 `{"Korean": "푸른모"}` 처럼 적습니다. 키는
FontForge 의 언어 이름입니다.

핵심은 `sources` 입니다.

- **우선순위 순서**입니다. 앞선 소스가 같은 코드포인트를 이깁니다.
  라틴 + 한글 + 일본어처럼 셋 이상도 됩니다.
- `role: base` 인 소스가 최종 글꼴의 뼈대가 됩니다. 힌팅도 여기에만 들어갑니다.
- `when` 이 붙은 소스는 그 변종을 만들 때만 포함됩니다.
- `path` 의 `{...}` 에는 `styles` 항목의 필드 이름을 씁니다.
- 소스의 `upem` 이 달라도 `target.em` 으로 자동 정규화됩니다. 2048 짜리 글꼴을
  1000 짜리와 섞어도 됩니다.

### fit — 소스를 목표 폭에 맞추는 방법

| 모드 | 언제 |
|---|---|
| `halfScale` | 라틴 고정폭·심볼. 일정 비율로 줄이고 반각 폭에 맞춥니다 |
| `cjkUniform` | CJK 소스의 전각 폭이 한 가지로 통일된 경우 (맑은 고딕 등) |
| `cjkClassify` | 글리프마다 폭이 제각각인 경우 (IBM Plex Sans KR 등) |

### ops — 글리프 단위 조작

`preOps` → (참조 해제, em 정규화) → `ops` → `fit` → `opsAfter` 순서로 돕니다.
`preOps` 는 참조를 풀기 전에 도는데, 합성 글리프(ŕ 등)가 교체 대상을 참조로
물고 있을 때 필요합니다.

| op | 하는 일 |
|---|---|
| `scale` / `rotate` | bbox 중심 기준 변환 |
| `ifWidth` | (op 의 조건) 지금 그 폭인 글리프만 고른다 |
| `scaleOrigin` | 원점 기준 변환 |
| `translate` / `setWidth` / `clear` | 이동 / 폭 지정 / 비우기 |
| `mergeSfd` | 손질한 글리프를 담은 `.sfd` 를 합칩니다 |
| `removeLookups` | 커닝 등 GPOS lookup 제거 |
| `fitLineBox` | Powerline 구분자를 행 박스 전체에 맞춥니다 |

## 구조

| 파일 | 역할 |
|---|---|
| `cli.py` | 명령. 두 단계를 부르고 결과를 검증 |
| `compose.py` | 합성 단계. FontForge 필요 |
| `finalize.py` | 마무리 단계. 힌팅·병합·테이블 수정. fontTools 만 필요 |
| `ops.py` / `fits.py` / `recipe.py` | 글리프 조작 / 폭 맞춤 / 레시피 |

## 옮길 때 주의할 것

FontForge 의 `.pe` 스크립트에서 옮겨 온 코드라, 변환 의미가 미묘하게 다릅니다.
고칠 때 알아 두면 좋습니다.

- `Scale(s)` 와 `Rotate(a)` 는 중심 인자를 생략하면 원점이 아니라 **글리프의
  bounding box 중심**이 기준입니다.
- `Italic(a)` 는 단순 기울이기가 아니라 FontForge 전용 변환입니다.
  `font.italicize(italic_angle=a)` 를 불러야 같은 결과가 나옵니다.
- `transform` 은 **advance width 도 같이 옮깁니다.** 폭을 지키려면 되돌려야 합니다.
- 세로 메트릭은 FontForge 에서 넣어도 `mergeFonts` 와 `generate` 가 윤곽을 보고
  다시 계산합니다. 그래서 `finalize` 에서 확정합니다.

## 라이선스

MIT. [PlemolJP](https://github.com/yuru7/PlemolJP) 의 생성 스크립트에서
출발했고 그쪽도 MIT 입니다.

합성 **결과물**의 라이선스는 소스 글꼴을 따릅니다. 독점 글꼴을 합쳤다면
결과물도 배포할 수 없습니다.
