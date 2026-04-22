"""
银行流水字段映射服务
将多模态模型提取的CSV字段映射到标准流水表字段
"""
import pandas as pd
from typing import Optional, Dict, List
from datetime import datetime
import io
import re


# 目标字段（流水表标准字段）
TARGET_FIELDS = {
    "id": "id",
    "serial_id": "serial_id",         # 交易流水号
    "name": "name",                    # 户名
    "account_id": "account_id",        # 账户号（上游传参 accountNo 固定填充）
    "account_no": "account_no",        # 账户号（LLM 提取原始值）
    "account_bank": "account_bank",    # 账户所属机构
    "trans_date": "trans_date",        # 交易日期
    "trans_time": "trans_time",        # 交易时间
    "opponent_name": "opponent_name",  # 对方户名
    "debit_credit": "debit_credit",  # 借贷标志
    "trans_amt": "trans_amt",          # 交易金额
    "account_balance": "account_balance",  # 账户余额
    "currency": "currency",            # 币种
    "opponent_account_no": "opponent_account_no",  # 对方账户
    "opponent_account_bank": "opponent_account_bank",  # 对方开户行
    "trans_channel": "trans_channel",  # 交易渠道
    "trans_type": "trans_type",        # 交易类型
    "trans_use": "trans_use",          # 交易用途
    "abstract": "abstract",            # 摘要
    "remark": "remark",                # 备注/附言
    "verif_label": "verif_label",      # 验证结果
    "rel_line_num": "rel_line_num",    # 行号
    "create_time": "create_time",      # 创建时间
    "update_time": "update_time",      # 更新时间
}


