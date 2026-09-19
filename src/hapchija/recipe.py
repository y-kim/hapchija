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


def styles_for(recipe, debug=False):
    styles = recipe["styles"]
    if debug:
        return [styles[recipe.get("debugStyleIndex", 0)]]
    return styles


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
