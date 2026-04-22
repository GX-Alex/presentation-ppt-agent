"""run_code — 在隔离临时目录执行代码脚本，支持 Node.js / Python / Shell。

使用场景:
  1. 执行 PptxGenJS 脚本生成 .pptx 文件
  2. 运行 Python 数据处理脚本产出文件
  3. 执行 Shell 命令

输出文件自动保存到 /static/run_code/{exec_id}/ 并返回可访问的 URL。
"""
import asyncio
import logging
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
# /static/ URL 映射到 backend/data/ 目录
STATIC_RUN_CODE_DIR = BACKEND_ROOT / "data" / "run_code"

# 脚本执行超时（秒）
EXEC_TIMEOUT = 90
# npm install 超时（秒）
NPM_INSTALL_TIMEOUT = 120

# ──────────────── Tool 定义 ────────────────

TOOL_DEFINITION: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "run_code",
        "description": (
            "在隔离的临时目录中执行代码脚本，支持 Node.js / Python / Shell。\n"
            "执行完成后自动收集生成的文件（.pptx/.pdf/.png/.html/.docx 等）并返回可访问的 URL。\n\n"
            "常见用途:\n"
            "- 生成 .pptx 文件: language=node, 代码中 require('pptxgenjs') 会自动安装依赖\n"
            "- Python 脚本处理数据: language=python\n"
            "- Shell 命令: language=shell\n\n"
            "重要事项:\n"
            "- 生成的文件【必须】用相对路径保存到当前目录，例如: pres.writeFile('output.pptx') 或 prs.save('result.pptx')\n"
            "- pptxgenjs 的 writeFile 是异步方法，必须 await: await pres.writeFile('output.pptx')\n"
            "- 脚本在临时沙箱中运行，不能访问系统其它路径\n"
        ),
        "parameters": {
            "type": "object",
            "required": ["code", "language"],
            "properties": {
                "code": {
                    "type": "string",
                    "description": "要执行的完整脚本代码",
                },
                "language": {
                    "type": "string",
                    "enum": ["node", "python", "shell"],
                    "description": "脚本语言: node(Node.js), python(Python 3), shell(bash)",
                },
                "extra_files": {
                    "type": "object",
                    "description": (
                        "额外写入临时目录的文件，格式: {文件名: 文件内容字符串}。"
                        "适合传入 JSON 数据文件等依赖文件。"
                    ),
                    "additionalProperties": {"type": "string"},
                },
                "collect_extensions": {
                    "type": "array",
                    "description": (
                        "要收集的输出文件扩展名列表（含点号），"
                        "默认: ['.pptx', '.pdf', '.png', '.html', '.docx', '.xlsx', '.svg']"
                    ),
                    "items": {"type": "string"},
                },
            },
        },
    },
}

TOOL_RUNTIME_METADATA: dict[str, Any] = {
    "expose_to_llm": True,
    "status": "stable",
}

# ──────────────── 主执行函数 ────────────────


async def execute(params: dict[str, Any]) -> dict[str, Any]:
    """执行代码脚本并收集输出文件。"""
    code: str = (params.get("code") or "").strip()
    language: str = (params.get("language") or "node").strip()
    extra_files: dict[str, str] = params.get("extra_files") or {}
    collect_extensions: list[str] = params.get("collect_extensions") or [
        ".pptx", ".pdf", ".png", ".html", ".docx", ".xlsx", ".svg", ".txt",
    ]

    if not code:
        return {"error": "code 参数不能为空"}
    if language not in ("node", "python", "shell"):
        return {"error": f"不支持的语言: {language}，请使用 node / python / shell"}

    exec_id = uuid.uuid4().hex[:12]

    with tempfile.TemporaryDirectory(prefix=f"run_code_{exec_id}_") as tmpdir:
        tmppath = Path(tmpdir)

        # 写入额外依赖文件（路径安全检查：只允许文件名，不允许目录层级）
        for fname, fcontent in extra_files.items():
            safe_name = Path(fname).name
            if not safe_name:
                continue
            (tmppath / safe_name).write_text(fcontent, encoding="utf-8")

        # 根据语言构建执行命令
        if language == "node":
            result = await _run_node(code, tmppath, exec_id)
        elif language == "python":
            result = await _run_python(code, tmppath)
        else:
            result = await _run_shell(code, tmppath)

        if "error" in result and result.get("_fatal"):
            return result

        # 收集输出文件并持久化到 static 目录
        saved_files = await _collect_and_save(tmppath, exec_id, collect_extensions)

        result["output_files"] = saved_files
        result["exec_id"] = exec_id
        result.pop("_fatal", None)
        return result


# ──────────────── Node.js 执行 ────────────────


