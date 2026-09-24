"""古籍残页转写拼接 API。

- ``POST /api/align``：提交两段含 "?"（未辨认字）的转写文本，将左段后缀与
  右段前缀做最优对齐，返回最高分对齐的原文区间、逐列对齐和拼接文本。
- ``POST /api/assemble``：提交按阅读顺序排列的 2～5 段转写，逐段复用上述
  后缀-前缀对齐拼接，并返回最终文本与逐字来源列表。
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from .aligner import align
from .assembler import AssemblyError, assemble

MAX_TEXT_LEN = 500   # 单段文本最大长度（残页转写通常远小于此）
MAX_SEGMENTS = 5     # /api/assemble 最大段数
MIN_SEGMENTS = 2     # /api/assemble 最小段数
MAX_TOTAL_LEN = 800  # /api/assemble 各段总长上限

app = FastAPI(
    title="古籍残页转写拼接 API",
    description=(
        "对两段含 `?`（未辨认字）的古籍残页转写文本做重叠拼接："
        "只将左段后缀与右段前缀对齐，左段未参与对齐的前缀、"
        "右段未参与对齐的后缀不计分。"
    ),
    version="1.0.0",
)


class AlignRequest(BaseModel):
    """拼接请求。"""

    left: str = Field(
        ..., min_length=1, max_length=MAX_TEXT_LEN,
        description="左段转写文本，未辨认字以 ? 表示",
        examples=["学而?习之"],
    )
    right: str = Field(
        ..., min_length=1, max_length=MAX_TEXT_LEN,
        description="右段转写文本，未辨认字以 ? 表示",
        examples=["时习之不亦"],
    )


class Interval(BaseModel):
    """原文区间（下标从 0 开始，左闭右开）。"""

    start: int = Field(..., description="起点下标（含）")
    end: int = Field(..., description="终点下标（不含）")
    text: str = Field(..., description="区间原文")


class Column(BaseModel):
    """逐列对齐中的一列。"""

    left_pos: int | None = Field(..., description="左段下标；空缺为 null")
    left_char: str | None = Field(..., description="左段字形；空缺为 null")
    right_pos: int | None = Field(..., description="右段下标；空缺为 null")
    right_char: str | None = Field(..., description="右段字形；空缺为 null")
    type: str = Field(
        ...,
        description="match=相同字 / wildcard=含? / mismatch=异字 / "
                    "gap_left=左段空缺 / gap_right=右段空缺",
    )
    score: int = Field(..., description="本列得分")


class Conflict(BaseModel):
    """异字冲突：拼接时保留左段字。"""

    left_pos: int = Field(..., description="左段原文位置")
    left_char: str = Field(..., description="左段字形（拼接保留）")
    right_pos: int = Field(..., description="右段原文位置")
    right_char: str = Field(..., description="右段字形")


class ResolvedWildcard(BaseModel):
    """"?" 补字记录：以对方已知字替换。"""

    segment: str = Field(..., description="left / right")
    pos: int = Field(..., description="该段原文位置")
    resolved_char: str = Field(..., description="补入的字形")


class AlignResponse(BaseModel):
    """拼接结果。"""

    score: int = Field(..., description="最高对齐得分")
    aligned_pairs: int = Field(..., description="对齐字符对数")
    left_interval: Interval = Field(..., description="左段参与对齐的后缀区间")
    right_interval: Interval = Field(..., description="右段参与对齐的前缀区间")
    left_free_prefix: str = Field(..., description="左段未参与对齐的前缀（不计分）")
    right_free_suffix: str = Field(..., description="右段未参与对齐的后缀（不计分）")
    aligned_left: str = Field(..., description="左段对齐串（空缺以 - 表示）")
    aligned_right: str = Field(..., description="右段对齐串（空缺以 - 表示）")
    columns: list[Column] = Field(..., description="逐列对齐")
    merged: str = Field(..., description="拼接文本")
    conflicts: list[Conflict] = Field(..., description="异字冲突列表")
    resolved_wildcards: list[ResolvedWildcard] = Field(..., description="? 补字列表")


class AssembleRequest(BaseModel):
    """多段顺序拼接请求。"""

    segments: list[str] = Field(
        ...,
        min_length=MIN_SEGMENTS,
        max_length=MAX_SEGMENTS,
        description="按阅读顺序排列的转写文本（2～5 段），未辨认字以 ? 表示",
        examples=[["学而?习之", "时习之不", "之不亦乐乎"]],
    )

    @model_validator(mode="after")
    def _validate_segments(self):
        for idx, seg in enumerate(self.segments):
            if len(seg) < 1:
                raise ValueError(f"第 {idx + 1} 段文本不能为空")
            if len(seg) > MAX_TEXT_LEN:
                raise ValueError(f"第 {idx + 1} 段文本超过 {MAX_TEXT_LEN} 字")
        total = sum(len(seg) for seg in self.segments)
        if total > MAX_TOTAL_LEN:
            raise ValueError(f"各段文本总长 {total} 字，超过 {MAX_TOTAL_LEN} 字上限")
        return self


class CharSource(BaseModel):
    """单个原始段对某输出字的来源标记（段序号、下标均从 0 开始）。"""

    segment: int = Field(..., description="原始段序号（从 0 开始）")
    pos: int = Field(..., description="该字在原始段中的下标（从 0 开始）")


class AssembleResponse(BaseModel):
    """多段顺序拼接结果。"""

    text: str = Field(..., description="最终拼接文本")
    sources: list[list[CharSource]] = Field(
        ...,
        description="逐字来源列表，与 text 等长；每项保留贡献该字的所有原始段"
                    "序号及原文下标（相同字、? 补字双方、异字冲突双方均保留）",
    )


@app.get("/", summary="服务信息")
def index():
    return {
        "name": "古籍残页转写拼接 API",
        "align": "POST /api/align",
        "assemble": "POST /api/assemble",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health", summary="健康检查")
def health():
    return {"status": "ok"}


@app.post(
    "/api/align",
    response_model=AlignResponse,
    summary="拼接两段残页转写文本",
    description=(
        "计分规则：相同字 +2；`?` 与任意字配对 0；异字 -2；"
        "连续空缺首字 -3、其余每字 -1。至少一对字符对齐。"
        "同分取对齐字符对数最多者，再取左段起点最小者。"
    ),
)
def api_align(req: AlignRequest):
    return align(req.left, req.right)


@app.post(
    "/api/assemble",
    response_model=AssembleResponse,
    status_code=200,
    summary="按阅读顺序逐段拼接 2～5 段残页转写",
    description=(
        "每段最长 500 字、总长最长 800 字。逐段复用后缀-前缀对齐：将当前拼接"
        "文本与下一段合并。每一步仅在最高对齐得分大于 0、且至少有 2 对相同"
        "已知字时继续；任一步不满足即返回 422 并指出失败段序号，不产生部分"
        "结果。返回最终文本及与其等长的逐字来源列表，来源保留贡献该字的所有"
        "原始段序号及原文下标（相同字、`?` 补字双方、异字冲突双方均保留）。"
    ),
)
def api_assemble(req: AssembleRequest):
    try:
        return assemble(req.segments)
    except AssemblyError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": str(exc),
                "failed_segment": exc.failed_segment,
            },
        ) from exc
