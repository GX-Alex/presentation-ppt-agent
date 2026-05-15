# Playwright / Chromium 导出故障排查

> 本文档涵盖 PDF 与 `pptx-faithful` 导出所需的 Playwright Chromium 运行时常见问题。
> 对应后端服务: `browser_pool.py`、`export_service.py`

## 快速验证

Playwright 是否正常工作，只需运行以下命令：

```bash
cd backend
python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('data:text/html,<h1>Hello</h1>')
    pdf = page.pdf()
    print(f'✅ PDF generated: {len(pdf)} bytes')
    browser.close()
"
```

如果打印 `✅ PDF generated: ...`，说明 Playwright 导出功能正常。

---

## 常见问题

### 1. `playwright install chromium` 未执行

**现象**: 启动后端时日志报错 `BrowserType.launch: Executable doesn't exist at ...`

**解决**:

```bash
cd backend
python -m playwright install chromium
```

> 如果网络较慢，可以指定中国镜像（仅限 Linux）:
> ```bash
> PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright python -m playwright install chromium
> ```

### 2. 缺少系统共享库（Linux）

**现象**:
```
OSError: libnss3.so: cannot open shared object file: No such file or directory
# 或
Missing libraries: libnss3, libnspr4, libatk-1.0.so.0, ...
```

**原因**: Playwright 启动 Chromium 时需要系统级共享库。不同发行版的缺失情况不同。

**Ubuntu / Debian**:
```bash
sudo apt-get update
sudo apt-get install -y \
  libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 \
  libxkbcommon0 libxcomposite1 libxdamage1 \
  libxrandr2 libgbm1 libpango-1.0-0 \
  libcairo2 libasound2 libatspi2.0-0
```

**Fedora / RHEL**:
```bash
sudo dnf install -y \
  nss nspr atk at-spi2-atk cairo \
  pango gdk-pixbuf2 libXcomposite libXdamage \
  libXrandr libxkbcommon libdrm mesa-libgbm alsa-lib
```

**Arch Linux**:
```bash
sudo pacman -S --needed nss nspr atk at-spi2-atk cairo pango libxkbcommon
```

### 3. Docker 环境: `/dev/shm` 不足

**现象**: 导出时 Chromium 崩溃或静默退出，日志中有 `/dev/shm` 相关字样。

**原因**: Docker 默认 `/dev/shm` 为 64MB，Chromium 需要更多共享内存用于渲染。

**解决**:

**方案 A**: 在 `docker-compose.yml` 中设置：
```yaml
services:
  backend:
    shm_size: 2gb
```

**方案 B**: 或使用 `--disable-dev-shm-usage` 启动标志（已内置在 `browser_pool.py` 的 Chromium 启动参数中）。

### 4. NixOS: Chromium 找不到或库路径异常

**现象**:
```
playwright._impl._errors.Error: BrowserType.launch: Executable doesn't exist at ...
```

**原因**: NixOS 使用不可变文件系统和独特的库路径。Playwright 的自动浏览器探测在 NixOS 上会失败。

**解决**:

**方案 A**（推荐）: 使用 nixpkgs 中的 Chromium，设置环境变量指向它：
```bash
# 安装 Chromium（如尚未安装）
nix profile install nixpkgs#chromium

# 用 PLAYWRIGHT_BROWSERS_PATH 指向 Playwright 缓存位置
# 或者手动指定浏览器可执行路径
export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=$(which chromium)
```

然后在 Python 代码中或 `.env` 中配置：
```env
# 在 .env 中添加
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/run/current-system/sw/bin/chromium
```

**方案 B**: 允许 Playwright 自行下载 Chromium（需网络），但绕开 NixOS 的 FHS 限制：
```bash
# 安装 nix-ld 以支持非 NixOS 二进制文件
nix profile install nixpkgs#nix-ld

# 配置 nix-ld
export NIX_LD=$(nix eval --raw nixpkgs#stdenv.cc.cc)/lib
export NIX_LD_LIBRARY_PATH=$(nix eval --raw nixpkgs#stdenv.cc.cc.lib)/lib
```

> **注意**: NixOS 上方案 A 最可靠。Chromium 系统库路径问题在 NixOS 23.11+ 中通过 `nix-ld` 有所缓解，但仍建议优先使用系统自带的 Chromium。

### 5. 沙箱权限问题

**现象**:
```
Error: Chromium sandbox failed. Consider using --no-sandbox or setting up sandbox correctly.
```

**解决**:

**方案 A**: 使用 `--no-sandbox`（已内置在 `browser_pool.py` 的启动参数中）。

**方案 B**（更安全）: 正确配置 sandbox：
```bash
sudo sysctl -w kernel.unprivileged_userns_clone=1
```

或在 Docker 中设置 `--security-opt seccomp=unconfined`。

### 6. macOS: 权限/证书问题

**现象**: Chromium 启动后立即退出，或提示开发者无法验证。

**解决**:

```bash
# 移除 macOS 的隔离属性（若从网络下载的 Chromium）
xattr -dr com.apple.quarantine ~/Library/Caches/ms-playwright/

# 或重新安装
python -m playwright install --force chromium
```

### 7. 代理/网络导致的安装失败

**现象**: `playwright install chromium` 下载到中途失败。

**解决**:

```bash
# 使用国内镜像
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright \
  python -m playwright install chromium

# 或使用代理
ALL_PROXY=http://127.0.0.1:7890 \
  python -m playwright install chromium
```

---

## 环境变量参考

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PLAYWRIGHT_BROWSERS_PATH` | `~/Library/Caches/ms-playwright` (macOS) / `~/.cache/ms-playwright` (Linux) | 浏览器二进制文件存放路径 |
| `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD` | (未设置) | 设任意值可跳过 `install` 时的浏览器下载 |
| `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` | (自动探测) | 手动指定 Chromium 可执行文件路径 |
| `PLAYWRIGHT_DOWNLOAD_HOST` | `https://playwright.azureedge.net` | 浏览器下载镜像地址 |
| `BROWSER_POOL_MAX_PAGES` | `3` | 浏览器池最大并发页面数（本项目自定义） |

---

## Docker 部署完整示例

对于 Docker 部署，建议的 Dockerfile 片段：

```dockerfile
# ── 安装 Playwright + 系统依赖 ──
RUN pip install playwright
RUN python -m playwright install chromium \
  && python -m playwright install-deps chromium

# ── 导出功能所依赖的环境变量 ──
ENV BROWSER_POOL_MAX_PAGES=3
```

`docker-compose.yml` 中的建议配置：

```yaml
services:
  backend:
    shm_size: 2gb
    environment:
      - BROWSER_POOL_MAX_PAGES=3
```

---

## 诊断脚本

如果仍有问题，运行以下脚本将输出系统信息供排查：

```bash
cd backend
python -c "
import sys, platform, subprocess, os

print('Python:', sys.version)
print('Platform:', platform.platform())
print('Playwright installed:', end=' ')

try:
    import playwright; print(playwright.__version__)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        chromium = p.chromium
        exe = chromium.executable_path
        print(f'Chromium path: {exe}')
        print(f'Chromium exists: {os.path.exists(exe)}')

        try:
            browser = chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            print('✅ Chromium launched successfully')
            browser.close()
        except Exception as e:
            print(f'❌ Launch failed: {e}')
except ImportError:
    print('Playwright not installed')
except Exception as e:
    print(f'Error: {e}')
"
```
