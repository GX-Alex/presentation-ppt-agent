"""
PDF 解析流水线模块

本模块实现银行流水 PDF/图片的解析流程：
1. pdf_detector: 检测 PDF 类型（文本型/扫描型）
2. pdf_to_image: 将 PDF 页面转换为图片
3. vl_recognizer: 使用视觉大模型识别图片中的表格内容（含余额连续性校验）
4. ensure_balance_ok: 对模型未输出 is_balance_ok 的记录做兜底处理
"""
