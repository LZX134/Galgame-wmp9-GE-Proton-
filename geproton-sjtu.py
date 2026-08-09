#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
geproton-sjtu.py — Steam Deck 一步到位工具 (GE-Proton + Flatseal/Protontricks + wmp9)
=====================================================================================
参考: https://github.com/thingsiplay/geprotondl (CLI 思路)
      https://github.com/GloriousEggroll/proton-ge-custom (GE-Proton 上游)

三大功能 (纯标准库, Python 3.8+, SteamOS / Linux / Windows 均可运行):

【1】GE-Proton 一步到位 (默认)
      - 默认走「上海交通大学 SJTUG 镜像」读取 release 信息 + 下载, 国内不再超时
      - 自动创建 compatibilitytools.d 目录, 自动探测 SteamOS/原生/Flatpak/Snap 路径
      - 断点续传 + 自动重试, SHA512 校验, 自动识别 x86_64 / aarch64
      - 更新检查: 有新版本时询问是否更新; 询问是否保留旧版本 (y/n), 默认删旧装新

【2】Steam Deck 工具链
      - 安装 / 检查 Flatseal 与 Protontricks (flatpak)
      - 扫描本机已安装的 Steam 游戏 (读 appmanifest_*.acf + libraryfolders.vdf)

【3】按游戏安装 wmp9 (Windows Media Player 9, 老游戏过场动画需要)
      - 通过 Steam AppID 定位游戏, 运行: flatpak run com.github.Matoking.protontricks <appid> wmp9
      - 自动预置 scripten.exe / MPSetup.exe 到 winetricks 缓存目录,
        绕开微软服务器 SSL/TLS 证书报错
      - exe 优先从你自己的 GitHub 仓库下载 (Release 附件 / 仓库根目录),
        配 GE_WMP9_REPO 环境变量; 回退 SJTU 镜像 -> 微软直连 -> 互联网档案馆

用法示例:
  python3 geproton-sjtu.py                  # GE-Proton 一步到位
  python3 geproton-sjtu.py --check          # 只检查 GE-Proton 更新 (0=最新, 2=有更新)
  python3 geproton-sjtu.py --tools          # 安装 Flatseal + Protontricks
  python3 geproton-sjtu.py --games          # 列出本机已安装 Steam 游戏
  python3 geproton-sjtu.py --wmp9           # 交互选择游戏装 wmp9
  python3 geproton-sjtu.py --wmp9 730       # 给 AppID 730 装 wmp9
  python3 geproton-sjtu.py --wmp9 "刺客信条" # 按游戏名装 wmp9
  python3 geproton-sjtu.py -y               # GE-Proton 全自动 (删旧装新)
  python3 geproton-sjtu.py -y --keep        # GE-Proton 全自动但保留旧版

wmp9 仓库配置:
  默认从 https://github.com/LZX134/Galgame-wmp9-GE-Proton- 取 exe
  (把 scripten.exe / MPSetup.exe 传到仓库根目录或 Release 附件即可, 无需任何配置;
   也可用环境变量 GE_WMP9_REPO 换成其他仓库)

flatpak 源:
  国内网络建议先执行 --flathub-mirror 把 flatpak 源切到上海交大镜像
  (恢复官方源: --flathub-official)
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROG = "geproton-sjtu"
TOOL_VERSION = "1.3.2"
OWNER_REPO = "GloriousEggroll/proton-ge-custom"
# 你自己的 GitHub 仓库: 放置 scripten.exe / MPSetup.exe (仓库根目录或 Release 附件),
# 可用环境变量 GE_WMP9_REPO 覆盖
DEFAULT_WMP9_REPO = "https://github.com/LZX134/Galgame-wmp9-GE-Proton-"
GITHUB_BASE = "https://github.com/" + OWNER_REPO
API_BASE = "https://api.github.com/repos/" + OWNER_REPO + "/releases"
# 上海交通大学 SJTUG 镜像 (智能缓存 github-release), 失败自动回退 GitHub
MIRROR_BASES = [
    "https://mirrors.sjtug.sjtu.edu.cn/github-release",
    "https://mirror.sjtu.edu.cn/github-release",
]
MIRRORS = [b + "/" + OWNER_REPO for b in MIRROR_BASES]
RETRIES = 3
UA = {"User-Agent": PROG + "/" + TOOL_VERSION}
PATT = re.compile(r"GE-Proton\d+-\d+")

