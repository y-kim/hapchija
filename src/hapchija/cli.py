"""hapchija 명령.

    hapchija list
    hapchija options --recipe recipes/foo.json
    hapchija build --recipe recipes/foo.json [-w 400,bold] [-s normal,italic]
                   [--variant normal,nerd] [--quick]

두께(-w), 기울임(-s), 변종(--variant)은 서로 독립인 선택자다. 셋 다 쉼표
목록이고 비우면 전부다. normal 은 세 곳 모두에서 "기본"을 뜻하는 예약어다:
400, 곧게 선 것, 변종 없는 빌드. --quick 은 -w normal -s normal 의 줄임말이다.

합성 단계는 FontForge 의 Python 바인딩이 필요하다. 지금 인터프리터에서
import 가 되면 그대로 쓰고, 안 되면 `fontforge -script` 로 돌려서 부른다.
"""

from __future__ import annotations

import argparse
import glob
import os
import multiprocessing
import shutil
import subprocess
import sys

from . import fetch, finalize, recipe as R

COMPOSE_MODULE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compose.py")


def fontforge_available():
    try:
        import fontforge  # noqa: F401
        return True
    except ImportError:
        return False


def compose_command(argv):
    """합성 단계를 실행할 명령. 바인딩이 없으면 fontforge 로 넘긴다."""
    env = dict(os.environ)
    pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = pkg_root + os.pathsep + env.get("PYTHONPATH", "")
    if fontforge_available():
        return [sys.executable, "-m", "hapchija.compose"] + argv, env
    if not shutil.which("fontforge"):
        raise SystemExit(
            "ERROR: FontForge 를 찾을 수 없습니다.\n"
            "  파이썬 바인딩 (python3-fontforge) 이나 fontforge 명령이 필요합니다."
        )
    return ["fontforge", "-script", COMPOSE_MODULE] + argv, env


def run_compose(recipe_path, root, out_dir, variants, styles, jobs=1):
    """합성 단계를 돌린다. styles 는 만들 스타일의 파일 이름 목록이다.

    두께는 서로 독립적이라 병렬로 만들 수 있다. 다만 코드포인트 배분과 폭
    분류는 두께와 무관하게 한 번만 하면 되므로, 먼저 계산해 파일로 남기고
    (--plan-only) 워커들이 그것을 읽어 쓴다. FontForge 는 fork 안전을 보장하지
    않으므로 스레드가 아니라 프로세스로 나눈다.
    """
    base = ["--recipe", recipe_path, "--root", root, "--out", out_dir]
    for name, on in variants.items():
        if on:
            base.append("--variant")
            base.append(name)
    all_styles = ["--styles", ",".join(styles)]

    if jobs <= 1 or len(styles) <= 1:
        cmd, env = compose_command(base + all_styles)
        subprocess.run(cmd, check=True, env=env)
        return

    # 배분은 고른 스타일 전체를 보고 한 번만 계산한다
    plan = os.path.join(out_dir, ".plan.json")
    cmd, env = compose_command(base + all_styles + ["--plan", plan, "--plan-only"])
    subprocess.run(cmd, check=True, env=env)

    # 두께를 워커 수만큼 갈라 준다
    chunks = [styles[i::jobs] for i in range(jobs)]
    chunks = [c for c in chunks if c]
    print("### 두께 %d개를 %d개 프로세스로 ###" % (len(styles), len(chunks)))
    procs = []
    for i, chunk in enumerate(chunks):
        cmd, env = compose_command(base + ["--plan", plan, "--styles", ",".join(chunk)])
        log = open(os.path.join(out_dir, ".worker-%d.log" % i), "w")
        procs.append((subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT),
                      log, chunk))
    failed = []
    for pr, log, chunk in procs:
        rc = pr.wait()
        log.close()
        print("  [%s] %s" % ("완료" if rc == 0 else "실패 rc=%d" % rc, " ".join(chunk)))
        if rc != 0:
            failed.append(chunk)
    for i in range(len(chunks)):
        path = os.path.join(out_dir, ".worker-%d.log" % i)
        if failed:
            print("--- 워커 %d 로그 ---" % i)
            with open(path, encoding="utf-8", errors="replace") as fp:
                print("".join(fp.readlines()[-25:]))
        os.remove(path)
    if os.path.exists(plan):
        os.remove(plan)
    if failed:
        raise SystemExit("ERROR: 합성 실패")


def variants_of(rec):
    """만들 변종 목록.

    (변종 이름, 파일 접두어, 출력 디렉터리 이름) 을 돌려준다. 변종 없는
    기본 빌드는 normal 이라는 예약된 이름을 쓴다.
    디렉터리는 글꼴 가족 이름 그대로 쓴다. 글꼴을 설치할 때 고르기 쉽도록
    파일 이름(공백 없음)이 아니라 사람이 보는 이름을 쓴다.
    """
    out = []
    seen = set()
    for source in rec["sources"]:
        when = source.get("when")
        if when and when not in seen:
            seen.add(when)
            suffix = R.variant_suffix(rec, {when: True})
            out.append((when, R.family_short(rec, suffix), R.family_name(rec, suffix)))
    out.append(("normal", R.family_short(rec), R.family_name(rec)))
    return out


