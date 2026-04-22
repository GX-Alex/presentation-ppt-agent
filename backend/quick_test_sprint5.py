"""
Sprint 5 验证测试 — 文件上传 + 文档解析 + URL 抓取 + 图片搜索。
运行: cd backend && python -m pytest quick_test_sprint5.py -v
或直接: cd backend && python quick_test_sprint5.py
"""
import asyncio
import importlib
import io
import os
import sys
import tempfile
import zipfile

# ────────────── 测试结果跟踪 ──────────────
_passed = 0
_failed = 0
_errors: list[str] = []


def _ok(name: str):
    global _passed
    _passed += 1
    print(f"  ✅ {name}")


def _fail(name: str, reason: str):
    global _failed
    _failed += 1
    _errors.append(f"{name}: {reason}")
    print(f"  ❌ {name} — {reason}")


# ════════════════════════════════════════════════════
#  1. 文件服务: 安全校验
# ════════════════════════════════════════════════════
def test_file_service_validation():
    print("\n🔧 1. 文件服务 — 安全校验")
    from app.services.file_service import (
        validate_extension,
        validate_file_size,
        sanitize_filename,
        validate_zip_entry,
        FileValidationError,
        MAX_FILE_SIZE,
    )

    # 1a. 扩展名白名单 — 允许
    for ext in [".pdf", ".docx", ".py", ".zip", ".png"]:
        try:
            result = validate_extension(f"test{ext}")
            assert result == ext, f"期望 {ext}，得到 {result}"
            _ok(f"允许扩展名 {ext}")
        except Exception as e:
            _fail(f"允许扩展名 {ext}", str(e))

    # 1b. 扩展名白名单 — 拒绝
    for ext in [".exe", ".bat", ".dll", ".php", ".jsp"]:
        try:
            validate_extension(f"malware{ext}")
            _fail(f"拒绝扩展名 {ext}", "应该抛出 FileValidationError")
        except FileValidationError:
            _ok(f"拒绝扩展名 {ext}")
        except Exception as e:
            _fail(f"拒绝扩展名 {ext}", str(e))

    # 1c. 无扩展名拒绝
    try:
        validate_extension("noext")
        _fail("拒绝无扩展名", "应该抛出异常")
    except FileValidationError:
        _ok("拒绝无扩展名")

    # 1d. 文件大小 — 通过
    try:
        validate_file_size(1024 * 1024)  # 1MB
        _ok("大小校验通过 (1MB)")
    except Exception as e:
        _fail("大小校验通过 (1MB)", str(e))

    # 1e. 文件大小 — 拒绝
    try:
        validate_file_size(MAX_FILE_SIZE + 1)
        _fail("大小校验拒绝 (>50MB)", "应该抛出异常")
    except FileValidationError:
        _ok("大小校验拒绝 (>50MB)")

    # 1f. 文件名清理
    try:
        result = sanitize_filename("../../etc/passwd")
        assert ".." not in result, f"路径穿越未清理: {result}"
        assert "/" not in result, f"斜杠未清理: {result}"
        _ok(f"文件名清理路径穿越 → {result}")
    except Exception as e:
        _fail("文件名清理路径穿越", str(e))

    try:
        result = sanitize_filename(".hidden_file.txt")
        assert not result.startswith("."), f"前导点未移除: {result}"
        _ok(f"文件名清理隐藏文件 → {result}")
    except Exception as e:
        _fail("文件名清理隐藏文件", str(e))

    # 1g. Zip Slip 防护
    try:
        safe = validate_zip_entry("src/main.py", "/tmp/test_extract")
        assert safe, "合法路径应通过"
        _ok("Zip Slip: 合法路径通过")
    except Exception as e:
        _fail("Zip Slip: 合法路径通过", str(e))

    try:
        dangerous = validate_zip_entry("../../etc/passwd", "/tmp/test_extract")
        assert not dangerous, "穿越路径应该被拒绝"
        _ok("Zip Slip: 穿越路径拒绝")
    except Exception as e:
        _fail("Zip Slip: 穿越路径拒绝", str(e))


# ════════════════════════════════════════════════════
#  2. Zip 安全解压
# ════════════════════════════════════════════════════
def test_zip_extraction():
    print("\n📦 2. ZIP 安全解压")
    from app.services.file_service import extract_zip_safe, FileValidationError

    # 创建临时 ZIP 文件
    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "test.zip")
        extract_dir = os.path.join(tmpdir, "extracted")

        # 创建包含正常文件的 ZIP
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("README.md", "# Test Project\nHello World")
            zf.writestr("src/main.py", "print('hello')")

        try:
            files = asyncio.get_event_loop().run_until_complete(
                extract_zip_safe(zip_path, extract_dir)
            )
            assert len(files) == 2, f"期望 2 个文件，得到 {len(files)}"
            assert os.path.isfile(os.path.join(extract_dir, "README.md"))
            assert os.path.isfile(os.path.join(extract_dir, "src/main.py"))
            _ok(f"正常 ZIP 解压成功 ({len(files)} 文件)")
        except Exception as e:
            _fail("正常 ZIP 解压", str(e))