# ---- Steam Deck 扩展 ----
FLATSEAL_APP = "com.github.tchx84.Flatseal"
PROTONTRICKS_APP = "com.github.Matoking.protontricks"
FLATHUB_SJTU = "https://mirror.sjtu.edu.cn/flathub"
FLATHUB_OFFICIAL = "https://flathub.org/repo/flathub.flatpakrepo"
WMP9_CACHE_FILES = {"scripten.exe": "wsh57", "MPSetup.exe": "wmp9"}
WMP9_FALLBACK_URLS = {
    "scripten.exe": [
        "https://download.microsoft.com/download/4/4/d/44de8a9e-630d-4c10-9f17-b9b34d3f6417/scripten.exe",
        "https://web.archive.org/web/2000/https://download.microsoft.com/download/4/4/d/44de8a9e-630d-4c10-9f17-b9b34d3f6417/scripten.exe",
        "https://web.archive.org/web/2if_/https://download.microsoft.com/download/4/4/d/44de8a9e-630d-4c10-9f17-b9b34d3f6417/scripten.exe",
    ],
    "MPSetup.exe": [
        "https://web.archive.org/web/20180404022333if_/download.microsoft.com/download/1/b/c/1bc0b1a3-c839-4b36-8f3c-19847ba09299/MPSetup.exe",
        "https://web.archive.org/web/2if_/download.microsoft.com/download/1/b/c/1bc0b1a3-c839-4b36-8f3c-19847ba09299/MPSetup.exe",
    ],
}

ASSUME_YES = False
DRY_RUN = False
SSL_CTX = ssl.create_default_context()


# ---------- 小工具 ----------
def c_green(s):   return "\033[32m" + s + "\033[0m" if sys.stdout.isatty() else s
def c_yellow(s):  return "\033[33m" + s + "\033[0m" if sys.stdout.isatty() else s
def c_red(s):     return "\033[31m" + s + "\033[0m" if sys.stdout.isatty() else s
def c_cyan(s):    return "\033[36m" + s + "\033[0m" if sys.stdout.isatty() else s


def warn(msg):
    print(c_yellow("警告: " + msg))


def err(msg):
    print(c_red("错误: " + msg), file=sys.stderr)