async def _run_node(code: str, tmppath: Path, exec_id: str) -> dict[str, Any]:
    script_file = tmppath / "main.js"
    script_file.write_text(code, encoding="utf-8")

    # 检测是否需要 pptxgenjs 或其它 npm 依赖
    needs_npm = "require(" in code and any(
        lib in code for lib in ["pptxgenjs", "pptx", "exceljs", "puppeteer", "jsdom"]
    )
    if needs_npm:
        pkg_content = _infer_package_json(code)
        (tmppath / "package.json").write_text(pkg_content, encoding="utf-8")
        install = await _run_process(
            ["npm", "install", "--no-audit", "--no-fund", "--prefer-offline"],
            cwd=str(tmppath),
            timeout=NPM_INSTALL_TIMEOUT,
        )
        if install["returncode"] != 0:
            return {
                "error": f"npm install 失败（exit {install['returncode']}）: {install['stderr'][:400]}",
                "stdout": install["stdout"][:200],
                "success": False,
                "_fatal": True,
            }
        logger.info(f"[run_code] npm install 完成: exec_id={exec_id}")

    # Auto-wrap in async IIFE if code uses async operations (pptxgenjs etc.)
    # but is not already wrapped in an async function/IIFE
    ASYNC_LIBS = {"pptxgenjs", "puppeteer", "exceljs"}
    needs_async_wrap = (
        any(lib in code for lib in ASYNC_LIBS)
        and not re.search(r'\basync\s*(function|\(|=>)', code[:500])
    )
    if needs_async_wrap:
        wrapped = f"(async () => {{\n{code}\n}})().catch(e => {{ console.error('Error:', e); process.exit(1); }});"
        script_file.write_text(wrapped, encoding="utf-8")

    run = await _run_process(["node", str(script_file)], cwd=str(tmppath), timeout=EXEC_TIMEOUT)
    return _format_result(run)


def _infer_package_json(code: str) -> str:
    """根据代码中的 require() 推断依赖并生成 package.json。"""
    import json
    import re

    deps: dict[str, str] = {}
    KNOWN_VERSIONS = {
        "pptxgenjs": "^3.12.0",
        "exceljs": "^4.3.0",
        "puppeteer": "^21.0.0",
        "jsdom": "^24.0.0",
        "axios": "^1.6.0",
        "lodash": "^4.17.21",
    }
    for match in re.finditer(r"""require\(['"]([^'"./][^'"]*)['"]\)""", code):
        pkg = match.group(1).split("/")[0]  # handle scoped packages & subpaths
        if pkg and not pkg.startswith("@types/"):
            deps[pkg] = KNOWN_VERSIONS.get(pkg, "latest")

    return json.dumps({"name": "run_code_exec", "dependencies": deps}, indent=2)


# ──────────────── Python 执行 ────────────────


async def _run_python(code: str, tmppath: Path) -> dict[str, Any]:
    script_file = tmppath / "main.py"
    script_file.write_text(code, encoding="utf-8")
    run = await _run_process(["python3", str(script_file)], cwd=str(tmppath), timeout=EXEC_TIMEOUT)
    return _format_result(run)


# ──────────────── Shell 执行 ────────────────


async def _run_shell(code: str, tmppath: Path) -> dict[str, Any]:
    script_file = tmppath / "main.sh"
    script_file.write_text(code, encoding="utf-8")
    script_file.chmod(0o755)
    run = await _run_process(["bash", str(script_file)], cwd=str(tmppath), timeout=EXEC_TIMEOUT)
    return _format_result(run)


# ──────────────── 工具函数 ────────────────


async def _run_process(cmd: list[str], cwd: str, timeout: float) -> dict[str, Any]:
    """创建子进程执行命令并捕获输出。"""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # 不继承 PATH 可能导致 node/python 找不到，保留 env 但限制 HOME
            env={**os.environ, "HOME": cwd, "TMPDIR": cwd},
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {"returncode": -1, "stdout": "", "stderr": f"执行超时（>{timeout}s）"}

        return {
            "returncode": proc.returncode or 0,
            "stdout": stdout_b.decode("utf-8", errors="replace"),
            "stderr": stderr_b.decode("utf-8", errors="replace"),
        }
    except FileNotFoundError as exc:
        return {"returncode": -1, "stdout": "", "stderr": f"命令未找到: {exc}"}
    except Exception as exc:
        return {"returncode": -1, "stdout": "", "stderr": str(exc)}


def _format_result(run: dict[str, Any]) -> dict[str, Any]:
    success = run["returncode"] == 0
    result: dict[str, Any] = {
        "success": success,
        "returncode": run["returncode"],
        "stdout": run["stdout"][:4000],
        "stderr": run["stderr"][:500] if success else run["stderr"][:1000],
    }
    if not success:
        result["error"] = f"脚本执行失败 (exit {run['returncode']}): {run['stderr'][:300]}"
    return result


async def _collect_and_save(
    tmppath: Path,
    exec_id: str,
    collect_extensions: list[str],
) -> list[dict[str, Any]]:
    """将生成的输出文件复制到 static 目录并返回 URL 列表。"""
    ext_set = {e.lower() for e in collect_extensions}
    output_files = [
        f for f in tmppath.rglob("*")
        if f.is_file() and f.suffix.lower() in ext_set
        # 排除 node_modules 和临时脚本自身
        and "node_modules" not in f.parts
        and f.name not in ("main.js", "main.py", "main.sh", "package.json", "package-lock.json")
    ]

    if not output_files:
        return []

    out_dir = STATIC_RUN_CODE_DIR / exec_id
    out_dir.mkdir(parents=True, exist_ok=True)

    saved: list[dict[str, Any]] = []
    for f in output_files:
        dest = out_dir / f.name
        shutil.copy2(f, dest)
        saved.append({
            "filename": f.name,
            "url": f"/static/run_code/{exec_id}/{f.name}",
            "size_bytes": f.stat().st_size,
        })
        logger.info(f"[run_code] 保存输出文件: {f.name} ({f.stat().st_size} bytes)")

    return saved
