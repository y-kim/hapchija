"""레시피 읽기와, 한 두께를 만드는 동안 들고 다니는 값."""

from __future__ import annotations

import json
import os


def load(path):
    with open(path, encoding="utf-8") as fp:
        return json.load(fp)


def cp(value):
    """'2500' 같은 16진 문자열을 코드포인트로."""
    return int(value, 16)


def cp_range(pair):
    """['2500', '257f'] 을 끝을 포함하는 range 로."""
    return range(cp(pair[0]), cp(pair[1]) + 1)


def family_name(recipe, suffix=""):
    family = recipe["output"]["familyName"]
    return "%s %s" % (family, suffix) if suffix else family


def family_short(recipe, suffix=""):
    return family_name(recipe, suffix).replace(" ", "")


def variant_suffix(recipe, variants):
    """켜진 변종에 해당하는 이름 접미어."""
    suffixes = recipe["output"].get("variantSuffix", {})
    for name, on in variants.items():
        if on:
            return suffixes.get(name, "")
    return ""


# 두께 이름 중 레시피와 무관하게 늘 통하는 것. CSS font-weight 의 normal 이다.
WEIGHT_ALIASES = {"normal": 400}

# -s 로 고를 수 있는 값. normal 은 곧게 선 것.
SLANTS = ("normal", "italic")


def split_list(values):
    """['400,bold', 'text'] → ['400', 'bold', 'text'].

    쉼표로 이어 적어도, 옵션을 여러 번 적어도 된다. 소문자로 맞추고 중복은
    한 번만 남긴다.
    """
    out = []
    for value in values or []:
        for token in str(value).split(","):
            token = token.strip().lower()
            if token and token not in out:
                out.append(token)
    return out


def weight_matches(style, token):
    """두께 지정 하나가 이 스타일에 맞는가. 숫자, 레시피의 두께 이름, normal(400)."""
    if token.isdigit():
        return style["weight"] == int(token)
    if token in WEIGHT_ALIASES:
        return style["weight"] == WEIGHT_ALIASES[token]
    return style["name"].lower() == token


def slant_matches(style, token):
    return bool(style.get("italic")) == (token == "italic")


def weight_names(recipe):
    """레시피에 있는 두께를 '400 regular' 꼴로. 오류 메시지에 쓴다."""
    out = []
    for style in recipe["styles"]:
        label = "%d %s" % (style["weight"], style["name"].lower())
        if label not in out:
            out.append(label)
    return out


def select_styles(recipe, weights=None, slants=None):
    """-w / -s 로 고른 스타일. 둘 다 비면 전부.

    어느 스타일에도 맞지 않는 지정이 있으면 ValueError 를 낸다. 오타를 조용히
    넘기면 빌드가 아무것도 안 만들고 끝나기 때문이다.
    """
    styles = recipe["styles"]
    for token in weights or []:
        if not any(weight_matches(s, token) for s in styles):
            raise ValueError("그런 두께가 없습니다: %s\n  있는 두께: %s"
                             % (token, ", ".join(weight_names(recipe))))
    for token in slants or []:
        if token not in SLANTS:
            raise ValueError("그런 스타일이 없습니다: %s\n  있는 스타일: %s"
                             % (token, ", ".join(SLANTS)))
    return [s for s in styles
            if (not weights or any(weight_matches(s, t) for t in weights))
            and (not slants or any(slant_matches(s, t) for t in slants))]


def pick_styles(recipe, files=None):
    """파일 이름(Regular, BoldItalic ...)으로 고른 스타일. 비면 전부.

    고르는 규칙은 cli 가 한 번만 적용하고, compose 와 finalize 에는 그 결과를
    이름으로 넘긴다.
    """
    if not files:
        return recipe["styles"]
    want = set(files.split(",")) if isinstance(files, str) else set(files)
    return [s for s in recipe["styles"] if s["file"] in want]


def active_sources(recipe, variants):
    """when 조건을 만족하는 소스만. 순서가 곧 우선순위다."""
    return [
        s for s in recipe["sources"]
        if not s.get("when") or variants.get(s["when"])
    ]


class Context:
    """한 두께를 만드는 동안 들고 다니는 값."""

    def __init__(self, recipe, style, root, variants):
        self.recipe = recipe
        self.style = style
        self.variants = variants
        target = recipe["target"]
        self.em_ascent = target["em"]["ascent"]
        self.em_descent = target["em"]["descent"]
        self.half_width = target["halfWidth"]
        self.full_width = self.half_width * 2
        self.italic_angle = target.get("italicAngle", 0)
        self.src_dirs = source_dirs(recipe, root)
        self.src_dir = self.src_dirs[0]

    def path(self, template, style=None):
        """소스 경로. {...} 에는 styles 항목의 필드 이름을 쓴다.

        sourceDir 와 fetchDir 를 순서대로 찾는다. 직접 만든 자산은 저장소에
        두고, 받아온 글꼴은 따로 두기 위해서다.
        """
        return resolve(self.src_dirs, template.format(**(style or self.style)))

    def width_value(self, spec, source_half=None):
        """폭 지정을 실제 값으로.

            "half" / "full" / "source-half"   이름
            {"emDiv": 3}                      전각을 n 으로 나눈 값
            352                               유닛 값 그대로

        emDiv 는 공백 문자에 쓴다. EM SPACE 를 전각으로 두면 THREE-PER-EM 은
        그 1/3 이어야 하는데, 전각 폭이 바뀌어도 따라가도록 분모로 적는다.
        """
        if isinstance(spec, (int, float)):
            return spec
        if isinstance(spec, dict):
            if "emDiv" in spec:
                return round(self.full_width / spec["emDiv"])
            raise ValueError("알 수 없는 폭 지정: %r" % spec)
        if spec == "half":
            return self.half_width
        if spec == "full":
            return self.full_width
        if spec == "source-half":
            return source_half
        raise ValueError("알 수 없는 폭 이름: %r" % spec)


def ribbi_flags(style):
    """이 두께가 자기 패밀리 안에서 Bold / Italic 중 무엇인지.

    Regular 와 Bold 는 한 패밀리의 네 칸(RIBBI)을 쓰고, 나머지 두께는 이름에
    두께를 붙인 별도 패밀리를 가진다. 그래서 SemiBold 는 "Monoplex KR SemiBold"
    패밀리의 Regular 이지 Bold 가 아니다.

    이름 테이블(compose.font_names)과 같은 판단을 써야 fsSelection, macStyle,
    subfamily 가 서로 어긋나지 않는다.
    """
    return style["name"] == "Bold", bool(style.get("italic"))


def source_dirs(recipe, root):
    """소스를 찾을 디렉터리. 앞에서부터 찾는다.

    sourceDir 에는 저장소가 들고 있는 자산(손질한 글리프 등)을,
    fetchDir 에는 받아온 글꼴을 둔다. 둘을 나누면 저장소에 무엇이 우리 것이고
    무엇이 남의 것인지 한눈에 보인다.
    """
    dirs = [os.path.join(root, recipe.get("sourceDir", "source"))]
    fetch_dir = recipe.get("fetchDir")
    if fetch_dir:
        dirs.append(os.path.join(root, fetch_dir))
    return dirs


def resolve(dirs, relative):
    """여러 디렉터리에서 먼저 찾아지는 것. 없으면 첫 번째 경로를 돌려준다."""
    for d in dirs:
        p = os.path.join(d, relative)
        if os.path.exists(p):
            return p
    return os.path.join(dirs[0], relative)