def move_output(root, prefix, build_dir, dir_name):
    dest = os.path.join(build_dir, dir_name)
    os.makedirs(dest, exist_ok=True)
    moved = 0
    for path in glob.glob(os.path.join(root, prefix + "-*.ttf")):
        shutil.move(path, os.path.join(dest, os.path.basename(path)))
        moved += 1
    return dest, moved


def check(rec, build_dir, families, styles):
    from fontTools.ttLib import TTFont

    expected, missing = [], []
    for prefix, dir_name in families:
        for style in styles:
            path = os.path.join(build_dir, dir_name, "%s-%s.ttf" % (prefix, style["file"]))
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


def resolve(args):
    """레시피 경로와 root 를 정한다. root 는 소스와 출력의 기준 디렉터리다."""
    path = os.path.abspath(args.recipe)
    if not os.path.isfile(path):
        print("ERROR: 레시피가 없습니다: %s" % path, file=sys.stderr)
        return None, None, None
    rec = R.load(path)
    root = os.path.abspath(args.root) if args.root else os.path.dirname(os.path.dirname(path))
    return path, rec, root


def weight_table(rec):
    """레시피에 있는 두께를 (숫자, 이름) 으로, 가벼운 것부터."""
    out = []
    for style in rec["styles"]:
        key = (style["weight"], style["name"].lower())
        if key not in out:
            out.append(key)
    return sorted(out)


def cmd_options(args):
    """이 레시피가 build 의 -w / -s / --variant 에 받는 값을 보여 준다."""
    recipe_path, rec, root = resolve(args)
    if not rec:
        return 2
    styles = rec["styles"]
    weights = weight_table(rec)
    slants = [t for t in R.SLANTS if any(R.slant_matches(s, t) for s in styles)]

    def weight_label(weight, name):
        aliases = [a for a, v in R.WEIGHT_ALIASES.items() if v == weight]
        return "%d %s" % (weight, name) + (" (= %s)" % ", ".join(aliases) if aliases else "")

    print("recipe : %s (%s)" % (os.path.relpath(recipe_path), rec.get("name")))
    print()
    print("-w, --weight   " + ", ".join(weight_label(w, n) for w, n in weights))
    print("-s, --style    " + ", ".join(slants))
    print("--variant      " + ", ".join("%s (%s)" % (name, family)
                                        for name, _, family in variants_of(rec)))
    quick = R.select_styles(rec, ["normal"], ["normal"])
    print("--quick        " + (", ".join(s["file"] for s in quick)
                               if quick else "(400 두께가 없어 쓸 수 없음)"))
    print()
    print("스타일 %d개. 두께 × 기울임, 칸은 파일 이름." % len(styles))
    label_width = max(len("%d %s" % (w, n)) for w, n in weights)
    cell_width = max([len(c) for c in slants] + [len(s["file"]) for s in styles])
    print("  %-*s  %s" % (label_width, "", "  ".join("%-*s" % (cell_width, c) for c in slants)))
    for weight, name in weights:
        cells = []
        for slant in slants:
            hit = [s for s in styles if s["weight"] == weight
                   and s["name"].lower() == name and R.slant_matches(s, slant)]
            cells.append(hit[0]["file"] if hit else "-")
        print("  %-*s  %s" % (label_width, "%d %s" % (weight, name),
                              "  ".join("%-*s" % (cell_width, c) for c in cells)))
    return 0


def cmd_fetch(args):
    path, rec, root = resolve(args)
    if not rec:
        return 2
    return fetch.run(rec, root, force=args.force)


def missing_sources(rec, root):
    """레시피가 쓰는 소스 중 실제로 없는 파일."""
    dirs = R.source_dirs(rec, root)
    out = []
    for source in rec.get("sources", []):
        for style in rec.get("styles", []):
            try:
                p = R.resolve(dirs, source["path"].format(**style))
            except KeyError:
                continue
            if not os.path.exists(p):
                out.append(os.path.relpath(p, root))
    return sorted(set(out))


