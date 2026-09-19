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
        self.src_dir = os.path.join(root, recipe.get("sourceDir", "source"))

    def path(self, template, style=None):
        """소스 경로. {...} 에는 styles 항목의 필드 이름을 쓴다."""
        return os.path.join(self.src_dir, template.format(**(style or self.style)))

    def width_value(self, name, source_half=None):
        if name == "half":
            return self.half_width
        if name == "full":
            return self.full_width
        if name == "source-half":
            return source_half
        raise ValueError("알 수 없는 폭 이름: %r" % name)
