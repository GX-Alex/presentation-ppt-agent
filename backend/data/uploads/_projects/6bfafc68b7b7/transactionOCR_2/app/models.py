"""
Pydantic 请求 / 响应模型
"""
from pydantic import BaseModel
from typing import List, Optional


# ── 上游请求体 ──

class OCRRequest(BaseModel):
    orderNO: str
    remoteUrls: List[str]
    custName: Optional[str] = ""
    companyName: Optional[str] = ""
    accountNo: Optional[str] = ""
    accountName: Optional[str] = ""


# ── 立即受理响应（202）：上游发完请求后拿到的应答 ──

class OCRAckResponse(BaseModel):
    orderNO: str
    message: str = "已受理，处理完成后将回调通知"


# ── 回调载荷：处理完成后 POST 到上游固定回调地址 ──

class OCRCallbackPayload(BaseModel):
    orderNO: str
    csvUrl: Optional[str] = None   # 服务内 CSV 下载路径，如 /downloads/{orderNO}.csv
    csvFile: Optional[str] = None  # base64 编码的 CSV 文件内容
    custName: Optional[str] = ""
    companyName: Optional[str] = ""
    accountNo: Optional[str] = ""
    accountName: Optional[str] = ""


# ── /ocr/upload 本地测试接口复用同一结构作响应 ──
OCRResponse = OCRCallbackPayload