def cmd_build(args):
    recipe_path, rec, root = resolve(args)
    if not rec:
        return 2
    miss = missing_sources(rec, root)
    if miss:
        print("ERROR: 소스 글꼴이 없습니다 (%d개)" % len(miss), file=sys.stderr)
        for p in miss[:6]:
            print("  " + p, file=sys.stderr)
        if len(miss) > 6:
            print("  ... 외 %d개" % (len(miss) - 6), file=sys.stderr)
        if rec.get("fetch"):
            print("\n  먼저 받아 오세요:  hapchija fetch --recipe %s"
                  % os.path.relpath(recipe_path), file=sys.stderr)
        return 2

    build_dir = os.path.join(root, rec.get("build", {}).get("outputDir", "build"))

    # 두께와 기울임. --quick 은 비어 있는 쪽을 normal 로 채운다.
    weights = R.split_list(args.weight) or (["normal"] if args.quick else [])
    slants = R.split_list(args.style) or (["normal"] if args.quick else [])
    try:
        styles = R.select_styles(rec, weights, slants)
    except ValueError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 2
    if not styles:
        print("ERROR: 두께 %s 에 스타일 %s 인 것이 레시피에 없습니다"
              % (",".join(weights) or "*", ",".join(slants) or "*"), file=sys.stderr)
        return 2

    # 변종. 비우면 전부, normal 은 변종 없는 기본 빌드.
    wanted = variants_of(rec)
    names = R.split_list(args.variant)
    if names:
        known = [v[0] for v in wanted]
        unknown = [n for n in names if n not in known]
        if unknown:
            print("ERROR: 그런 변종이 없습니다: %s" % ", ".join(unknown), file=sys.stderr)
            print("  있는 변종: %s" % ", ".join(known), file=sys.stderr)
            return 2
        wanted = [v for v in wanted if v[0] in names]

    print("recipe : %s (%s)" % (os.path.relpath(recipe_path), rec.get("name")))
    print("root   : %s" % root)
    print("styles : %s (%d)" % (", ".join(s["file"] for s in styles), len(styles)))
    print("variant: %s" % ", ".join(v[0] for v in wanted))
    files = [s["file"] for s in styles]

    # 중간 산출물은 work/ 안에서 만든다. 저장소 루트에 만들면 빌드가 중간에
    # 실패했을 때 ttf 가 그대로 남는다.
    work = os.path.join(root, rec.get("workDir", "work"))
    os.makedirs(work, exist_ok=True)

    families = []
    for name, prefix, dir_name in wanted:
        print("### Build: %s ###" % name)
        variants = {} if name == "normal" else {name: True}
        run_compose(recipe_path, root, work, variants, files, jobs=args.jobs)
        finalize.run(rec, work, variants, files)
        dest, moved = move_output(work, prefix, build_dir, dir_name)
        print("-> %s (%d 개)" % (os.path.relpath(dest, root), moved))
        families.append((prefix, dir_name))

    shutil.rmtree(work, ignore_errors=True)

    print("### Checking generated fonts ###")
    rc = check(rec, build_dir, families, styles)
    print("### Build OK ###" if rc == 0 else "### Build FAILED ###")
    return rc


def main(argv=None):
    parser = argparse.ArgumentParser(prog="hapchija",
                                     description="레시피대로 여러 글꼴을 하나로 합친다")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("list", help="레시피 목록")
    p.add_argument("--dir", default="recipes")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("options", help="레시피가 build 의 -w / -s / --variant 에 받는 값")
    p.add_argument("--recipe", default=os.environ.get("RECIPE"))
    p.add_argument("--root", default=None)
    p.set_defaults(func=cmd_options)

    p = sub.add_parser("fetch", help="레시피가 선언한 소스 글꼴을 받아온다")
    p.add_argument("--recipe", default=os.environ.get("RECIPE"))
    p.add_argument("--root", default=None)
    p.add_argument("--force", action="store_true", help="이미 있어도 다시 받는다")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("build", help="레시피대로 빌드")
    p.add_argument("--recipe", default=os.environ.get("RECIPE"))
    p.add_argument("--root", default=None,
                   help="소스와 출력의 기준 디렉터리 (기본: 레시피의 상위)")
    p.add_argument("-w", "--weight", action="append", metavar="W[,W...]",
                   help="만들 두께. 숫자(400)나 레시피의 이름(bold, text). normal 은 400. 기본은 전부")
    p.add_argument("-s", "--style", action="append", metavar="S[,S...]",
                   help="만들 기울임. normal(곧게 선 것), italic. 기본은 둘 다")
    p.add_argument("--variant", action="append", metavar="V[,V...]",
                   help="만들 변종. normal 은 변종 없는 기본 빌드. 기본은 전부")
    p.add_argument("--quick", action="store_true",
                   default=os.environ.get("QUICK") == "1",
                   help="-w normal -s normal 의 줄임말 (QUICK=1 로도 켜짐)")
    p.add_argument("-j", "--jobs", type=int,
                   default=int(os.environ.get("JOBS") or 0) or max(1, multiprocessing.cpu_count() - 1),
                   help="동시에 만들 두께 수 (기본: CPU 수 - 1)")
    p.set_defaults(func=cmd_build)

    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        parser.print_help()
        return 2
    if args.cmd in ("build", "fetch", "options") and not args.recipe:
        print("ERROR: --recipe 가 필요합니다", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
