"""레시피가 선언한 소스 글꼴을 받아 온다.

    hapchija fetch --recipe recipes/foo.json

용량이 큰 소스 글꼴을 저장소에 커밋하지 않고 필요할 때 받기 위한 것이다.
레시피의 `fetch` 항목이 무엇을 어디서 받아 어디에 풀지 적는다.

    "fetch": [
      { "name": "IBM Plex Sans JP",
        "url": "https://github.com/.../ibm-plex-sans-jp.zip",
        "sha256": "4c14...",
        "extract": [
          { "glob": "*/ttf/unhinted/IBMPlexSansJP-*.ttf", "to": "IBM-Plex-Sans-JP" },
          { "glob": "*/LICENSE.txt", "to": "IBM-Plex-Sans-JP" }
        ] }
    ]

받은 압축 파일은 캐시에 두고 재사용한다. 이미 풀려 있으면 건너뛴다.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
import sys
import urllib.request
import zipfile

CACHE_ENV = "HAPCHIJA_CACHE"


def cache_dir():
    d = os.environ.get(CACHE_ENV)
    if not d:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
        d = os.path.join(base, "hapchija")
    os.makedirs(d, exist_ok=True)
    return d


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fp:
        while True:
            b = fp.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def download(url, dest):
    print("  받는 중 " + url)
    tmp = dest + ".part"
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            out.write(b)
            done += len(b)
            if total:
                pct = done * 100 // total
                print(f"\r    {done//1024//1024} / {total//1024//1024} MB ({pct}%)",
                      end="", flush=True)
    if total:
        print()
    os.replace(tmp, dest)


def ensure_archive(item):
    """압축 파일을 캐시에 확보한다. 체크섬이 맞으면 다시 받지 않는다."""
    url = item["url"]
    name = item.get("cacheAs") or url.rsplit("/", 1)[-1]
    path = os.path.join(cache_dir(), name)
    want = item.get("sha256")

    if os.path.exists(path):
        if not want:
            return path
        got = sha256(path)
        if got == want:
            return path
        print(f"  캐시의 체크섬이 다릅니다. 다시 받습니다\n    기대 {want}\n    실제 {got}")
        os.remove(path)

    download(url, path)
    if want:
        got = sha256(path)
        if got != want:
            os.remove(path)
            raise SystemExit(
                f"ERROR: 체크섬이 맞지 않습니다: {url}\n  기대 {want}\n  실제 {got}"
            )
    return path


def extract(archive, rules, src_dir):
    """rules 의 glob 에 맞는 파일만 꺼낸다. 디렉터리 구조는 버리고 파일만 옮긴다."""
    n = 0
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        for rule in rules:
            pat = rule["glob"]
            to = os.path.join(src_dir, rule.get("to", ""))
            os.makedirs(to, exist_ok=True)
            hits = [x for x in names if fnmatch.fnmatch(x, pat)]
            if not hits:
                print(f"  경고: 맞는 파일이 없습니다: {pat}", file=sys.stderr)
            for name in hits:
                # 'as' 는 여러 압축 파일에서 같은 이름(LICENSE.txt 등)이 나올 때
                # 덮어쓰지 않도록 이름을 바꿔 준다. 하나만 꺼낼 때 쓴다.
                base = rule["as"] if rule.get("as") and len(hits) == 1 \
                    else os.path.basename(name)
                out = os.path.join(to, base)
                with z.open(name) as fin, open(out, "wb") as fout:
                    shutil.copyfileobj(fin, fout)
                n += 1
    return n


def item_done(item, src_dir):
    """이미 풀려 있는지. expect 에 적힌 파일이 다 있으면 건너뛴다."""
    expect = item.get("expect")
    if not expect:
        return False
    return all(os.path.exists(os.path.join(src_dir, p)) for p in expect)


def fetch_files(item, src_dir):
    """압축이 아니라 개별 파일을 받는다.

    릴리스 자산이 없고 저장소 트리에만 있는 글꼴을 위한 것이다. IBM Plex 는
    2024-08 에 패키지별 릴리스로 개편했는데, 그 이전 버전은 zip 이 없다.
    """
    n = 0
    to = os.path.join(src_dir, item.get("to", ""))
    os.makedirs(to, exist_ok=True)
    for spec in item["files"]:
        url = spec["url"] if isinstance(spec, dict) else spec
        name = spec.get("as") if isinstance(spec, dict) else None
        name = name or url.rsplit("/", 1)[-1]
        dest = os.path.join(to, name)
        want = spec.get("sha256") if isinstance(spec, dict) else None
        if os.path.exists(dest) and want and sha256(dest) == want:
            continue
        print("  받는 중 " + name)
        tmp = dest + ".part"
        with urllib.request.urlopen(url) as r, open(tmp, "wb") as out:
            shutil.copyfileobj(r, out)
        if want:
            got = sha256(tmp)
            if got != want:
                os.remove(tmp)
                raise SystemExit(
                    "ERROR: 체크섬이 맞지 않습니다: %s\n  기대 %s\n  실제 %s"
                    % (url, want, got))
        os.replace(tmp, dest)
        n += 1
    return n


def run(recipe, root, force=False):
    items = recipe.get("fetch") or []
    if not items:
        print("이 레시피에는 받아올 소스가 없습니다.")
        return 0

    # 받아온 것은 fetchDir 에 둔다. 없으면 sourceDir 에 둔다.
    src_dir = os.path.join(root, recipe.get("fetchDir") or recipe.get("sourceDir", "source"))
    os.makedirs(src_dir, exist_ok=True)
    print(f"받는 곳: {src_dir}")
    print(f"캐시: {cache_dir()}")

    for item in items:
        name = item.get("name") or (item.get("url") or "").rsplit("/", 1)[-1] or "?"
        if not force and item_done(item, src_dir):
            print(f"[건너뜀] {name} — 이미 있습니다")
            continue
        print(f"[받기] {name}")
        if item.get("files"):
            n = fetch_files(item, src_dir)
            print(f"  {n}개 파일을 받았습니다")
        else:
            archive = ensure_archive(item)
            n = extract(archive, item.get("extract", []), src_dir)
            print(f"  {n}개 파일을 풀었습니다")

    print("fetch: done")
    return 0