# 常见银行字段名映射（输入字段 -> 标准字段）
FIELD_MAPPING: Dict[str, str] = {
    # 户名/账户名
    "户名": "name",
    "账户名": "name",
    "户名称": "name",
    "客户名称": "name",
    "客户名": "name",
    "持卡人": "name",
    "账户姓名": "name",
    "name": "name",
    "username": "name",
    "user_name": "name",
    "account_name": "name",
    "account_holder": "name",
    "card_holder": "name",
    "holder_name": "name",
    "client_name": "name",

    # 账户号（LLM 提取原始值 → 映射到 account_no；account_id 由上游参数固定覆盖）
    "账号": "account_no",
    "卡号": "account_no",
    "账户号": "account_no",
    "账户号码": "account_no",
    "银行账号": "account_no",
    "account_no": "account_no",
    "account_no2": "account_no",
    "account_number": "account_no",
    "account": "account_no",
    "card_no": "account_no",
    "card_number": "account_no",
    "bank_account": "account_no",
    "bank_account_no": "account_no",

    # 账户所属机构
    "账户所属机构": "account_bank",
    "账户开户机构": "account_bank",
    "开户机构": "account_bank",
    "机构": "account_bank",
    "银行机构": "account_bank",
    "所属机构": "account_bank",
    "account_bank": "account_bank",
    "bank_name": "account_bank",
    "bank": "account_bank",
    "branch": "account_bank",
    "branch_name": "account_bank",

    # 交易日期
    "交易日期": "trans_date",
    "日期": "trans_date",
    "记账日期": "trans_date",
    "trans_date": "trans_date",
    "transaction_date": "trans_date",
    "txn_date": "trans_date",
    "post_date": "trans_date",
    "value_date": "trans_date",
    "date": "trans_date",

    # 交易时间
    "交易时间": "trans_time",
    "时间": "trans_time",
    "交易日期时间": "trans_time",
    "记账时间": "trans_time",
    "发生时间": "trans_time",
    "日期时间": "trans_time",
    "trans_time": "trans_time",
    "transaction_time": "trans_time",
    "txn_time": "trans_time",
    "datetime": "trans_time",
    "time": "trans_time",

    # 对方户名
    "对方户名": "opponent_name",
    "对方名称": "opponent_name",
    "对手名称": "opponent_name",
    "交易对手": "opponent_name",
    "对手信息": "opponent_name",
    "对方账户名": "opponent_name",
    "对方账户名称": "opponent_name",
    "对方": "opponent_name",
    "收款人": "opponent_name",
    "付款人": "opponent_name",
    "交易对象": "opponent_name",
    "counterparty_name": "opponent_name",
    "opponent": "opponent_name",
    "recipient": "opponent_name",
    "beneficiary": "opponent_name",
    "payee": "opponent_name",
    "payer": "opponent_name",
    "trans_target": "opponent_name",
    "target_name": "opponent_name",

    # 借贷标志
    "借贷标志": "debit_credit",
    "借贷方向": "debit_credit",
    "方向": "debit_credit",
    "借贷": "debit_credit",
    "借/贷": "debit_credit",
    "借方": "debit_credit",
    "贷方": "debit_credit",
    "debit_credit": "debit_credit",
    "dc_flag": "debit_credit",
    "dr_cr": "debit_credit",
    "side": "debit_credit",
    "direction": "debit_credit",
    "credit_debit": "debit_credit",
    "cr_dr": "debit_credit",

    # 收/支/其他 标识 -> 借贷标志映射
    "收/支": "debit_credit",
    "收入/支出": "debit_credit",
    "收入/支出/其他": "debit_credit",
   # "收": "debit_credit",
   # "支": "debit_credit",
    "income_expense": "debit_credit",
    "in_out": "debit_credit",

    # 交易金额
    "借方发生额": "trans_amt",
    "收入": "trans_amt",
    "支出": "trans_amt",
    "收入金额": "trans_amt",
    "收入/支出金额": "trans_amt",
    "贷方发生额": "trans_amt",
    "支出金额": "trans_amt",
    "交易金额": "trans_amt",
    "金额": "trans_amt",
    "发生金额": "trans_amt",
    "发生额": "trans_amt",
    "金额(元)": "trans_amt",
    "trans_amt": "trans_amt",
    "amount": "trans_amt",
    "amt": "trans_amt",
    "transaction_amount": "trans_amt",
    "txn_amt": "trans_amt",
    "sum": "trans_amt",

    # 账户余额
    "余额": "account_balance",
    "账户余额": "account_balance",
    "可用余额": "account_balance",
    "当前余额": "account_balance",
    "balance": "account_balance",
    "account_balance": "account_balance",
    "closing_balance": "account_balance",
    "end_balance": "account_balance",
    "avail_balance": "account_balance",

    # 币种
    "币种": "currency",
    "币别": "currency",
    "currency": "currency",

    # 对方账户
    "对方账号": "opponent_account_no",
    "对手账号": "opponent_account_no",
    "对方账户": "opponent_account_no",
    "对手账户": "opponent_account_no",
    "交易对手账号": "opponent_account_no",
    "对手卡号": "opponent_account_no",
    "对方户名/账号": "opponent_account_no",
    "对方卡号": "opponent_account_no",
    "对方账户号": "opponent_account_no",
    "对方账户号码": "opponent_account_no",
    "交易账号": "opponent_account_no",
    "counterparty_account": "opponent_account_no",
    "opp_account_no": "opponent_account_no",
    "recipient_account": "opponent_account_no",
    "beneficiary_account": "opponent_account_no",
    "payee_account": "opponent_account_no",
    "opponent_account": "opponent_account_no",

    # 对方开户行
    "对方开户行": "opponent_account_bank",
    "对手开户行": "opponent_account_bank",
    "开户行": "opponent_account_bank",
    "对方行名": "opponent_account_bank",
    "对方银行": "opponent_account_bank",
    "交易行名": "opponent_account_bank",
    "counterparty_bank": "opponent_account_bank",
    "opp_bank": "opponent_account_bank",
    "recipient_bank": "opponent_account_bank",
    "bank_name": "opponent_account_bank",
    "trans_bank": "opponent_account_bank",

    # 交易渠道
    "交易渠道": "trans_channel",
    "渠道": "trans_channel",
    "渠道类型": "trans_channel",
    "channel": "trans_channel",
    "trans_channel": "trans_channel",
    "channel_type": "trans_channel",
    "device_channel": "trans_channel",

    # 交易类型
    "交易类型": "trans_type",
    "类型": "trans_type",
    "业务类型": "trans_type",
    "交易性质": "trans_type",
    "trans_type": "trans_type",
    "transaction_type": "trans_type",
    "txn_type": "trans_type",
    "type": "trans_type",
    "业务类别": "trans_type",

    # 交易用途
    "用途": "trans_use",
    "交易用途": "trans_use",
    "用途说明": "trans_use",
    "trans_use": "trans_use",
    "purpose": "trans_use",
    "usage": "trans_use",

    # 摘要
    "摘要": "abstract",
    "交易摘要": "abstract",
    "业务摘要": "abstract",
    "摘要描述": "abstract",
    "abstract": "abstract",
    "description": "abstract",
    "desc": "abstract",
    "narrative": "abstract",

    # 备注/附言
    "备注": "remark",
    "交易备注": "remark",
    "附言": "remark",
    "交易附言": "remark",
    "备注信息": "remark",
    "remark": "remark",
    "memo": "remark",
    "note": "remark",
    "comments": "remark",
    "additional_info": "remark",
}


def parse_amount(amount_str):
    """解析金额字符串为浮点数"""
    # 处理 Series 情况
    if hasattr(amount_str, 'iloc'):
        return amount_str.apply(parse_amount)

    if pd.isna(amount_str) or amount_str == "":
        return 0.0

    try:
        # 移除货币符号和空格
        amount_str = str(amount_str).replace("¥", "").replace("￥", "").replace(",", "").replace(" ", "")
        # 提取数值
        amount_str = ''.join(c for c in amount_str if c.isdigit() or c == '.' or c == '-' or c == '+')
        return float(amount_str) if amount_str else 0.0
    except (ValueError, AttributeError):
        return 0.0


def parse_debit_credit(dc_str):
    """解析借贷标志为标准值

    标准化输出:
    - 借方/支出: 'D' 或 '借'
    - 贷方/收入: 'C' 或 '贷'
    """
    # 处理 Series 情况
    if hasattr(dc_str, 'iloc'):
        return dc_str.apply(parse_debit_credit)

    if pd.isna(dc_str) or str(dc_str).strip() == "":
        return None

    dc_str = str(dc_str).strip().upper()

    # 借方标志
    debit_patterns = ['D', '借', 'DEBIT', 'DR', '支出', '付', '-', 'EXPENSE', 'expense', '支', 'DEBIT']
    # 贷方标志
    credit_patterns = ['C', '贷', 'CREDIT', 'CR', '收入', '收', '+', 'INCOME', 'income', '收', 'CREDIT']

    for pattern in debit_patterns:
        if pattern in dc_str:
            return '借'
    for pattern in credit_patterns:
        if pattern in dc_str:
            return '贷'

    return dc_str