# ════════════════════════════════════════════════════
#  3. Tool 自动发现
# ════════════════════════════════════════════════════
def test_tool_discovery():
    print("\n🔍 3. Tool 自动发现")
    from app.core.tool_dispatch import auto_discover_tools, get_tool_names, get_tool_definitions

    auto_discover_tools()
    names = get_tool_names()
    definitions = get_tool_definitions()

    print(f"  已注册 Tool ({len(names)}): {names}")

    # 检查新增的 Sprint 5 Tool
    expected_tools = [
        "parse_document",
        "parse_project",
        "read_project_file",
        "fetch_url",
        "image_search",
    ]

    for tool_name in expected_tools:
        if tool_name in names:
            _ok(f"Tool 已注册: {tool_name}")
        else:
            _fail(f"Tool 已注册: {tool_name}", f"未找到，可用: {names}")

    # 检查定义格式
    for defn in definitions:
        func = defn.get("function", {})
        name = func.get("name", "?")
        if name in expected_tools:
            assert func.get("description"), f"{name} 缺少 description"
            assert func.get("parameters"), f"{name} 缺少 parameters"
            _ok(f"Tool 定义格式正确: {name}")


# ════════════════════════════════════════════════════
#  4. parse_document 模块导入
# ════════════════════════════════════════════════════
def test_parse_document_import():
    print("\n📄 4. parse_document 模块")
    try:
        from app.tools.parse_document import TOOL_DEFINITION, execute
        assert TOOL_DEFINITION["function"]["name"] == "parse_document"
        assert callable(execute)
        _ok("parse_document 导入成功")
    except Exception as e:
        _fail("parse_document 导入", str(e))

    # 测试纯文本解析
    try:
        from app.tools.parse_document import _parse_text
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("Hello World\n第二行\n第三行")
            f.flush()
            result = _parse_text(f.name)
            assert result["format"] == "text"
            assert "Hello World" in result["full_text"]
            assert result["line_count"] == 3
            _ok("TXT 解析正确")
            os.unlink(f.name)
    except Exception as e:
        _fail("TXT 解析", str(e))

    # 测试 CSV 解析
    try:
        from app.tools.parse_document import _parse_csv
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("name,age\nAlice,30\nBob,25")
            f.flush()
            result = _parse_csv(f.name)
            assert result["format"] == "csv"
            assert result["row_count"] == 3
            assert "Alice" in result["full_text"]
            _ok("CSV 解析正确")
            os.unlink(f.name)
    except Exception as e:
        _fail("CSV 解析", str(e))

    # 测试分块
    try:
        from app.tools.parse_document import _split_chunks
        text = "A" * 2000  # 2000 字符
        chunks = _split_chunks(text, chunk_size=800, overlap=100)
        assert len(chunks) >= 3, f"期望至少 3 块，得到 {len(chunks)}"
        _ok(f"文本分块: {len(chunks)} 块")
    except Exception as e:
        _fail("文本分块", str(e))


# ════════════════════════════════════════════════════
#  5. parse_project 模块导入
# ════════════════════════════════════════════════════
def test_parse_project_import():
    print("\n📁 5. parse_project 模块")
    try:
        from app.tools.parse_project import TOOL_DEFINITION, execute
        assert TOOL_DEFINITION["function"]["name"] == "parse_project"
        assert callable(execute)
        _ok("parse_project 导入成功")
    except Exception as e:
        _fail("parse_project 导入", str(e))

    # 测试文件树构建
    try:
        from app.tools.parse_project import _build_file_tree, _tree_to_text
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "src"))
            with open(os.path.join(tmpdir, "README.md"), 'w') as f:
                f.write("# Test")
            with open(os.path.join(tmpdir, "src/main.py"), 'w') as f:
                f.write("print('hello')")

            tree = _build_file_tree(tmpdir)
            assert tree["type"] == "dir"
            text = _tree_to_text(tree)
            assert "README.md" in text
            assert "main.py" in text
            _ok("文件树构建正确")
    except Exception as e:
        _fail("文件树构建", str(e))

    # 测试项目类型检测
    try:
        from app.tools.parse_project import _detect_project_type
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "requirements.txt"), 'w') as f:
                f.write("flask==2.0.0")
            types = _detect_project_type(tmpdir)
            assert "python" in types, f"期望 python，得到 {types}"
            _ok(f"项目类型检测: {types}")
    except Exception as e:
        _fail("项目类型检测", str(e))


# ════════════════════════════════════════════════════
#  6. read_project_file 模块导入
# ════════════════════════════════════════════════════
def test_read_project_file_import():
    print("\n📖 6. read_project_file 模块")
    try:
        from app.tools.read_project_file import TOOL_DEFINITION, execute
        assert TOOL_DEFINITION["function"]["name"] == "read_project_file"
        assert callable(execute)
        _ok("read_project_file 导入成功")
    except Exception as e:
        _fail("read_project_file 导入", str(e))

    # 测试语言检测
    try:
        from app.tools.read_project_file import _detect_language
        assert _detect_language(".py") == "python"
        assert _detect_language(".ts") == "typescript"
        assert _detect_language(".json") == "json"
        _ok("语言检测正确")
    except Exception as e:
        _fail("语言检测", str(e))


