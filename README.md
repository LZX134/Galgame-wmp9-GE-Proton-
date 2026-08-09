# geproton-sjtu.py — Steam Deck 一步到位工具

在 Steam Deck / SteamOS 上装 **Galgame 或老游戏**时，你一般要手动做三件事：
装 GE-Proton、装 Flatseal / Protontricks、给单个游戏装 **wmp9**（Windows Media Player 9，
很多 Galgame 的过场动画没它就不播放）。

这个脚本把三件事全自动化了。**SteamOS / Linux / Windows 都能跑**，只依赖 Python 3.8+ 标准库。

---

## 快速开始（Steam Deck）

1. **进入桌面模式**：按住电源键 → 选择"切换到桌面模式"
2. 打开终端（开始菜单 → System → Konsole），先切 flatpak 源到国内镜像（可选但推荐，下载更快）：

   ```bash
   python3 geproton-sjtu.py --flathub-mirror
   ```

3. **装 GE-Proton**（自动下载最新版并装好，国内走上海交大镜像）：

   ```bash
   python3 geproton-sjtu.py
   ```

4. **装 Flatseal 和 Protontricks**：

   ```bash
   python3 geproton-sjtu.py --tools
   ```

5. **给 Galgame 装 wmp9**（把"游戏"换成游戏名，或直接传 Steam AppID）：

   ```bash
   python3 geproton-sjtu.py --wmp9 "游戏名字"
   # 或者: python3 geproton-sjtu.py --wmp9 730
   # 或者不带参数, 交互选择: python3 geproton-sjtu.py --wmp9
   ```

6. 回游戏模式，Steam → 游戏 → 属性 → 兼容性 → 勾选"强制使用特定兼容工具"，
   选你装的 GE-Proton 版本，启动游戏即可。

---

## wmp9 是怎么自动搞定的（重点）

protontricks 装 wmp9 时，本来会去微软服务器下载两个文件：

| 文件 | 放到的缓存目录 |
|---|---|
| `scripten.exe` | `~/.var/app/com.github.Matoking.protontricks/cache/winetricks/wsh57/` |
| `MPSetup.exe` | `~/.var/app/com.github.Matoking.protontricks/cache/winetricks/wmp9/` |

但微软的下载地址有 **SSL/TLS 证书问题**，下载必然失败——这就是教程里让你手动下载、
手动放文件的原因。

脚本做的事：在运行 protontricks 之前，**自动把两个 exe 下载好、放到上面的缓存目录**。
winetricks 发现缓存里已有文件，就不会再去微软下载，wmp9 直接装成功。

两个 exe 的下载源按顺序尝试（哪个通就用哪个）：

1. 你仓库的 GitHub Release 附件 → 2. 仓库根目录（main/master）→
   3. 上海交大 SJTU 镜像（×2）→ 4. 微软官方直连 / 互联网档案馆（archive.org）

> 默认从 `https://github.com/LZX134/Galgame-wmp9-GE-Proton-` 取 exe。
> 想换仓库？设环境变量 `GE_WMP9_REPO` 即可。

---

## 常用参数速查

### GE-Proton

| 参数 | 作用 |
|---|---|
| （不带参数） | 一步到位：检查更新 → 下载最新 → 安装 |
| `-c` / `--check` | 只检查有没有新版本（脚本用：0=已最新，2=有更新） |
| `-l` / `--list` | 列出已安装的 GE-Proton |
| `-R` / `--releases` | 列出远端全部版本号 |
| `-i TAG` / `--install TAG` | 装指定版本，如 `-i 11-3` |
| `-r TAG` / `--remove TAG` | 卸载指定版本 |
| `-f` / `--force` | 已装过也强制重下重装 |
| `-d DIR` / `--dir DIR` | 指定安装目录（默认自动探测 SteamOS/原生/Flatpak/Snap） |
| `-a x86_64\|aarch64` | 指定架构（默认自动检测） |
| `-m 前缀` | 追加镜像前缀，可多次，优先尝试 |
| `-y` | 全自动，跳过所有确认（更新时默认删旧版） |
| `-k` / `--keep` | 更新时保留旧版本（配合 `-y` 用） |
| `--no-verify` | 跳过 SHA512 校验（不推荐） |
| `--dry-run` | 只打印要做什么，不真做 |
| `--insecure` | 忽略 SSL/TLS 证书校验（最后手段） |
| `-v` / `--version` | 显示版本号 |

### Steam Deck 扩展

| 参数 | 作用 |
|---|---|
| `-t` / `--tools` | 安装/检查 Flatseal 与 Protontricks |
| `--flathub-mirror` | flathub 源切到上海交大镜像（国内快） |
| `--flathub-official` | flathub 源恢复官方 |
| `-g` / `--games` | 列出本机已安装的 Steam 游戏（AppID） |
| `-w [游戏]` / `--wmp9 [游戏]` | 给指定游戏装 wmp9，可传 AppID 或游戏名，省略则交互选择 |

**退出码**：`0` 成功/已最新 · `1` 出错 · `2` 检查到有新版本（配合 `--check` 用于脚本判断）

---

## 常见问题

**Q：提示下载慢 / 超时？**
A：GE-Proton 默认已走上海交大镜像；wmp9 的 exe 优先走你仓库（GitHub）。
国内网络 GitHub 偶尔不稳，脚本会自动换源，最终还有微软直连 / archive.org 兜底。
也可以先用 `--flathub-mirror` 切 flatpak 源。

**Q：SJTU 镜像返回"Making sure you're not a bot!"页面？**
A：这是镜像的反机器人验证。脚本会自动识别并跳过（校验 MZ 文件头），不影响使用。
也可以手动在浏览器打开一次镜像链接过验证，之后脚本可能就放行了。

**Q：装 wmp9 提示找不到 Protontricks？**
A：先跑 `python3 geproton-sjtu.py --tools` 装好它。

**Q：游戏没出现在 `--games` 列表里？**
A：游戏必须已安装（非仅入库），脚本读的是 `appmanifest_*.acf`。

**Q：脚本支持 Windows 吗？**
A：支持（测试过）。GE-Proton 主要用于 SteamOS/Linux，但 wmp9 缓存预置、
`--games` 扫描、`--wmp9` 等逻辑在 Windows 上同样可用。

---

## 目录说明（SteamOS）

- GE-Proton 安装目录：`~/.steam/root/compatibilitytools.d/`（或 `~/.local/share/Steam/compatibilitytools.d/`）
- wmp9 缓存：`~/.var/app/com.github.Matoking.protontricks/{cache,.cache}/winetricks/{wmp9,wsh57}/`

## 环境变量

| 变量 | 作用 |
|---|---|
| `GE_WMP9_REPO` | 换 wmp9 exe 的来源仓库，如 `https://github.com/你的名字/你的仓库` |

---

## 致谢

- GE-Proton 上游：[GloriousEggroll/proton-ge-custom](https://github.com/GloriousEggroll/proton-ge-custom)
- 下载思路参考：[thingsiplay/geprotondl](https://github.com/thingsiplay/geprotondl)
- 国内镜像：上海交通大学 SJTUG 镜像站