def ask_yes_no(question, default=False):
    """y/n 确认。ASSUME_YES -> 直接 yes; 非交互 -> 返回 default。"""
    if ASSUME_YES:
        print(question + " [y/N] y")
        return True
    if not sys.stdin.isatty():
        ans = "y" if default else "n"
        print(question + " [y/N] {} (非交互环境, 按默认处理; 如需自动确认请加 -y)".format(ans))
        return default
    while True:
        try:
            ans = input(question + " [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return default
        if ans in ("y", "yes"):
            return True
        if ans in ("", "n", "no"):
            return False
        print("请输入 y 或 n")


def ask_number(prompt, lo, hi):
    if not sys.stdin.isatty():
        print(prompt + " (非交互环境, 请用参数显式指定)")
        return None
    while True:
        try:
            ans = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if ans.isdigit() and lo <= int(ans) <= hi:
            return int(ans)
        print("请输入 {}~{} 之间的数字".format(lo, hi))


def parse_version(tag):
    m = re.search(r"GE-Proton(\d+)-(\d+)", tag)
    return (int(m.group(1)), int(m.group(2))) if m else None


def version_key(tag):
    v = parse_version(tag)
    return v or (0, 0)


def normalize_tag(tag):
    """'11-3' -> 'GE-Proton11-3'"""
    tag = tag.strip()
    if PATT.fullmatch(tag):
        return tag
    m = re.fullmatch(r"(\d+)-(\d+)", tag)
    if m:
        return "GE-Proton{}-{}".format(m.group(1), m.group(2))
    return tag


# ---------- GE-Proton 安装目录 ----------
def default_install_dir():
    home = Path.home()
    candidates = []
    if os.name == "nt":
        pf = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        candidates.append(Path(pf) / "Steam" / "steamapps" / "compatibilitytools.d")
    else:
        candidates = [
            home / ".steam" / "steam" / "compatibilitytools.d",     # SteamOS 3.6+ / 新版 Steam 实际目录
            home / ".local" / "share" / "Steam" / "compatibilitytools.d",
            home / ".steam" / "root" / "compatibilitytools.d",      # 旧版软链接 (指向上面同一位置)
            home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam" / "compatibilitytools.d",  # flatpak
            home / "snap" / "steam" / "common" / ".steam" / "root" / "compatibilitytools.d",                # snap
        ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0] if candidates else None


def resolve_basedir(args):
    if args.dir:
        b = Path(args.dir).expanduser()
    else:
        d = default_install_dir()
        if not d:
            err("未找到 Steam 安装目录, 请用 --dir 手动指定")
            sys.exit(1)
        b = Path(d)
    if not DRY_RUN:
        try:
            b.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            err("无法创建安装目录 {}: {}".format(b, e))
            sys.exit(1)
    return b


# ---------- 本地已安装 GE-Proton ----------
def detect_installed(basedir):
    found = {}
    if not basedir.is_dir():
        return found
    for folder in basedir.iterdir():
        if not folder.is_dir():
            continue
        if not folder.name.startswith("GE-Proton"):
            continue
        if not (folder / "proton").is_file():
            continue
        found[folder.name] = folder
    return dict(sorted(found.items(), key=lambda kv: version_key(kv[0]), reverse=True))


def remove_version(folder):
    """安全删除 GE-Proton 目录 (双重校验, 防止误删用户数据)。"""
    folder = Path(folder)
    if not folder.name.startswith("GE-Proton"):
        raise RuntimeError("拒绝删除: 目录名不是 GE-Proton* -> {}".format(folder))
    if not (folder / "proton").is_file():
        raise RuntimeError("拒绝删除: 缺少 proton 文件, 不是 GE-Proton 目录 -> {}".format(folder))
    shutil.rmtree(folder)


# ---------- 网络 ----------
def fetch(url, timeout=45, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                return r.status, r.geturl(), r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < retries:
                time.sleep(1.5 * (i + 1))
    raise last


def get_latest_tag():
    """并行竞速获取最新版本: 两个 SJTU 镜像 + GitHub API, 谁先成功用谁, 立即返回。"""

    def probe(url, slot):
        try:
            if url.startswith("http"):
                _, final, _ = fetch(url, timeout=15, retries=0)
                m = re.search(r"/releases/tag/([^/?#]+)", final)
                tag = urllib.parse.unquote(m.group(1)) if m else None
            else:  # "api"
                _, _, data = fetch(API_BASE + "/latest", timeout=15, retries=0)
                tag = json.loads(data)["tag_name"]
            if tag and PATT.fullmatch(tag):
                slot.append(tag)
        except Exception:  # noqa: BLE001
            pass

    import threading
    urls = [base + "/releases/latest" for base in MIRRORS] + ["api"]
    slots = [[] for _ in urls]
    threads = [threading.Thread(target=probe, args=(u, s), daemon=True)
               for u, s in zip(urls, slots)]
    for t in threads:
        t.start()
    deadline = time.time() + 30
    while time.time() < deadline:
        for s in slots:
            if s:
                return s[0]
        time.sleep(0.1)
    raise RuntimeError("无法获取 GE-Proton 最新版本, 请检查网络")


def list_remote_tags():
    """远端版本列表: 镜像 releases 页 / GitHub API 并行竞速。"""

    def probe(url, slot):
        try:
            if url.startswith("http"):
                _, _, data = fetch(url, timeout=15, retries=0)
                tags = set(PATT.findall(data.decode("utf-8", "ignore")))
            else:  # "api"
                _, _, data = fetch(API_BASE, timeout=15, retries=0)
                tags = {rel.get("tag_name", "") for rel in json.loads(data)}
                tags = {t for t in tags if PATT.fullmatch(t)}
            if tags:
                slot.extend(tags)
        except Exception:  # noqa: BLE001
            pass

    import threading
    urls = [base + "/releases" for base in MIRRORS] + ["api"]
    slots = [[] for _ in urls]
    threads = [threading.Thread(target=probe, args=(u, s), daemon=True)
               for u, s in zip(urls, slots)]
    for t in threads:
        t.start()
    deadline = time.time() + 30
    while time.time() < deadline:
        got = set()
        for s in slots:
            got |= set(s)
        if got:
            return sorted(got, key=version_key, reverse=True)
        time.sleep(0.1)
    return []


def sources_for(tag, name):
    for m in MIRRORS:
        yield "{}/releases/download/{}/{}".format(m, tag, name)
    yield "{}/releases/download/{}/{}".format(GITHUB_BASE, tag, name)


def show_progress(label, done, total, final=False):
    if not sys.stderr.isatty():
        return
    if total:
        pct = min(100.0, done * 100.0 / total)
        bar = "#" * int(pct / 2)
        sys.stderr.write("\r  {} {:5.1f}% [{:<50}] {:5.1f}/{:5.1f} MB".format(
            label, pct, bar, done / 1048576, total / 1048576))
    else:
        sys.stderr.write("\r  {} {:5.1f} MB".format(label, done / 1048576))
    if final:
        sys.stderr.write("\n")
    sys.stderr.flush()


def download(url, dest, label, timeout=60):
    """断点续传下载: 失败自动重试, 每次从已有大小续传。"""
    dest = Path(dest)
    for attempt in range(1, RETRIES + 1):
        offset = dest.stat().st_size if dest.exists() else 0
        headers = dict(UA)
        if offset:
            headers["Range"] = "bytes={}-".format(offset)
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
                total = r.headers.get("Content-Length")
                total = int(total) + offset if (total and offset) else (int(total) if total else None)
                if r.status == 416:          # 服务器认为已下载完整
                    if total is not None and offset >= total:
                        return True
                    raise IOError("服务器返回 416 (Range 无效)")
                mode = "ab" if offset else "wb"
                last = time.time()
                with open(dest, mode) as f:
                    while True:
                        chunk = r.read(256 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        now = time.time()
                        if now - last >= 0.15:
                            last = now
                            show_progress(label, offset + f.tell(), total)
                if total is not None and dest.stat().st_size < total:
                    raise IOError("下载不完整 (期望 {} 字节, 实际 {})".format(total, dest.stat().st_size))
            show_progress(label, dest.stat().st_size, total, final=True)
            return True
        except urllib.error.HTTPError as e:
            if e.code == 416 and dest.exists():
                return True
            if e.code == 404:      # 404 不会因重试变好, 快速失败进入下一个源
                raise
            if attempt < RETRIES:
                warn("{} 下载中断 (HTTP {}), 断点续传重试 {}/{}...".format(label, e.code, attempt, RETRIES))
                time.sleep(2)
            else:
                raise
        except (urllib.error.URLError, OSError, IOError) as e:
            if attempt < RETRIES:
                warn("{} 下载中断 ({}), 断点续传重试 {}/{}...".format(label, e, attempt, RETRIES))
                time.sleep(2)
            else:
                raise


def is_gzip(path):
    """校验是真正的 gzip 压缩包 (1F 8B 魔数), 防止镜像返回的网页被当成 tarball。"""
    try:
        with open(path, "rb") as f:
            return f.read(2) == b"\x1f\x8b"
    except OSError:
        return False


def is_sha512_file(path, archive_name):
    """校验 sha512sum 文件内容: 至少有一行是 <64位hex> <文件名>。"""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 64 and parts[1].endswith(archive_name):
            return True
    return False


def download_one(url, dest, label, validate=None):
    """按单源下载; validate(path)->bool 校验内容, 失败清掉残留返回 False。"""
    try:
        download(url, dest, label)
        if validate and not validate(Path(dest)):
            raise RuntimeError("内容校验失败 (镜像可能返回了错误页面), 跳过该源")
        return True
    except Exception as e:  # noqa: BLE001
        warn("从 {} 下载失败: {}".format(url, e))
        Path(dest).unlink(missing_ok=True)
        return False


def verify_sha512(archive_path, sha_path, archive_name):
    want = None
    text = sha_path.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].endswith(archive_name):
            want = parts[0].lower()
            break
    if not want:
        raise RuntimeError("校验文件里找不到 {} 对应的条目".format(archive_name))
    h = hashlib.sha512()
    with open(archive_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest().lower() != want:
        raise RuntimeError("SHA512 校验失败, 下载文件可能损坏 (请重试)")


def extract(basedir, archive):
    subprocess.run(["tar", "xf", str(archive), "--directory", str(basedir)], check=True)


def asset_names(tag, arch):
    suffix = "-aarch64" if arch == "aarch64" else ""
    return tag + suffix + ".tar.gz", tag + suffix + ".sha512sum"


def detect_arch():
    m = platform.machine().lower()
    return "aarch64" if m in ("aarch64", "arm64") else "x86_64"


# ---------- GE-Proton 安装 ----------
def do_install(basedir, tag, args):
    arch = args.arch or detect_arch()
    tarball_name, sha_name = asset_names(tag, arch)
    print(c_cyan("安装 {} ({}) -> {}".format(tag, arch, basedir)))
    if DRY_RUN:
        for u in sources_for(tag, tarball_name):
            print("  [dry-run] 将下载: " + u)
        print("  [dry-run] 跳过下载 / 校验 / 解压")
        return 0
    tmp = Path(tempfile.mkdtemp(prefix="geproton-sjtu-"))
    try:
        archive = tmp / tarball_name
        ok = False
        for url in sources_for(tag, tarball_name):
            print("  下载来源: " + url)
            if download_one(url, archive, tarball_name, validate=is_gzip):
                ok = True
                break
        if not ok:
            err("tarball 下载失败, 请检查网络后重试")
            return 1
        sha_file = tmp / sha_name
        ok = False
        for url in sources_for(tag, sha_name):
            if download_one(url, sha_file, sha_name,
                            validate=lambda p: is_sha512_file(p, tarball_name)):
                ok = True
                break
        if not ok:
            err("sha512 校验文件下载失败")
            return 1
        if not args.no_verify:
            print("  校验 SHA512 ...")
            try:
                verify_sha512(archive, sha_file, tarball_name)
            except RuntimeError as e:
                err(str(e))
                return 1
        print("  解压到 {} ...".format(basedir))
        target_dir = basedir / tag
        if target_dir.exists():
            remove_version(target_dir)  # --force 覆盖重装时清理
        extract(basedir, archive)
        if not (target_dir / "proton").is_file():
            err("解压后未找到 proton 文件, 安装可能不完整, 请手动检查: {}".format(target_dir))
            return 1
        print(c_green("完成! {} 已安装到 {}".format(tag, basedir)))
        print("提示: 重启 Steam (或重新登录) 后, 在游戏的兼容层设置里选择 {} 即可使用。".format(tag))
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- GE-Proton 各子命令 ----------
def cmd_list(basedir):
    installed = detect_installed(basedir)
    if not installed:
        print("未安装任何 GE-Proton。目录: {}".format(basedir))
        return 0
    print("已安装 ({}):".format(basedir))
    for tag, folder in installed.items():
        print("  {}  ->  {}".format(tag, folder))
    return 0


def cmd_check(basedir):
    installed = detect_installed(basedir)
    try:
        latest = get_latest_tag()
    except RuntimeError as e:
        err(str(e))
        return 1
    if not installed:
        print("本地: 未安装 GE-Proton | 最新: {}".format(latest))
        return 2
    cur = max(installed, key=version_key)
    if latest in installed:
        print("已是最新: {} (位于 {})".format(latest, basedir))
        return 0
    print("本地: {} | 最新: {} — 有可用更新".format(cur, latest))
    return 2


def cmd_one_step(basedir, args):
    installed = detect_installed(basedir)
    try:
        latest = get_latest_tag()
    except RuntimeError as e:
        err(str(e))
        return 1

    if not installed:
        print("未检测到已安装的 GE-Proton, 将安装最新版 {}".format(latest))
        if not ask_yes_no("是否下载并安装 {}? (走 SJTU 镜像)".format(latest), default=True):
            print("已取消。")
            return 0
        return do_install(basedir, latest, args)

    cur = max(installed, key=version_key)
    if latest in installed:
        print(c_green("已是最新: {} (位于 {})".format(latest, basedir)))
        return 0

    print("当前版本: {} (位于 {})".format(cur, installed[cur]))
    print("最新版本: {}".format(latest))
    if not ask_yes_no("发现新版本 {}, 是否更新?".format(latest), default=True):
        print("已取消。")
        return 0
    if args.keep:
        keep = True
    elif ASSUME_YES:
        keep = False
    else:
        keep = ask_yes_no("是否保留旧版本 {}? (选 n 将删除旧版本)".format(cur), default=False)
    old_list = [t for t in installed if t != latest]
    if keep:
        if old_list:
            print("保留旧版本: " + ", ".join(old_list))
    else:
        for t in old_list:
            print("删除旧版本 {} ...".format(t))
            if not DRY_RUN:
                remove_version(installed[t])
    return do_install(basedir, latest, args)


def cmd_install_specific(basedir, tag, args):
    tag = normalize_tag(tag)
    if not PATT.fullmatch(tag):
        err("版本号格式不对, 例如: --install 11-3 或 --install GE-Proton11-3")
        return 1
    installed = detect_installed(basedir)
    if tag in installed and not args.force:
        print("{} 已安装 (位于 {}), 如要覆盖重装请加 --force".format(tag, installed[tag]))
        return 0
    if tag in installed and args.force:
        print("强制重装 {} ...".format(tag))
    return do_install(basedir, tag, args)


def cmd_remove(basedir, tag):
    tag = normalize_tag(tag)
    installed = detect_installed(basedir)
    if tag not in installed:
        err("未安装 {} (当前已安装: {})".format(tag, ", ".join(installed) or "无"))
        return 1
    if ask_yes_no("确认删除 {}? (位于 {})".format(tag, installed[tag]), default=False):
        if not DRY_RUN:
            remove_version(installed[tag])
        print(c_green("已删除 {}。".format(tag)))
    else:
        print("已取消。")
    return 0


# ================= Steam Deck 扩展 =================
# ---------- Flatseal / Protontricks ----------
def flatpak_available():
    return shutil.which("flatpak") is not None


def flatpak_installed(appid):
    try:
        out = subprocess.run(["flatpak", "list", "--app", "--columns=application"],
                             capture_output=True, text=True, timeout=60).stdout
        return appid in out.split()
    except Exception:  # noqa: BLE001
        return False


def cmd_flathub(args):
    """切换 flatpak 的 flathub 源 (默认切上海交大镜像, 国内下载更快; 可恢复官方源)。"""
    if not flatpak_available():
        err("未找到 flatpak 命令, 请在 SteamOS / Linux 桌面环境下运行")
        return 1
    if args.flathub_official:
        url, label = FLATHUB_OFFICIAL, "官方源"
    else:
        url, label = FLATHUB_SJTU, "上海交大镜像"
    if not ask_yes_no("把 flatpak 的 flathub 源切换到 {} ({})?".format(label, url), default=True):
        return 0
    print("切换中 ... (SteamOS 会弹出管理员密码确认)")
    r = subprocess.run(["flatpak", "remote-modify", "flathub", "--url=" + url])
    if r.returncode == 0:
        print(c_green("已切换到 {}: {}".format(label, url)))
        return 0
    err("切换失败(退出码 {}), 可手动执行:"
        "  sudo flatpak remote-modify flathub --url={}"
        .format(r.returncode, url))
    return 1


def cmd_tools(args):
    if not flatpak_available():
        err("未找到 flatpak 命令, 请在 SteamOS / Linux 桌面环境下运行")
        return 1
    apps = [
        (FLATSEAL_APP, "Flatseal (图形化权限管理工具)"),
        (PROTONTRICKS_APP, "Protontricks (按游戏运行 winetricks 命令)"),
    ]
    for app, label in apps:
        if flatpak_installed(app):
            print("已安装: {} ({})".format(app, label))
            continue
        if not ask_yes_no("是否安装 {}? ({})".format(app, label), default=True):
            continue
        print("安装 {} ...".format(app))
        r = subprocess.run(["flatpak", "install", "-y", "flathub", app])
        if r.returncode == 0:
            print(c_green("已安装 {} ({})".format(app, label)))
        else:
            err("安装 {} 失败, 退出码 {}".format(app, r.returncode))
    if flatpak_installed(PROTONTRICKS_APP):
        print()
        if ask_yes_no("给 Protontricks 授予全部文件系统权限? (等效 Flatseal 里勾选 Filesystem 四项,"
                      " 使其能访问 Steam 游戏目录, 否则可能读不到游戏)", default=True):
            r = subprocess.run(["flatpak", "override", "--user", PROTONTRICKS_APP,
                                "--filesystem=host", "--filesystem=host-os"])
            if r.returncode == 0:
                print(c_green("已授予全部文件系统权限, 无需再手动配置 Flatseal。"))
            else:
                err("授权失败(退出码 {}), 可手动打开 Flatseal → Protontricks → Filesystem 全勾。"
                    .format(r.returncode))
    return 0


# ---------- Steam 本地游戏扫描 ----------
def steam_steamapps_dirs():
    dirs, seen = [], set()
    home = Path.home()
    roots = []
    if os.name == "nt":
        pf = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        roots.append(Path(pf) / "Steam")
        roots.append(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Steam")
    else:
        roots = [
            home / ".steam" / "steam",
            home / ".steam" / "root",
            home / ".local" / "share" / "Steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / "data" / "Steam",
            home / "snap" / "steam" / "common" / ".steam" / "steam",
        ]
    for root in roots:
        sa = root / "steamapps"
        if sa.is_dir() and str(sa) not in seen:
            seen.add(str(sa))
            dirs.append(sa)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            for lib in re.findall(r'"path"\s*"([^"]+)"',
                                  vdf.read_text(encoding="utf-8", errors="ignore")):
                lib = lib.replace("\\\\", "\\").replace('\\"', '"')
                p = Path(lib) / "steamapps"
                if p.is_dir() and str(p) not in seen:
                    seen.add(str(p))
                    dirs.append(p)
    return dirs


def parse_appmanifest(path):
    text = path.read_text(encoding="utf-8", errors="ignore")
    appid = re.search(r'"appid"\s*"(\d+)"', text)
    name = re.search(r'"name"\s*"([^"]+)"', text)
    state = re.search(r'"StateFlags"\s*"(\d+)"', text)
    if not appid:
        return None
    return {
        "appid": appid.group(1),
        "name": name.group(1) if name else "?",
        "installed": bool(state and int(state.group(1)) & 4),
    }


def scan_steam_games():
    games, seen = [], set()
    for sa in steam_steamapps_dirs():
        for mf in sa.glob("appmanifest_*.acf"):
            g = parse_appmanifest(mf)
            if g and g["installed"] and g["appid"] not in seen:
                seen.add(g["appid"])
                games.append(g)
    return sorted(games, key=lambda g: g["name"].lower())


def print_games(games):
    for i, g in enumerate(games, 1):
        print("{:3d}. [{}] {}".format(i, g["appid"], g["name"]))


def cmd_games(args):
    games = scan_steam_games()
    if not games:
        err("未扫描到已安装的 Steam 游戏。请确认 Steam 已安装并登录, 或检查 steamapps 目录权限。")
        return 1
    print("本机已安装的 Steam 游戏 ({} 个):".format(len(games)))
    print_games(games)
    return 0


# ---------- wmp9 (Windows Media Player 9) ----------
def wmp9_repo_sources(fname):
    """优先从你自己的 GitHub 仓库取 exe (Release 附件或仓库根目录), 再走 SJTU 镜像。"""
    repo = os.environ.get("GE_WMP9_REPO", DEFAULT_WMP9_REPO).rstrip("/")
    yield repo + "/releases/latest/download/" + fname
    yield repo + "/raw/main/" + fname
    yield repo + "/raw/master/" + fname
    m = re.match(r"https?://github\.com/([^/]+)/([^/?#]+)", repo)
    if m:
        owner, reponame = m.group(1), m.group(2)
        for base in MIRROR_BASES:
            yield "{}/{}/{}/releases/latest/download/{}".format(base, owner, reponame, fname)


def wmp9_sources(fname):
    yield from wmp9_repo_sources(fname)
    for u in WMP9_FALLBACK_URLS.get(fname, []):
        yield u


def wmp9_cache_dirs():
    """protontricks (flatpak) 的 winetricks 缓存目录。"""
    home = Path.home()
    base = home / ".var" / "app" / PROTONTRICKS_APP
    return [base / "cache" / "winetricks", base / ".cache" / "winetricks"]


def is_pe_exe(path):
    """校验是真正的 Windows PE 可执行文件 (MZ 魔数), 防止镜像返回的网页被当成 exe 缓存。"""
    try:
        with open(path, "rb") as f:
            return f.read(2) == b"MZ"
    except OSError:
        return False


def ensure_wmp9_file(fname):
    sub = WMP9_CACHE_FILES[fname]
    dirs = []
    for d in wmp9_cache_dirs():
        try:
            (d / sub).mkdir(parents=True, exist_ok=True)
            dirs.append(d / sub)
        except OSError:
            pass
    if not dirs:
        err("无法创建 winetricks 缓存目录")
        return False
    if all((p / fname).exists() and is_pe_exe(p / fname) for p in dirs):
        print("  缓存已存在: {}".format(dirs[0] / fname))
        return True
    tmp = dirs[0] / fname
    ok = False
    for url in wmp9_sources(fname):
        print("  下载 {} <- {}".format(fname, url))
        if download_one(url, tmp, fname, validate=is_pe_exe):
            ok = True
            break
    if not ok:
        err("{} 下载失败, 请手动下载后放到: {}".format(fname, dirs[0]))
        return False
    for p in dirs[1:]:
        shutil.copy2(tmp, p / fname)
    return True


def choose_game(games, hint):
    if hint:
        for g in games:
            if g["appid"] == hint:
                return g
        hits = [g for g in games if hint.lower() in g["name"].lower()]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            print("匹配到多个游戏, 请选择:")
            print_games(hits)
            n = ask_number("输入序号: ", 1, len(hits))
            return hits[n - 1] if n else None
        if hint.isdigit():
            return {"appid": hint, "name": "未知游戏 (AppID {})".format(hint)}
        return None
    if not games:
        return None
    print("本机已安装的 Steam 游戏 ({} 个):".format(len(games)))
    print_games(games)
    n = ask_number("选择要给哪个游戏装 wmp9? 输入序号: ", 1, len(games))
    return games[n - 1] if n else None


def cmd_wmp9(args):
    if not flatpak_available():
        err("未找到 flatpak 命令, 请在 SteamOS / Linux 桌面环境下运行")
        return 1
    if not flatpak_installed(PROTONTRICKS_APP):
        err("尚未安装 Protontricks, 请先运行: {} --tools".format(PROG))
        return 1
    hint = (args.wmp9 or "").strip()
    if not hint and not sys.stdin.isatty():
        err("非交互环境请显式指定游戏: --wmp9 <AppID 或游戏名>")
        return 1
    games = scan_steam_games()
    target = choose_game(games, hint)
    if not target:
        err("没有可用的目标游戏。可用: --wmp9 <AppID> 或 <游戏名>, 或不带参数交互选择")
        return 1
    print("目标游戏: {} [AppID {}]".format(target["name"], target["appid"]))
    if not ask_yes_no("确认为它安装 wmp9? (将运行 flatpak run {} {} wmp9)"
                      .format(PROTONTRICKS_APP, target["appid"]), default=True):
        print("已取消。")
        return 0
    print(c_yellow("提示: 默认从你的仓库 {} 取 exe; 若还没上传 scripten.exe / MPSetup.exe,"
                   " 将回退到微软直连/互联网档案馆。传好后优先走仓库, 不再依赖微软。"
                   .format(DEFAULT_WMP9_REPO)))
    print("预置 winetricks 缓存 (scripten.exe / MPSetup.exe) ...")
    for fname in WMP9_CACHE_FILES:
        if not ensure_wmp9_file(fname):
            return 1
    print("运行 protontricks ... (可能需要几分钟)")
    r = subprocess.run(["flatpak", "run", PROTONTRICKS_APP, target["appid"], "wmp9"])
    if r.returncode == 0:
        print(c_green("完成! {} 的 wmp9 已装好, 重启游戏即可。".format(target["name"])))
        if str(target["appid"]) == "2458530":  # 魔女的夜宴
            print(c_yellow("已知问题(魔女的夜宴): GE-Proton11-3/11-1 播放 OP/ED 时画面上下颠倒,"
                           " 可在桌面模式→高级设置→视频渲染方式选\"层\"修复;"
                           " 9-11 播放时无声; 9-20 无法正常播放。"))
        return 0
    err("protontricks 退出码 {} (非 0), 请查看上方日志。".format(r.returncode))
    return 1


# ---------- 入口 ----------
def build_parser():
    ap = argparse.ArgumentParser(
        prog=PROG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Steam Deck 一步到位工具: GE-Proton + Flatseal/Protontricks + 按游戏装 wmp9"
                    " (GE-Proton 默认走上海交大 SJTUG 镜像, 自动回退 GitHub)",
        epilog="退出码: 0=成功/已最新  1=出错  2=检查到有新版本 (配合 --check 用于脚本)\n"
               "wmp9 的 exe 默认从 https://github.com/LZX134/Galgame-wmp9-GE-Proton- 取, 可用 GE_WMP9_REPO 覆盖" + chr(10) +
               "flatpak 源切换: --flathub-mirror (上海交大镜像) / --flathub-official (官方源)",
    )
    ap.add_argument("-c", "--check", action="store_true", help="只检查 GE-Proton 更新, 不下载")
    ap.add_argument("-l", "--list", action="store_true", help="列出已安装的 GE-Proton")
    ap.add_argument("-R", "--releases", action="store_true", help="列出远端全部 GE-Proton 版本")
    ap.add_argument("-i", "--install", metavar="TAG", help="安装指定 GE-Proton 版本, 如 11-3 (默认最新)")
    ap.add_argument("-r", "--remove", metavar="TAG", help="卸载指定 GE-Proton 版本")
    ap.add_argument("-f", "--force", action="store_true", help="已安装时也强制重新下载安装")
    ap.add_argument("-d", "--dir", metavar="DIR", help="GE-Proton 安装目录 (默认自动探测)")
    ap.add_argument("-a", "--arch", choices=["x86_64", "aarch64"], help="GE-Proton 架构 (默认自动检测)")
    ap.add_argument("-m", "--mirror", action="append", help="额外镜像前缀 (可多次, 优先尝试)")
    ap.add_argument("-y", "--yes", action="store_true", help="全自动, 跳过所有确认 (更新时默认删除旧版, 加 --keep 保留)")
    ap.add_argument("-k", "--keep", action="store_true", help="更新 GE-Proton 时保留旧版本")
    ap.add_argument("--no-verify", action="store_true", help="跳过 SHA512 校验 (不推荐)")
    ap.add_argument("--dry-run", action="store_true", help="只打印将执行的操作, 不实际执行")
    ap.add_argument("--insecure", action="store_true", help="忽略 SSL/TLS 证书校验 (仅作最后手段)")
    ap.add_argument("-v", "--version", action="store_true", help="显示版本")

    deck = ap.add_argument_group(title="Steam Deck 扩展")
    deck.add_argument("-t", "--tools", action="store_true", help="安装/检查 Flatseal 与 Protontricks (flatpak)")
    deck.add_argument("--flathub-mirror", action="store_true",
                      help="把 flatpak 的 flathub 源切换到上海交大镜像(国内下载更快)")
    deck.add_argument("--flathub-official", action="store_true",
                      help="把 flatpak 的 flathub 源恢复为官方源")
    deck.add_argument("-g", "--games", action="store_true", help="列出本机已安装的 Steam 游戏 (AppID)")
    deck.add_argument("-w", "--wmp9", nargs="?", const="", metavar="GAME",
                      help="为指定游戏安装 wmp9 (需 Protontricks); 可传 AppID 或游戏名, 省略则交互选择")
    return ap


def main(argv=None):
    global ASSUME_YES, DRY_RUN, SSL_CTX
    args = build_parser().parse_args(argv)
    ASSUME_YES = args.yes
    DRY_RUN = args.dry_run
    if args.mirror:
        MIRRORS[:0] = [m.rstrip("/") for m in args.mirror]
    if args.insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        SSL_CTX = ctx
        warn("已开启 --insecure: 忽略 SSL/TLS 证书校验")

    if args.version:
        print("{} {}".format(PROG, TOOL_VERSION))
        return 0
    if args.releases:
        for t in list_remote_tags():
            print(t)
        return 0
    if args.flathub_mirror or args.flathub_official:
        return cmd_flathub(args)
    if args.tools:
        return cmd_tools(args)
    if args.games:
        return cmd_games(args)
    if args.wmp9 is not None:
        return cmd_wmp9(args)

    basedir = resolve_basedir(args)

    if args.remove:
        return cmd_remove(basedir, args.remove)
    if args.list:
        return cmd_list(basedir)
    if args.check:
        return cmd_check(basedir)
    if args.install:
        return cmd_install_specific(basedir, args.install, args)
    return cmd_one_step(basedir, args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
