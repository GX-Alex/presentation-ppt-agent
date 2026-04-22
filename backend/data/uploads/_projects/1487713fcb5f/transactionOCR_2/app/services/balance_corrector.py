"""
余额连续性校验 + 借贷方向自动修正

在所有 chunk 合并后的 merged_df 上运行：
- 逐行对相邻行余额差与借贷金额进行校验，判断方向是否有误
- 正确行 → verif_label = '正确'
- 首行（无前行参照）→ verif_label = '正确'（默认信任）
- 空余额/空金额/无效借贷标志 → verif_label 留空（跳过）

升序（时间从早到晚）：
  bal[i] = bal[i-1] + delta[i]，当前行的 dc 决定余额变化
  若 dc 错 → 直接修正当前行，verif_label = '已修正'

降序（时间从晚到早）：
  bal[i] = bal[i-1] - delta[i-1]，前一行的 dc 决定余额变化
  若 dc[i-1] 错 → 回退修正前一行，verif_label = '已修正'
  无法修复 → verif_label = '存疑'（标在当前行），dc 不变
"""
import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger("transaction_ocr")

_VALID_DC = {"借", "贷"}


def _parse_float(val) -> Optional[float]:
    """将字段值解析为浮点数，无法解析返回 None"""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).replace(",", "").strip()
    if not s or s.lower() == "nan":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _detect_order(df: pd.DataFrame) -> str:
    """
    通过首尾行非空 trans_date 判断数据是升序还是降序。
    返回 'asc'（升序/时间从早到晚）或 'desc'（降序/时间从晚到早）。
    无法判断时默认返回 'asc'。
    """
    if "trans_date" not in df.columns or len(df) < 2:
        return "asc"

    dates = df["trans_date"].dropna().astype(str)
    dates = dates[dates.str.strip().str.len() >= 8]

    if len(dates) < 2:
        return "asc"

    first_date = dates.iloc[0]
    last_date = dates.iloc[-1]

    return "asc" if first_date <= last_date else "desc"


def _flip(dc: str) -> str:
    return "贷" if dc == "借" else "借"


