"""
PDF转图片服务 + 银行流水字段映射服务 - 基于FastAPI
"""
import fitz
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import base64
import logging
import pandas as pd
import io
from datetime import datetime
from PIL import Image

from transaction_mapper import (
    process_transaction_data,
    df_to_csv_bytes,
    TARGET_FIELDS
)

# 配置日志（带时间戳）
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.DEBUG, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="PDF转图片 + 银行流水字段映射服务",
    description="PDF转图片服务和银行流水字段映射服务的组合",
    default_response_class=JSONResponse
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常处理器"""
    logger.exception(f"未捕获的异常: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)}
    )


def pdf_to_images(file_bytes: bytes, zoom: float = 2.0, quality: int = 85, max_width: int = 2000) -> List[bytes]:
    """
    将PDF转换为图片字节列表（带压缩）

    Args:
        file_bytes: PDF文件的字节数据
        zoom: 缩放因子，值越大图片越清晰(默认2.0)
        quality: JPEG质量 (1-100)，默认85
        max_width: 最大宽度，超过则等比压缩，默认2000

    Returns:
        List[bytes]: 每页图片的JPEG字节列表
    """
    images = []

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)

            # 计算缩放后的尺寸
            mat = fitz.Matrix(zoom, zoom)

            # 渲染页面为图片
            pix = page.get_pixmap(matrix=mat)

            # 转换为PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            # 宽度超过限制时等比压缩
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

            # 压缩图片
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=quality, optimize=True)
            img_bytes = output.getvalue()

            logger.info(f"页面 {page_num + 1}: 原始 {pix.width}x{pix.height}, 压缩后 {img.width}x{img.height}, 大小 {len(img_bytes)} bytes")

            images.append(img_bytes)

        doc.close()
    except Exception as e:
        raise ValueError(f"PDF处理失败: {str(e)}")

    return images


@app.post("/convert")
async def convert_pdf_to_images(
    files: List[UploadFile] = File(...),
    zoom: float = 2.0,
    quality: int = Form(85, description="图片质量 1-100"),
    max_width: int = Form(2000, description="最大宽度")
):
    """
    上传PDF文件数组，转换为图片数组返回（支持压缩）

    - **files**: PDF文件数组
    - **zoom**: 缩放因子（默认2.0）
    - **quality**: JPEG质量 1-100（默认85）
    - **max_width**: 最大宽度（默认2000px）
    """
    if not files or all(f.filename == '' for f in files):
        raise HTTPException(status_code=400, detail="没有收到文件")

    all_images = []
    file_results = []

    for file in files:
        if file.filename == '':
            continue

        logger.info(f"收到文件: {file.filename}")

        # 验证文件类型
        if not file.filename.lower().endswith('.pdf'):
            logger.warning(f"文件类型不支持: {file.filename}")
            continue

        try:
            # 读取文件内容
            file_bytes = await file.read()
            logger.info(f"文件大小: {len(file_bytes)} bytes")

            if len(file_bytes) == 0:
                logger.warning(f"文件为空: {file.filename}")
                continue

            # 限制文件大小 (100MB)
            if len(file_bytes) > 100 * 1024 * 1024:
                logger.warning(f"文件过大: {file.filename}")
                continue

            # 转换为图片（带压缩）
            images = pdf_to_images(file_bytes, zoom=zoom, quality=quality, max_width=max_width)
            logger.info(f"成功转换 {file.filename}: {len(images)} 页")

            # 编码图片
            encoded_images = [base64.b64encode(img).decode('latin-1') for img in images]

            file_results.append({
                "filename": file.filename,
                "page_count": len(images),
                "images": encoded_images
            })

            all_images.extend(encoded_images)

        except ValueError as e:
            logger.error(f"PDF处理错误: {e}")
            continue
        except Exception as e:
            logger.exception(f"服务器错误: {e}")
            continue

    if not file_results:
        raise HTTPException(status_code=400, detail="没有有效的PDF文件")

    # 返回 Array[file] 格式
    return file_results


@app.post("/convert/zip")
async def convert_pdf_to_zip(
    files: List[UploadFile] = File(...),
    zoom: float = 2.0,
    quality: int = Form(85, description="图片质量 1-100"),
    max_width: int = Form(2000, description="最大宽度")
):
    """
    上传PDF文件，返回包含所有图片的 ZIP 压缩包
    """
    import zipfile
    
    if not files or all(f.filename == '' for f in files):
        raise HTTPException(status_code=400, detail="没有收到文件")

    all_images = []
    
    for file in files:
        if file.filename == '' or not file.filename.lower().endswith('.pdf'):
            continue

        try:
            file_bytes = await file.read()
            if len(file_bytes) == 0 or len(file_bytes) > 100 * 1024 * 1024:
                continue

            images = pdf_to_images(file_bytes, zoom=zoom, quality=quality, max_width=max_width)
            
            # 保存文件名和图片数据
            base_name = file.filename.rsplit('.', 1)[0]
            for i, img in enumerate(images):
                all_images.append((f"{base_name}_page_{i+1}.jpg", img))

        except Exception as e:
            logger.exception(f"PDF处理错误: {e}")
            continue

    if not all_images:
        raise HTTPException(status_code=400, detail="没有有效的PDF文件")

    # 创建 ZIP 文件
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for filename, img_bytes in all_images:
            zip_file.writestr(filename, img_bytes)
    
    zip_buffer.seek(0)
    
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=pdf_images.zip",
            "X-Total-Images": str(len(all_images))
        }
    )


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}


@app.post("/convert/multipart")
async def convert_pdf_to_multipart(
    files: List[UploadFile] = File(...),
    zoom: float = 2.0,
    quality: int = Form(85),
    max_width: int = Form(2000)
):
    """
    上传PDF文件，返回 multipart/mixed 格式的多个图片文件
    测试 Dify 是否能解析为 Array[File]
    """
    from starlette.responses import Response
    import uuid
    
    if not files or all(f.filename == '' for f in files):
        raise HTTPException(status_code=400, detail="没有收到文件")

    all_images = []
    
    for file in files:
        if file.filename == '' or not file.filename.lower().endswith('.pdf'):
            continue

        try:
            file_bytes = await file.read()
            if len(file_bytes) == 0 or len(file_bytes) > 100 * 1024 * 1024:
                continue

            images = pdf_to_images(file_bytes, zoom=zoom, quality=quality, max_width=max_width)
            base_name = file.filename.rsplit('.', 1)[0]
            for i, img in enumerate(images):
                all_images.append((f"{base_name}_page_{i+1}.jpg", img))

        except Exception as e:
            logger.exception(f"PDF处理错误: {e}")
            continue

    if not all_images:
        raise HTTPException(status_code=400, detail="没有有效的PDF文件")

    # 构建 multipart/mixed 响应
    boundary = f"----Boundary{uuid.uuid4().hex}"
    
    body_parts = []
    for filename, img_bytes in all_images:
        part = (
            f"--{boundary}\r\n"
            f"Content-Type: image/jpeg\r\n"
            f"Content-Disposition: attachment; filename=\"{filename}\"\r\n"
            f"\r\n"
        ).encode('utf-8') + img_bytes + b"\r\n"
        body_parts.append(part)
    
    body_parts.append(f"--{boundary}--\r\n".encode('utf-8'))
    body = b"".join(body_parts)
    
    return Response(
        content=body,
        media_type=f"multipart/mixed; boundary={boundary}",
        headers={
            "X-Total-Files": str(len(all_images))
        }
    )


@app.post("/convert/files")
async def convert_pdf_to_files(
    files: List[UploadFile] = File(...),
    zoom: float = 2.0,
    quality: int = Form(85, description="图片质量 1-100"),
    max_width: int = Form(2000, description="最大宽度")
):
    """
    上传PDF文件，返回图片文件流（供 Dify files 变量使用）
    返回 multipart/mixed 格式，每个 part 是一张图片
    """
    from starlette.responses import Response
    import uuid
    
    if not files or all(f.filename == '' for f in files):
        raise HTTPException(status_code=400, detail="没有收到文件")

    all_images = []

    for file in files:
        if file.filename == '' or not file.filename.lower().endswith('.pdf'):
            continue

        try:
            file_bytes = await file.read()
            if len(file_bytes) == 0 or len(file_bytes) > 100 * 1024 * 1024:
                continue

            images = pdf_to_images(file_bytes, zoom=zoom, quality=quality, max_width=max_width)
            all_images.extend(images)

        except Exception as e:
            logger.exception(f"PDF处理错误: {e}")
            continue

    if not all_images:
        raise HTTPException(status_code=400, detail="没有有效的PDF文件")

    # 返回第一张图片作为文件（单文件模式）
    # Dify HTTP 节点更容易处理单文件响应
    return Response(
        content=all_images[0],
        media_type="image/jpeg",
        headers={
            "Content-Disposition": f"attachment; filename=page_1.jpg",
            "X-Total-Pages": str(len(all_images))
        }
    )


@app.post("/convert/image/{page}")
async def convert_pdf_to_single_image(
    page: int,
    files: List[UploadFile] = File(...),
    zoom: float = 2.0,
    quality: int = Form(85),
    max_width: int = Form(2000)
):
    """
    上传PDF文件，返回指定页码的图片
    
    - **page**: 页码（从1开始）
    """
    from starlette.responses import Response
    
    if not files or all(f.filename == '' for f in files):
        raise HTTPException(status_code=400, detail="没有收到文件")

    all_images = []

    for file in files:
        if file.filename == '' or not file.filename.lower().endswith('.pdf'):
            continue

        try:
            file_bytes = await file.read()
            if len(file_bytes) == 0 or len(file_bytes) > 100 * 1024 * 1024:
                continue

            images = pdf_to_images(file_bytes, zoom=zoom, quality=quality, max_width=max_width)
            all_images.extend(images)

        except Exception as e:
            logger.exception(f"PDF处理错误: {e}")
            continue

    if not all_images:
        raise HTTPException(status_code=400, detail="没有有效的PDF文件")

    if page < 1 or page > len(all_images):
        raise HTTPException(status_code=400, detail=f"页码超出范围，总共 {len(all_images)} 页")

    return Response(
        content=all_images[page - 1],
        media_type="image/jpeg",
        headers={
            "Content-Disposition": f"attachment; filename=page_{page}.jpg",
            "X-Total-Pages": str(len(all_images)),
            "X-Current-Page": str(page)
        }
    )


@app.post("/convert/info")
async def get_pdf_info(
    files: List[UploadFile] = File(...)
):
    """
    获取PDF页数信息（不返回图片，用于确定迭代次数）
    """
    if not files or all(f.filename == '' for f in files):
        raise HTTPException(status_code=400, detail="没有收到文件")

    total_pages = 0
    file_info = []

    for file in files:
        if file.filename == '' or not file.filename.lower().endswith('.pdf'):
            continue

        try:
            file_bytes = await file.read()
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            pages = len(doc)
            doc.close()
            
            file_info.append({
                "filename": file.filename,
                "pages": pages
            })
            total_pages += pages

        except Exception as e:
            logger.exception(f"PDF处理错误: {e}")
            continue

    return {
        "total_pages": total_pages,
        "files": file_info
    }


# ==================== 银行流水字段映射服务 ====================

@app.get("/")
async def root():
    """服务健康检查"""
    return {
        "status": "ok",
        "service": "银行流水字段映射服务",
        "version": "1.0.0",
        "target_fields": list(TARGET_FIELDS.keys())
    }


@app.get("/fields")
async def get_target_fields():
    """获取目标字段列表"""
    return {
        "target_fields": TARGET_FIELDS,
        "description": {
            "id": "主键ID",
            "name": "户名",
            "account_id": "账户号",
            "trans_date": "交易日期",
            "trans_time": "交易时间",
            "opponent_name": "对方户名",
            "debit_credit": "借贷标志",
            "trans_amt": "交易金额",
            "account_balance": "账户余额",
            "currency": "币种",
            "opponent_account_no": "对方账户",
            "opponent_account_bank": "对方开户行",
            "account_bank": "账户所属机构",
            "trans_channel": "交易渠道",
            "trans_type": "交易类型",
            "trans_use": "交易用途",
            "abstract": "摘要",
            "remark": "备注/附言",
            "verif_label": "验证结果",
            "rel_line_num": "行号",
            "create_time": "创建时间",
            "update_time": "更新时间",
        }
    }


@app.post("/map")
async def map_transaction_csv(
    file: UploadFile = File(..., description="CSV文件"),
    account_name: Optional[str] = Form(None, description="账户名，用于填充"),
    account_id: Optional[str] = Form(None, description="账户号，用于填充"),
    account_bank: Optional[str] = Form(None, description="账户所属机构，用于填充"),
    serial_id: Optional[str] = Form(None, description="交易流水号，用于填充"),
):
    """
    上传CSV文件并映射字段

    - **file**: CSV文件
    - **account_name**: 账户名（可选）
    - **account_id**: 账户号（可选）
    - **account_bank**: 账户所属机构（可选）
    - **serial_id**: 交易流水号（可选）
    """
    try:
        # 读取文件内容
        content = await file.read()

        if not content:
            raise HTTPException(status_code=400, detail="文件内容为空")

        # 处理数据
        df = process_transaction_data(content, account_name, account_id, account_bank, serial_id)

        # 生成CSV响应
        csv_bytes = df_to_csv_bytes(df)

        # 构建文件名
        filename = f"mapped_transactions_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv"

        return StreamingResponse(
            iter([csv_bytes]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": "text/csv; charset=utf-8-sig"
            }
        )

    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400, detail="CSV文件为空或格式错误")
    except Exception as e:
        logger.exception(f"处理失败: {e}")
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@app.post("/map/json")
async def map_transaction_csv_json(
    file: UploadFile = File(..., description="CSV文件"),
    account_name: Optional[str] = Form(None, description="账户名，用于填充"),
    account_id: Optional[str] = Form(None, description="账户号，用于填充"),
    account_bank: Optional[str] = Form(None, description="账户所属机构，用于填充"),
    serial_id: Optional[str] = Form(None, description="交易流水号，用于填充"),
):
    """
    上传CSV文件并映射字段，返回JSON格式预览

    - **file**: CSV文件
    - **account_name**: 账户名（可选）
    - **account_id**: 账户号（可选）
    - **account_bank**: 账户所属机构（可选）
    - **serial_id**: 交易流水号（可选）
    """
    try:
        # 读取文件内容
        content = await file.read()

        if not content:
            raise HTTPException(status_code=400, detail="文件内容为空")

        # 处理数据
        df = process_transaction_data(content, account_name, account_id, account_bank, serial_id)

        # 返回JSON格式（限制100条）
        return {
            "status": "success",
            "total_rows": len(df),
            "fields": list(df.columns),
            "data": df.head(100).to_dict(orient="records")
        }

    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400, detail="CSV文件为空或格式错误")
    except Exception as e:
        logger.exception(f"处理失败: {e}")
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@app.post("/map/info")
async def get_mapping_info(
    file: UploadFile = File(..., description="CSV文件"),
):
    """
    分析CSV文件字段并返回映射信息

    - **file**: CSV文件
    """
    try:
        # 读取文件内容
        content = await file.read()

        if not content:
            raise HTTPException(status_code=400, detail="文件内容为空")

        # 读取CSV获取原始字段
        try:
            df = pd.read_csv(io.BytesIO(content), encoding='utf-8')
        except UnicodeDecodeError:
            df = pd.read_csv(io.BytesIO(content), encoding='gbk')

        original_columns = list(df.columns)
        mapped_columns = []

        from transaction_mapper import normalize_field_name, FIELD_MAPPING

        for col in original_columns:
            normalized = normalize_field_name(col)
            mapped = None

            if normalized in FIELD_MAPPING:
                mapped = FIELD_MAPPING[normalized]
            else:
                for key in FIELD_MAPPING:
                    if key in normalized or normalized in key:
                        mapped = FIELD_MAPPING[key]
                        break

            mapped_columns.append({
                "original": col,
                "mapped_to": mapped if mapped else col,
                "status": "mapped" if mapped else "unchanged"
            })

        return {
            "status": "success",
            "original_fields": original_columns,
            "mapping_result": mapped_columns,
            "target_fields": list(TARGET_FIELDS.keys())
        }

    except Exception as e:
        logger.exception(f"分析失败: {e}")
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