# ════════════════════════════════════════════════════
#  7. fetch_url + SSRF 防护
# ════════════════════════════════════════════════════
def test_fetch_url_ssrf():
    print("\n🌐 7. fetch_url — SSRF 防护")
    from app.tools.fetch_url import check_ssrf, SSRFError, TOOL_DEFINITION

    assert TOOL_DEFINITION["function"]["name"] == "fetch_url"
    _ok("fetch_url 导入成功")

    # 合法 URL 应通过
    try:
        check_ssrf("https://www.example.com")
        _ok("SSRF: 合法 URL 通过")
    except SSRFError:
        _fail("SSRF: 合法 URL 通过", "不应被拦截")
    except Exception as e:
        # DNS 解析可能失败（无网络），这不是 SSRF 错误
        _fail("SSRF: 合法 URL 通过", f"异常: {e}")

    # 私有 IP 应被拒绝
    ssrf_urls = [
        ("http://127.0.0.1:8080/admin", "回环地址"),
        ("http://localhost/secret", "localhost"),
        ("http://169.254.169.254/metadata", "元数据服务"),
        ("ftp://example.com/file", "非 HTTP 协议"),
    ]

    for url, desc in ssrf_urls:
        try:
            check_ssrf(url)
            _fail(f"SSRF 拦截: {desc}", "应该被拦截")
        except SSRFError:
            _ok(f"SSRF 拦截: {desc}")
        except Exception as e:
            _fail(f"SSRF 拦截: {desc}", str(e))


# ════════════════════════════════════════════════════
#  8. image_search 模块导入
# ════════════════════════════════════════════════════
def test_image_search_import():
    print("\n🖼️ 8. image_search 模块")
    try:
        from app.tools.image_search import TOOL_DEFINITION, execute
        assert TOOL_DEFINITION["function"]["name"] == "image_search"
        assert callable(execute)
        _ok("image_search 导入成功")
    except Exception as e:
        _fail("image_search 导入", str(e))

    # 无 API Key 时应返回错误提示
    import app.tools.image_search as img_mod
    original_key = img_mod.PEXELS_API_KEY
    img_mod.PEXELS_API_KEY = ""
    try:
        result = asyncio.get_event_loop().run_until_complete(
            img_mod.execute({"query": "test"})
        )
        assert "error" in result, "无 API Key 应返回错误"
        assert "PEXELS_API_KEY" in result["error"]
        _ok("无 API Key 错误提示正确")
    except Exception as e:
        _fail("无 API Key 处理", str(e))
    finally:
        img_mod.PEXELS_API_KEY = original_key


# ════════════════════════════════════════════════════
#  9. Files API 路由检查
# ════════════════════════════════════════════════════
def test_files_api_routes():
    print("\n🛣️ 9. Files API 路由")
    try:
        from app.api.files import router
        routes = [r.path for r in router.routes]
        has_upload = any("upload" in r for r in routes)
        assert has_upload, f"缺少 upload 路由，有: {routes}"
        _ok(f"Files API 路由: {routes}")
    except Exception as e:
        _fail("Files API 路由", str(e))


# ════════════════════════════════════════════════════
#  10. 依赖检查
# ════════════════════════════════════════════════════
def test_dependencies():
    print("\n📦 10. Sprint 5 依赖检查")
    deps = {
        "fitz": "PyMuPDF",
        "docx": "python-docx",
        "pptx": "python-pptx",
        "openpyxl": "openpyxl",
        "trafilatura": "trafilatura",
        "httpx": "httpx",
    }
    for module_name, pkg_name in deps.items():
        try:
            importlib.import_module(module_name)
            _ok(f"依赖可用: {pkg_name}")
        except ImportError:
            _fail(f"依赖可用: {pkg_name}", f"import {module_name} 失败，请 pip install {pkg_name}")


# ════════════════════════════════════════════════════
#  主入口
# ════════════════════════════════════════════════════
def main():
    print("=" * 60)
    print("  Sprint 5 验证测试: 文件上传与解析 + 搜索")
    print("=" * 60)

    test_dependencies()
    test_file_service_validation()
    test_zip_extraction()
    test_tool_discovery()
    test_parse_document_import()
    test_parse_project_import()
    test_read_project_file_import()
    test_fetch_url_ssrf()
    test_image_search_import()
    test_files_api_routes()

    print("\n" + "=" * 60)
    print(f"  结果: ✅ {_passed} 通过  ❌ {_failed} 失败")
    if _errors:
        print("\n  失败详情:")
        for err in _errors:
            print(f"    • {err}")
    print("=" * 60)

    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