def apply_balance_correction(df: pd.DataFrame, tolerance: float = 0.01) -> pd.DataFrame:
    """
    对 merged_df 执行余额连续性校验，就地修改 debit_credit 和 verif_label 列。

    升序：校验当前行的 dc，错误时修正当前行。
    降序：校验前一行的 dc（因为是前行的交易决定了到当前行的余额变化），
          错误时回退修正前一行，当前行标为「正确」。

    Args:
        df        : 合并后的完整 DataFrame（保持原始行序，不排序）
        tolerance : 余额误差容忍值（默认 0.01 元）

    Returns:
        修正后的 DataFrame（同一对象）
    """
    if df.empty:
        return df

    required = {"debit_credit", "trans_amt", "account_balance"}
    if not required.issubset(df.columns):
        logger.debug("[balance_corrector] 缺失必要列 %s，跳过校验", required - set(df.columns))
        return df

    if "verif_label" not in df.columns:
        df["verif_label"] = ""

    # 确保列为 object 类型，避免写入字符串时报错
    df["verif_label"] = df["verif_label"].astype(object)
    df["debit_credit"] = df["debit_credit"].astype(object)

    order = _detect_order(df)
    logger.info("[balance_corrector] 数据排列方向: %s（%s）", order, "升序" if order == "asc" else "降序")

    corrected = 0
    suspect = 0
    correct = 0

    prev_balance: Optional[float] = None
    # 降序专用：跟踪前一行的 dc/amt/index，用于回退修正
    prev_dc: Optional[str] = None
    prev_amt: Optional[float] = None
    prev_valid_idx = None      # 前一个有效行的 DataFrame index
    prev_delta_valid: bool = False  # 前行 dc/amt 是否可用于降序校验

    for i in df.index:
        dc = df.at[i, "debit_credit"]
        amt = _parse_float(df.at[i, "trans_amt"])
        bal = _parse_float(df.at[i, "account_balance"])

        # ── 跳过条件：缺失必要字段 ──
        if amt is None or amt == 0.0 or bal is None or dc not in _VALID_DC:
            if bal is not None:
                prev_balance = bal
            prev_delta_valid = False  # 跳过行，其 dc/amt 不可信
            continue

        # ── 首行，或降序前行不可用 ──
        if prev_balance is None or (order == "desc" and not prev_delta_valid):
            df.at[i, "verif_label"] = "正确"
            prev_balance = bal
            prev_dc = dc
            prev_amt = amt
            prev_valid_idx = i
            prev_delta_valid = True
            correct += 1
            continue

        if order == "asc":
            # ── 升序：用当前行自己的 delta 校验 ──
            # bal[i] = bal[i-1] + delta[i]，delta[i] = +amt 贷 / -amt 借
            sign = 1.0 if dc == "贷" else -1.0
            expected = prev_balance + sign * amt
            diff = abs(bal - expected)

            if diff <= tolerance:
                df.at[i, "verif_label"] = "正确"
                correct += 1
            else:
                dc_flip = _flip(dc)
                sign_flip = 1.0 if dc_flip == "贷" else -1.0
                expected_flip = prev_balance + sign_flip * amt
                diff_flip = abs(bal - expected_flip)

                if diff_flip <= tolerance:
                    logger.info(
                        "[balance_corrector] 第%d行 修正 debit_credit: %s→%s "
                        "(余额差 %.4f→%.4f)",
                        i + 1, dc, dc_flip, diff, diff_flip,
                    )
                    df.at[i, "debit_credit"] = dc_flip
                    df.at[i, "verif_label"] = "已修正"
                    dc = dc_flip  # 更新本轮 dc，传给下次迭代的 prev_dc
                    corrected += 1
                else:
                    logger.warning(
                        "[balance_corrector] 第%d行 余额不连续且无法自动修正 "
                        "(prev=%.2f, amt=%.2f, dc=%s, actual=%.2f, "
                        "expected=%.2f, expected_flip=%.2f)",
                        i + 1, prev_balance, amt, dc, bal, expected, expected_flip,
                    )
                    df.at[i, "verif_label"] = "存疑"
                    suspect += 1

        else:  # descending
            # ── 降序：用前一行的 delta 校验当前行余额 ──
            # 时间轴：... T[i] → T[i-1] ...
            # T[i] 更早，T[i-1] 更新（数组中在前）
            # bal[i-1] = bal[i] + delta[i-1]  =>  bal[i] = bal[i-1] - delta[i-1]
            # delta[i-1] = +prev_amt 贷 / -prev_amt 借
            sign_prev = 1.0 if prev_dc == "贷" else -1.0
            expected = prev_balance - sign_prev * prev_amt
            diff = abs(bal - expected)

            if diff <= tolerance:
                df.at[i, "verif_label"] = "正确"
                correct += 1
            else:
                # 尝试翻转前一行的 dc
                prev_dc_flip = _flip(prev_dc)
                sign_prev_flip = 1.0 if prev_dc_flip == "贷" else -1.0
                expected_flip = prev_balance - sign_prev_flip * prev_amt
                diff_flip = abs(bal - expected_flip)

                if diff_flip <= tolerance:
                    logger.info(
                        "[balance_corrector] 第%d行(前行) 修正 debit_credit: %s→%s "
                        "(余额差 %.4f→%.4f)，第%d行余额连续",
                        (prev_valid_idx + 1) if prev_valid_idx is not None else "?",
                        prev_dc, prev_dc_flip, diff, diff_flip, i + 1,
                    )
                    # 回退修正前行
                    if prev_valid_idx is not None:
                        df.at[prev_valid_idx, "debit_credit"] = prev_dc_flip
                        old_label = df.at[prev_valid_idx, "verif_label"]
                        df.at[prev_valid_idx, "verif_label"] = "已修正"
                        if old_label == "正确":
                            correct -= 1  # 前行不再算「正确」
                    prev_dc = prev_dc_flip  # 修正后的 dc 传给下轮
                    corrected += 1
                    df.at[i, "verif_label"] = "正确"
                    correct += 1
                else:
                    logger.warning(
                        "[balance_corrector] 第%d行 余额不连续且无法自动修正 "
                        "(prev_bal=%.2f, prev_dc=%s, prev_amt=%.2f, actual=%.2f, "
                        "expected=%.2f, expected_flip=%.2f)",
                        i + 1, prev_balance, prev_dc, prev_amt, bal,
                        expected, expected_flip,
                    )
                    df.at[i, "verif_label"] = "存疑"
                    suspect += 1

        prev_balance = bal
        prev_dc = dc
        prev_amt = amt
        prev_valid_idx = i
        prev_delta_valid = True

    total = len(df)
    logger.info(
        "[balance_corrector] 校验完成 共%d行: 正确=%d 已修正=%d 存疑=%d 跳过=%d",
        total, correct, corrected, suspect, total - correct - corrected - suspect,
    )
    return df