def parse_date_only(dt_str) -> Optional[str]:
    """解析日期字符串为标准格式 YYYY-MM-DD"""
    # 处理 Series 情况
    if hasattr(dt_str, 'iloc'):
        return dt_str.apply(parse_date_only)

    if pd.isna(dt_str) or dt_str == "":
        return None

    dt_str = str(dt_str).strip()

    # 处理 float 格式（如 20240102.0 -> 20240102）
    if dt_str.endswith('.0'):
        dt_str = dt_str[:-2]

    # 日期格式
    date_formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y年%m月%d日",
        "%m-%d",
        "%m/%d",
        "%d %b %Y",
        "%b %d, %Y",
    ]

    for fmt in date_formats:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # 支持 8 位纯数字日期格式（如 20240102 -> 2024-01-02）
    if re.match(r'^\d{8}$', dt_str):
        try:
            dt = datetime.strptime(dt_str, "%Y%m%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    return dt_str


def parse_time_only(time_str) -> Optional[str]:
    """解析时间字符串为标准格式 :HHMM:SS"""
    # 处理 Series 情况
    if hasattr(time_str, 'iloc'):
        return time_str.apply(parse_time_only)

    if pd.isna(time_str) or time_str == "":
        return None

    time_str = str(time_str).strip()

    # 处理 float 格式（如 150132.0 -> 150132）
    if time_str.endswith('.0'):
        time_str = time_str[:-2]

    # 时间格式
    time_formats = [
        "%H:%M:%S",
        "%H:%M",
        "%H:%M:%S.%f",
    ]

    for fmt in time_formats:
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt.strftime("%H:%M:%S")
        except ValueError:
            continue

    # 支持 HHmmss 格式（6位纯数字，如 193816 -> 19:38:16）
    if re.match(r'^\d{6}$', time_str):
        try:
            dt = datetime.strptime(time_str, "%H%M%S")
            return dt.strftime("%H:%M:%S")
        except ValueError:
            pass

    # 支持 HHmms 格式（5位纯数字，如 83016 -> 08:30:16，假设首位0省略）
    if re.match(r'^\d{5}$', time_str):
        try:
            dt = datetime.strptime(time_str, "%H%M%S")
            return dt.strftime("%H:%M:%S")
        except ValueError:
            pass

    # 支持 HHmm 格式（4位纯数字，如 0930 -> 09:30:00）
    if re.match(r'^\d{4}$', time_str):
        try:
            dt = datetime.strptime(time_str, "%H%M")
            return dt.strftime("%H:%M:%S")
        except ValueError:
            pass

    return time_str


_DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_TIME_RE = re.compile(r'^\d{2}:\d{2}:\d{2}$')


def _is_strict_date(s) -> bool:
    """严格校验 YYYY-MM-DD 格式且日历合法"""
    if pd.isna(s) or not isinstance(s, str):
        return False
    if not _DATE_RE.match(s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _is_strict_time(s) -> bool:
    """严格校验 HH:MM:SS 格式且时间合法"""
    if pd.isna(s) or not isinstance(s, str):
        return False
    if not _TIME_RE.match(s):
        return False
    try:
        datetime.strptime(s, "%H:%M:%S")
        return True
    except ValueError:
        return False


def strict_validate_datetime_fields(df: pd.DataFrame) -> pd.DataFrame:
    """
    对 trans_date / trans_time 做严格格式 + 日历合法性校验：
    - trans_date 不符合 YYYY-MM-DD 或日历非法 → 取上一条日期（链式传递），
      首行无有效日期时使用当天运行日期作为兜底。
    - trans_time 不符合 HH:MM:SS 或时间非法 → 置 None。
    """
    if df.empty:
        return df

    # ── trans_date：顺序遍历，前向填充 ──
    if 'trans_date' in df.columns:
        prev_date: str = datetime.now().strftime("%Y-%m-%d")  # 首行兜底
        for idx in df.index:
            val = df.at[idx, 'trans_date']
            val_str = str(val).strip() if pd.notna(val) else ''
            if _is_strict_date(val_str):
                prev_date = val_str          # 有效值：更新游标
            else:
                df.at[idx, 'trans_date'] = prev_date  # 无效值：回填并保持游标

    # ── trans_time：向量化，无效置 None ──
    if 'trans_time' in df.columns:
        df['trans_time'] = df['trans_time'].apply(
            lambda v: v if _is_strict_time(str(v).strip() if pd.notna(v) else '') else None
        )

    return df


def parse_datetime(dt_str: str) -> Optional[str]:
    """解析日期时间字符串为标准格式"""
    if pd.isna(dt_str) or dt_str == "":
        return None

    dt_str = str(dt_str).strip()

    # 尝试多种日期格式
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
        "%Y年%m月%d日 %H:%M:%S",
        "%Y年%m月%d日 %H:%M",
        "%Y年%m月%d日",
        "%m-%d %H:%M:%S",
        "%m/%d %H:%M:%S",
        "%d %b %Y %H:%M:%S",
        "%d %b %Y",
        "%b %d, %Y %H:%M:%S",
        "%b %d, %Y",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

    return dt_str  # 返回原始字符串


def split_datetime_fields(df: pd.DataFrame) -> pd.DataFrame:
    """
    校验并拆分日期时间字段

    处理以下情况：
    1. trans_date 包含完整日期时间（如 "2026-01-01 10:30:00"）
       - 拆分：日期转 yyyy-mm-dd 格式，时间存入 trans_time（如果为空）
    2. trans_time 包含完整日期时间（如 "2026-01-01 10:30:00"）
       - 拆分：时间标准化为 HH:MM:SS，日期存入 trans_date（如果为空）

    Args:
        df: 处理后的 DataFrame

    Returns:
        拆分后的 DataFrame
    """
    if df.empty:
        return df

    # 确保字段存在
    if 'trans_date' not in df.columns:
        df['trans_date'] = None
    if 'trans_time' not in df.columns:
        df['trans_time'] = None

    # 日期时间分隔符模式（支持 - / . 分隔符）
    datetime_pattern = re.compile(
        r'^(\d{4}[-/.]?\d{1,2}[-/.]?\d{1,2})[\sT]+(\d{1,2}:?\d{0,2}:?\d{0,2})$'
    )
    # 中文日期时间模式：YYYY年MM月DD日 HH:MM:SS
    datetime_cn_pattern = re.compile(
        r'^(\d{4}年\d{1,2}月\d{1,2}日)[\s]+(\d{1,2}:?\d{0,2}:?\d{0,2})$'
    )
    # 纯数字日期时间模式：YYYYMMDD HHmmss
    datetime_num_pattern = re.compile(
        r'^(\d{8})[\s]+(\d{6})$'
    )

    for idx in df.index:
        trans_date_val = df.at[idx, 'trans_date']
        trans_time_val = df.at[idx, 'trans_time']
        trans_date_str = str(trans_date_val).strip() if pd.notna(trans_date_val) else ''
        trans_time_str = str(trans_time_val).strip() if pd.notna(trans_time_val) else ''

        # 情况1：trans_date 包含日期时间
        if trans_date_str:
            match = datetime_pattern.match(trans_date_str)
            if not match:
                match = datetime_cn_pattern.match(trans_date_str)
            if not match:
                match = datetime_num_pattern.match(trans_date_str)

            if match:
                date_part = match.group(1)
                time_part = match.group(2)

                # 转换日期为 yyyy-mm-dd 格式
                normalized_date = normalize_date_format(date_part)
                df.at[idx, 'trans_date'] = normalized_date

                # 如果 trans_time 为空，填充时间部分
                if not trans_time_str:
                    # 去除时间中的冒号后统一处理
                    time_clean = time_part.replace(':', '')
                    normalized_time = normalize_time_format(time_clean)
                    if normalized_time:
                        df.at[idx, 'trans_time'] = normalized_time

        # 情况2：trans_time 包含日期时间
        if trans_time_str:
            match = datetime_pattern.match(trans_time_str)
            if not match:
                match = datetime_cn_pattern.match(trans_time_str)
            if not match:
                match = datetime_num_pattern.match(trans_time_str)

            if match:
                date_part = match.group(1)
                time_part = match.group(2)

                # 转换时间为 HH:MM:SS 格式
                time_clean = time_part.replace(':', '')
                normalized_time = normalize_time_format(time_clean)
                if normalized_time:
                    df.at[idx, 'trans_time'] = normalized_time

                # 如果 trans_date 为空，填充日期部分
                if not trans_date_str:
                    normalized_date = normalize_date_format(date_part)
                    if normalized_date:
                        df.at[idx, 'trans_date'] = normalized_date
            else:
                # 不是日期时间格式，但也尝试标准化时间（如 112030 -> 11:20:30）
                normalized_time = normalize_time_format(trans_time_str)
                if normalized_time:
                    df.at[idx, 'trans_time'] = normalized_time

    return df


def normalize_date_format(date_str: str) -> str:
    """
    将各种日期格式统一转换为 yyyy-mm-dd 格式

    支持的格式：
    - 2026-01-01
    - 2026/01/01
    - 20260101
    - 2026.01.01
    - 2026年1月1日

    Args:
        date_str: 日期字符串

    Returns:
        标准化后的日期字符串 (yyyy-mm-dd)
    """
    if pd.isna(date_str) or date_str == "":
        return None

    date_str = str(date_str).strip()

    # 移除分隔符中的非数字字符用于纯数字格式检测
    pure_num = re.sub(r'\D', '', date_str)

    # 尝试各种日期格式
    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y%m%d",
        "%Y.%m.%d",
        "%Y年%m月%d日",
        "%Y年%m月%d日",
        "%Y-m-d",
        "%Y/m/d",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # 如果都无法解析，返回原值
    return date_str


def normalize_time_format(time_str: str) -> str:
    """
    将各种时间格式统一转换为 HH:MM:SS 格式

    支持的格式：
    - 10:30:00
    - 10:30
    - 10:30:00.000
    - 103021 (HHmmss 6位纯数字)
    - 1430 (HHmm 4位纯数字)

    Args:
        time_str: 时间字符串

    Returns:
        标准化后的时间字符串 (HH:MM:SS)
    """
    if pd.isna(time_str) or time_str == "":
        return None

    time_str = str(time_str).strip()

    # 尝试各种时间格式
    formats = [
        "%H:%M:%S",
        "%H:%M",
        "%H:%M:%S.%f",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt.strftime("%H:%M:%S")
        except ValueError:
            continue

    # 支持 HHmmss 格式（6位纯数字，如 193816 -> 19:38:16）
    if re.match(r'^\d{6}$', time_str):
        try:
            dt = datetime.strptime(time_str, "%H%M%S")
            return dt.strftime("%H:%M:%S")
        except ValueError:
            pass

    # 支持 HHmms 格式（5位纯数字，如 83016 -> 08:30:16，假设首位0省略）
    if re.match(r'^\d{5}$', time_str):
        try:
            dt = datetime.strptime(time_str, "%H%M%S")
            return dt.strftime("%H:%M:%S")
        except ValueError:
            pass

    # 支持 HHmm 格式（4位纯数字）
    if re.match(r'^\d{4}$', time_str):
        try:
            dt = datetime.strptime(time_str, "%H%M")
            return dt.strftime("%H:%M:%S")
        except ValueError:
            pass

    # 如果都无法解析，返回原值
    return time_str


def normalize_field_name(field_name: str) -> str:
    """标准化字段名"""
    if pd.isna(field_name):
        return ""

    # 移除空格和特殊字符
    name = str(field_name).strip().lower()
    # 移除括号内容
    import re
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'\（[^）]*\）', '', name)
    return name


def map_fields(df: pd.DataFrame) -> pd.DataFrame:
    """将输入CSV的字段映射到标准字段"""
    if df.empty:
        return df

    # 创建列名映射
    column_mapping = {}
    mapped_columns = set()

    for col in df.columns:
        normalized = normalize_field_name(col)

        # 精确匹配
        if normalized in FIELD_MAPPING:
            target = FIELD_MAPPING[normalized]
            column_mapping[col] = target
            mapped_columns.add(target)
            continue

        # 模糊匹配 - 检查是否包含关键词
        for key, value in FIELD_MAPPING.items():
            if key in normalized or normalized in key:
                column_mapping[col] = value
                mapped_columns.add(value)
                break
        else:
            # 无匹配，保留原字段名
            column_mapping[col] = col

    # 重命名列
    df_mapped = df.rename(columns=column_mapping)

    # 删除重复列（保留第一个）
    df_mapped = df_mapped.loc[:, ~df_mapped.columns.duplicated()]

    # 确保所有目标字段都存在（如果不存在才添加）
    for field in TARGET_FIELDS:
        if field not in df_mapped.columns:
            df_mapped[field] = None

    # 返回按目标字段顺序排列的DataFrame
    return df_mapped[list(TARGET_FIELDS.keys())]


def process_transaction_data(
    csv_content: bytes,
    account_name: Optional[str] = None,
    account_id: Optional[str] = None,
    account_bank: Optional[str] = None,
    serial_id: Optional[str] = None
) -> pd.DataFrame:
    """
    处理交易数据CSV

    Args:
        csv_content: CSV文件内容
        account_name: 账户名（用于填充）
        account_id: 账户号（用于填充）
        account_bank: 账户所属机构（用于填充）
        serial_id: 交易流水号（用于填充）

    Returns:
        处理后的DataFrame
    """
    # 读取CSV - 使用更健壮的方法处理各种格式
    text = None

    # 尝试UTF-8
    try:
        text = csv_content.decode('utf-8-sig')
    except UnicodeDecodeError:
        pass

    if text is None:
        try:
            text = csv_content.decode('utf-8')
        except UnicodeDecodeError:
            text = csv_content.decode('gbk')

    # 预处理CSV：确保负数被正确引用
    lines = text.split('\n')
    processed_lines = []
    for line in lines:
        # 跳过空行
        if not line.strip():
            continue
        # 处理形如 "...,值,-数值,..." 的情况
        # 在负数前添加引号（如果还没有引号包围）
        import re
        # 匹配逗号后面跟着负号和数字的情况
        line = re.sub(r',(-?\d+\.?\d*)', r',\1', line)
        processed_lines.append(line)

    # 重新组合
    processed_text = '\n'.join(processed_lines)

    # 使用pandas读取
    try:
        df = pd.read_csv(io.StringIO(processed_text), encoding='utf-8')
    except Exception:
        df = pd.read_csv(io.StringIO(processed_text), encoding='gbk')

    # 将 "--" 替换为空值
    df = df.replace('--', '')

    # 保存借方/贷方发生额的值（在字段映射前）
    # 利用 FIELD_MAPPING 映射规则来判断哪些列会被映射到 trans_amt
    # 支持：借方发生额、贷方发生额、收入金额、支出金额
    debit_amt = None
    credit_amt = None

    for col in df.columns:
        # 使用原始列名进行检查（更精确）
        # 检查该列会被映射到哪个目标字段
        if col in FIELD_MAPPING:
            target_field = FIELD_MAPPING[col]
            # 如果映射到 trans_amt，检查原始列名
            if target_field == 'trans_amt':
                # 借方发生额/支出金额 -> 借方
                if '借方' in col or '支出' in col:
                    # 排除"贷方"的情况
                    if '贷方' not in col and '收入' not in col:
                        debit_amt = df[col].copy()
                # 贷方发生额/收入金额 -> 贷方
                elif '贷方' in col or '收入' in col:
                    # 排除"借方"的情况
                    if '借方' not in col and '支出' not in col:
                        credit_amt = df[col].copy()

    # 处理独立的"支出"和"收入"两列同时存在的情况
    # LLM返回的"支出"和"收入"列都会被映射到trans_amt，需要特殊处理
    # 保存原始列名中的"支出"和"收入"列数据（在字段映射之前保存）
    expense_col_data = None
    income_col_data = None

    for col in df.columns:
        # 检查是否是原始的"支出"或"收入"列
        if col == '支出':
            expense_col_data = df['支出'].copy()
        elif col == '收入':
            income_col_data = df['收入'].copy()

    # 字段映射
    df = map_fields(df)

    # 如果同时存在"支出"和"收入"两列的数据，需要合并处理
    if expense_col_data is not None and income_col_data is not None:
        # 根据支出/收入列的值设置trans_amt和debit_credit
        for idx in df.index:
            expense_val = expense_col_data.iloc[idx] if expense_col_data is not None else None
            income_val = income_col_data.iloc[idx] if income_col_data is not None else None

            # 解析金额
            expense_amt = parse_amount(expense_val)
            income_amt = parse_amount(income_val)

            if income_amt > 0 and expense_amt == 0:
                # 有收入，无支出 -> 贷
                df.at[idx, 'trans_amt'] = income_amt
                df.at[idx, 'debit_credit'] = '贷'
            elif expense_amt != 0 and income_amt == 0:
                # 有支出（包括负数），无收入 -> 借
                df.at[idx, 'trans_amt'] = abs(expense_amt)
                df.at[idx, 'debit_credit'] = '借'
            elif income_amt > 0 and expense_amt > 0:
                # 两者都有值，取较大的那个
                if income_amt >= expense_amt:
                    df.at[idx, 'trans_amt'] = income_amt
                    df.at[idx, 'debit_credit'] = '贷'
                else:
                    df.at[idx, 'trans_amt'] = expense_amt
                    df.at[idx, 'debit_credit'] = '借'

        # 支出/收入映射完成后，对 trans_amt 取绝对值
        if 'trans_amt' in df.columns:
            df['trans_amt'] = df['trans_amt'].abs()

    # 删除重复列（由 map_fields 处理，但保留安全检查）
    df = df.loc[:, ~df.columns.duplicated()]

    # 处理组合字段 对方户名/账号 -> 拆分（必须在字段映射后）
    combined_col = None
    for col in ['对方户名/账号', 'opponent_account_no']:
        if col in df.columns:
            combined_col = col
            break

    if combined_col:
        def split_combined_field(val):
            if pd.isna(val) or str(val).strip() == '':
                return None, None
            val_str = str(val).strip()
            if '/' in val_str:
                parts = val_str.split('/', 1)
                return parts[0].strip() if parts[0].strip() else None, parts[1].strip() if len(parts) > 1 and parts[1].strip() else None
            return None, None  # 没有斜杠时不更新任何字段
        split_result = df[combined_col].apply(split_combined_field)

        # 更新 opponent_name（只更新有值的部分）
        new_name = split_result.apply(lambda x: x[0])
        mask = new_name.notna()
        df.loc[mask, 'opponent_name'] = new_name[mask]

        # 更新 opponent_account_no（如果需要拆分）
        if combined_col == 'opponent_account_no':
            # 原字段是 opponent_account_no
            # 如果拆分后有账号部分才更新，否则保持原值
            new_account = split_result.apply(lambda x: x[1] if x[1] else None)
            # 只更新有值的部分，确保类型一致
            mask = new_account.notna()
            for idx in df.index:
                if mask.get(idx, False):
                    df.at[idx, 'opponent_account_no'] = new_account.at[idx]
        else:
            # 原字段是 对方户名/账号，填充拆分后的账号部分
            df['opponent_account_no'] = df['opponent_account_no'].fillna(split_result.apply(lambda x: x[1]))

        # 只有当原字段不是 opponent_account_no 时才删除
        if combined_col != 'opponent_account_no':
            df = df.drop(columns=[combined_col], errors='ignore')

    # 数据清洗：删除脏数据记录
    df = clean_dirty_data(df)

    # 填充账户名和账户号
    if account_name:
        # 如果原数据没有name字段或为空，则填充
        if 'name' not in df.columns or df['name'].isna().all():
            df['name'] = account_name

    if account_id:
        # LLM 元数据中提取的账户号，填充到 account_no（account_id 由上游参数固定覆盖）
        if 'account_no' not in df.columns or df['account_no'].isna().all():
            df['account_no'] = account_id

    if account_bank:
        # 如果原数据没有account_bank字段或为空，则填充
        if 'account_bank' not in df.columns or df['account_bank'].isna().all():
            df['account_bank'] = account_bank

    # 填充交易流水号（通过参数传入，不从CSV中获取）
    if serial_id:
        df['serial_id'] = serial_id

    # 处理交易金额：确保是数值类型
    if 'trans_amt' in df.columns:
        df['trans_amt'] = df['trans_amt'].apply(parse_amount)

        # 处理金额正负到借贷标识的映射
        # 判断该份原始数据交易金额是否有负数
        has_negative = (df['trans_amt'] < 0).any()

        if has_negative:
            # 若有负数：正值映射到"贷"，负值映射到"借"
            # trans_amt 取绝对值
            for idx in df.index:
                amt = df.at[idx, 'trans_amt']
                if pd.notna(amt) and amt != 0:
                    if amt > 0:
                        # 正值映射到贷
                        if pd.isna(df.at[idx, 'debit_credit']) or df.at[idx, 'debit_credit'] is None:
                            df.at[idx, 'debit_credit'] = '贷'
                    else:
                        # 负值映射到借，金额取绝对值
                        df.at[idx, 'trans_amt'] = abs(amt)
                        if pd.isna(df.at[idx, 'debit_credit']) or df.at[idx, 'debit_credit'] is None:
                            df.at[idx, 'debit_credit'] = '借'

        # 借贷映射完成后，对 trans_amt 取绝对值（确保所有金额为正数）
    df['trans_amt'] = df['trans_amt'].abs()

    # 处理交易日期
    if 'trans_date' in df.columns:
        df['trans_date'] = df['trans_date'].apply(parse_date_only)

    # 处理交易时间
    if 'trans_time' in df.columns:
        df['trans_time'] = df['trans_time'].apply(parse_time_only)

    # 日期时间校验与拆分：处理完整 datetime 映射到单一字段的情况
    # trans_date 只保留年月日，trans_time 保留时间部分
    df = split_datetime_fields(df)

    # 强校验：trans_date 必须为合法 YYYY-MM-DD（日历校验），否则前向填充；
    # trans_time 必须为合法 HH:MM:SS，否则置 None
    df = strict_validate_datetime_fields(df)

    # 处理借贷标志：标准化为 借/贷
    if 'debit_credit' in df.columns:
        df['debit_credit'] = df['debit_credit'].apply(parse_debit_credit)

    # 处理收/支/其他字段到借贷标志的映射
    # 查找可能的收入/支出标识字段（这些字段在字段映射后可能已被删除，需要从原始列名中查找）
    income_expense_fields = ['收/支', '收入/支出', '收支', '收入', '支出', '收入/支出/其他', '收', '支',
                              'income_expense', 'in_out']

    # 从原始CSV的列名中查找收入/支出字段（这些字段在字段映射时会被覆盖，需要重新处理）
    # 检查是否有原始列名包含收/支信息
    for col in df.columns:
        col_lower = str(col).lower()
        # 跳过已经是标准字段的列
        if col in TARGET_FIELDS or col == 'debit_credit':
            continue

        # 检查是否是收入/支出字段
        is_income_expense_field = False
        for field in income_expense_fields:
            if field.lower() in col_lower or col_lower == field.lower():
                is_income_expense_field = True
                break

        if is_income_expense_field:
            # 将收入/支出字段值映射到借贷标志
            for idx in df.index:
                val = df.at[idx, col]
                if pd.notna(val) and str(val).strip():
                    val_str = str(val).strip()
                    # 收入/收 -> 贷
                    if '收' in val_str or '收入' in val_str or val_str.lower() in ['income', 'c', 'credit']:
                        if pd.isna(df.at[idx, 'debit_credit']) or df.at[idx, 'debit_credit'] is None:
                            df.at[idx, 'debit_credit'] = '贷'
                    # 支出/支 -> 借
                    elif '支' in val_str or '支出' in val_str or val_str.lower() in ['expense', 'd', 'debit']:
                        if pd.isna(df.at[idx, 'debit_credit']) or df.at[idx, 'debit_credit'] is None:
                            df.at[idx, 'debit_credit'] = '借'
                    # 其他 -> 不做处理

            # 删除已处理的收入/支出字段
            df = df.drop(columns=[col], errors='ignore')

    # 处理借方/贷方发生额：将借贷方金额相加作为交易金额
    # 使用字段映射前保存的值（避免列被覆盖）
    # 只要有任一边有值就执行计算
    if debit_amt is not None or credit_amt is not None:
        def get_trans_amt(idx):
            try:
                debit = float(debit_amt.iloc[idx]) if pd.notna(debit_amt.iloc[idx]) else 0
            except (ValueError, TypeError):
                debit = 0
            try:
                credit = float(credit_amt.iloc[idx]) if pd.notna(credit_amt.iloc[idx]) else 0
            except (ValueError, TypeError):
                credit = 0
            return debit + credit

        df['trans_amt'] = [get_trans_amt(i) for i in range(len(df))]
        # 借方/贷方发生额计算后取绝对值
        df['trans_amt'] = df['trans_amt'].abs()

        # 根据借方/贷方发生额设置借贷标志
        # 贷方大于0时，借贷标志为贷；借方大于0时，借贷标志为借
        # 优先判断贷方，因为贷方通常表示收入
        for idx in df.index:
            try:
                debit = float(debit_amt.iloc[idx]) if pd.notna(debit_amt.iloc[idx]) else 0
            except (ValueError, TypeError):
                debit = 0
            try:
                credit = float(credit_amt.iloc[idx]) if pd.notna(credit_amt.iloc[idx]) else 0
            except (ValueError, TypeError):
                credit = 0

            # 如果借贷标志为空，根据借方/贷方发生额设置
            # 优先判断贷方：贷方大于0 -> 贷，借方大于0 -> 借
            if pd.isna(df.at[idx, 'debit_credit']) or df.at[idx, 'debit_credit'] is None:
                if credit > 0:
                    df.at[idx, 'debit_credit'] = '贷'
                elif debit > 0:
                    df.at[idx, 'debit_credit'] = '借'

    # 清理账号字段：去除两边特殊字符
    def clean_account_no(val):
        if pd.isna(val) or str(val).strip() == '':
            return None
        val_str = str(val).strip()
        val_str = val_str.strip('/').strip('-').strip('#').strip()
        return val_str if val_str else None

    if 'opponent_account_no' in df.columns:
        df['opponent_account_no'] = df['opponent_account_no'].apply(clean_account_no)

    # ── 排序已禁用（保持原始行序）──
    # df['_original_order'] = range(len(df))
    # if 'trans_date' in df.columns:
    #     sort_cols = ['trans_date']
    #     if 'trans_time' in df.columns and df['trans_time'].notna().any():
    #         sort_cols.append('trans_time')
    #     sort_cols.append('_original_order')
    #     df = df.sort_values(by=sort_cols, ascending=True, na_position='last').reset_index(drop=True)
    #     df = df.drop(columns=['_original_order'], errors='ignore')

    # 填充行号
    if 'rel_line_num' in df.columns:
        df['rel_line_num'] = range(1, len(df) + 1)

    # 填充创建和更新时间
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if 'create_time' in df.columns:
        df['create_time'] = now
    if 'update_time' in df.columns:
        df['update_time'] = now

    return df


def clean_dirty_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    清洗脏数据记录

    删除以下类型的记录:
    1. 所有字段值都为 '-' 或类似的占位符（数量不固定）
    2. 所有数值字段皆为表头字段（第一行表头除外）

    Args:
        df: 映射后的DataFrame

    Returns:
        清洗后的DataFrame
    """
    if df.empty:
        return df

    original_len = len(df)

    # 1. 删除所有字段值都为 '-' 或空白的记录
    # 使用正则匹配：只包含 '-' 和空白的字符串
    dash_pattern = re.compile(r'^[-\s]+$')

    def is_all_dashes(row):
        """检查整行是否全是 '-' 或空白"""
        non_empty_count = 0
        for val in row:
            if pd.isna(val):
                continue
            val_str = str(val).strip()
            if val_str == '':
                continue
            non_empty_count += 1
            # 如果包含非 '-' 非空白字符，则不是脏数据
            if not dash_pattern.match(val_str):
                return False
        # 如果至少有一个非空值，且全是 '-' 或空白，则删除
        return non_empty_count > 0

    df = df[~df.apply(is_all_dashes, axis=1)]

    # 2. 删除数值字段皆为表头字段的记录（第一行表头除外）
    # 常见表头关键词
    header_keywords = ['交易时间', '交易日期', '金额', '余额', '摘要', '户名', '账号',
                       '对方', '日期', '时间', '金额', '类型', '名称', 'trans_', 'amount',
                       'balance', 'date', 'time', 'type', 'name', 'account']

    def is_header_row(row):
        """检查是否为表头行"""
        # 确保 row 是单一值，不是 Series
        def get_value(val):
            if hasattr(val, 'iloc'):  # 如果是 Series
                return val.iloc[0] if len(val) > 0 else None
            return val

        # 获取数值类型的字段（排除 id、name、account_id 等非数值字段）
        numeric_cols = ['trans_amt', 'account_balance']

        # 检查数值字段是否为表头关键词
        for col in numeric_cols:
            if col in df.columns:
                val = row.get(col)
                val = get_value(val)
                if pd.notna(val):
                    val_str = str(val).strip()
                    # 如果是数值但值像表头（如 "金额(元)"）
                    if val_str in header_keywords:
                        return True

        # 检查所有非空非数值字段是否都是表头关键词
        all_header = True
        for val in row:
            val = get_value(val)
            if pd.isna(val):
                continue
            val_str = str(val).strip()
            if val_str == '':
                continue
            # 检查是否匹配任何表头关键词
            is_header = False
            for keyword in header_keywords:
                if keyword in val_str or val_str == keyword:
                    is_header = True
                    break
            if not is_header:
                all_header = False
                break

        return all_header

    # 应用清洗（跳过第一行，它可能是真正的表头）
    if len(df) > 1:
        # 直接获取需要删除的行索引
        rows_to_drop = []
        for idx in range(1, len(df)):
            if is_header_row(df.iloc[idx]):
                rows_to_drop.append(idx)
        if rows_to_drop:
            df = df.drop(rows_to_drop).reset_index(drop=True)
        else:
            df = df.reset_index(drop=True)

    # 3. 删除只有 'id' 字段有值，其他字段都为空的记录（无效数据行）
    def is_invalid_row(row):
        """检查是否为无效数据行"""
        # 确保 row 是单一值，不是 Series
        def get_value(val):
            if hasattr(val, 'iloc'):
                return val.iloc[0] if len(val) > 0 else None
            return val

        # 如果 id 列有值但其他关键字段都为空，可能是无效行
        if 'id' in df.columns:
            val = row.get('id')
            val = get_value(val)
            if pd.notna(val):
                key_cols = ['trans_date', 'trans_time', 'trans_amt', 'account_balance']
                all_empty = True
                for col in key_cols:
                    if col in df.columns:
                        cell_val = row.get(col)
                        cell_val = get_value(cell_val)
                        if pd.notna(cell_val) and str(cell_val).strip() != '':
                            all_empty = False
                            break
                if all_empty:
                    return True
        return False

    df = df[~df.apply(is_invalid_row, axis=1)]

    cleaned_len = len(df)
    if original_len != cleaned_len:
        print(f"[数据清洗] 删除了 {original_len - cleaned_len} 条脏数据")

    return df.reset_index(drop=True)


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """将DataFrame转换为CSV字节流"""
    output = io.StringIO()
    df.to_csv(output, index=False, encoding='utf-8-sig')  # utf-8-sig 支持Excel打开
    return output.getvalue().encode('utf-8')
