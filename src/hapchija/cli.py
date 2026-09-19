"""hapchija 명령.

    hapchija list
    hapchija build --recipe recipes/foo.json [--debug] [--variant nerd]

합성 단계는 FontForge 의 Python 바인딩이 필요하다. 지금 인터프리터에서
import 가 되면 그대로 쓰고, 안 되면 `fontforge -script` 로 돌려서 부른다.
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import sys

from . import finalize, recipe as R

COMPOSE_MODULE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compose.py")


def fontforge_available():
    try:
        import fontforge  # noqa: F401
        return True
    except ImportError:
        return False


def run_compose(recipe_path, root, out_dir, variants, debug):
    """합성 단계를 돌린다. 바인딩이 없으면 fontforge 로 넘긴다."""
    argv = ["--recipe", recipe_path, "--root", root, "--out", out_dir]
    for name, on in variants.items():
        if on:
            argv += ["--variant", name]
    if debug:
        argv.append("--debug")

    if fontforge_available():
        from . import compose
        compose.main(argv)
        return

    if not shutil.which("fontforge"):
        raise SystemExit(
            "ERROR: FontForge 를 찾을 수 없습니다.\n"
            "  파이썬 바인딩 (python3-fontforge) 이나 fontforge 명령이 필요합니다."
        )
    # fontforge 안의 파이썬에서는 패키지가 안 보일 수 있으므로 경로를 넘겨 준다
    env = dict(os.environ)
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = pkg_root + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run(["fontforge", "-script", COMPOSE_MODULE] + argv,
                   check=True, env=env)


def variants_of(rec):
    """만들 변종 목록. (이름, 출력 접두어)"""
    out = []
    for source in rec["sources"]:
        when = source.get("when")
        if when and when not in [v[0] for v in out]:
            out.append((when, R.family_short(rec, R.variant_suffix(rec, {when: True}))))
    out.append(("standard", R.family_short(rec)))
    return out


def move_output(root, prefix, build_dir):
    dest = os.path.join(build_dir, prefix)
    os.makedirs(dest, exist_ok=True)
    moved = 0
    for path in glob.glob(os.path.join(root, prefix + "-*.ttf")):
        shutil.move(path, os.path.join(dest, os.path.basename(path)))
        moved += 1
    return dest, moved


def check(rec, build_dir, prefixes, debug):
    from fontTools.ttLib import TTFont

    styles = R.styles_for(rec, debug)
    expected, missing = [], []
    for prefix in prefixes:
        for style in styles:
            path = os.path.join(build_dir, prefix, "%s-%s.ttf" % (prefix, style["file"]))
            expected.append(path)
            if not os.path.isfile(path):
                missing.append(path)

    for path in missing:
        print("MISSING: " + path, file=sys.stderr)
    print("expected=%d  missing=%d" % (len(expected), len(missing)))
    if missing:
        return 1

    bad = 0
    for path in expected:
        try:
            font = TTFont(path, recalcBBoxes=False, recalcTimestamp=False)
            for tag in ("head", "name", "cmap"):
                _ = font[tag]
            _ = font["glyf"] if "glyf" in font else font["CFF "]
            font.close()
        except Exception as exc:  # noqa: BLE001
            print("INVALID: %s: %s" % (path, exc), file=sys.stderr)
            bad += 1
    print("readable=%d/%d" % (len(expected) - bad, len(expected)))
    return 1 if bad else 0


def cmd_list(args):
    paths = sorted(glob.glob(os.path.join(args.dir, "*.json")))
    if not paths:
        print("레시피가 없습니다: %s" % args.dir)
        return 1
    rows = []
    for path in paths:
        try:
            rec = R.load(path)
            ids = " + ".join(s["id"] for s in rec.get("sources", []))
            rows.append((os.path.relpath(path), "%s  (%s)" % (rec.get("name", "?"), ids)))
        except Exception as exc:  # noqa: BLE001
            rows.append((os.path.relpath(path), "읽기 실패: %s" % exc))
    width = max(len(r[0]) for r in rows)
    for path, desc in rows:
        print("  %-*s  %s" % (width, path, desc))
    return 0


def cmd_build(args):
    recipe_path = os.path.abspath(args.recipe)
    if not os.path.isfile(recipe_path):
        print("ERROR: 레시피가 없습니다: %s" % recipe_path, file=sys.stderr)
        return 2

    rec = R.load(recipe_path)
    # 소스와 출력은 레시피가 있는 곳 기준. --root 로 바꿀 수 있다.
    root = os.path.abspath(args.root) if args.root else os.path.dirname(
        os.path.dirname(recipe_path))
    build_dir = os.path.join(root, rec.get("build", {}).get("outputDir", "build"))

    wanted = variants_of(rec)
    if args.debug:
        wanted = [v for v in wanted if v[0] == "standard"]
    if args.variant:
        wanted = [v for v in wanted if v[0] in args.variant]
        if not wanted:
            print("ERROR: 그런 변종이 없습니다: %s" % args.variant, file=sys.stderr)
            return 2

    print("recipe : %s (%s)" % (os.path.relpath(recipe_path), rec.get("name")))
    print("root   : %s" % root)
    print("variant: %s" % ", ".join(v[0] for v in wanted))

    prefixes = []
    for name, prefix in wanted:
        print("### Build: %s ###" % name)
        variants = {} if name == "standard" else {name: True}
        run_compose(recipe_path, root, root, variants, args.debug)
        finalize.run(rec, root, variants, args.debug)
        dest, moved = move_output(root, prefix, build_dir)
        print("-> %s (%d 개)" % (os.path.relpath(dest, root), moved))
        prefixes.append(prefix)

    print("### Checking generated fonts ###")
    rc = check(rec, build_dir, prefixes, args.debug)
    print("### Build OK ###" if rc == 0 else "### Build FAILED ###")
    return rc


def main(argv=None):
    parser = argparse.ArgumentParser(prog="hapchija",
                                     description="레시피대로 여러 글꼴을 하나로 합친다")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("list", help="레시피 목록")
    p.add_argument("--dir", default="recipes")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("build", help="레시피대로 빌드")
    p.add_argument("--recipe", default=os.environ.get("RECIPE"))
    p.add_argument("--root", default=None,
                   help="소스와 출력의 기준 디렉터리 (기본: 레시피의 상위)")
    p.add_argument("--variant", action="append", help="만들 변종. 기본은 전부")
    p.add_argument("--debug", action="store_true",
                   default=os.environ.get("DEBUG") == "1")
    p.set_defaults(func=cmd_build)

    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 2
    if args.cmd == "build" and not args.recipe:
        print("ERROR: --recipe 가 필요합니다", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
