"""多份残页转写的异文校勘。

复用 :mod:`app.assembler` 的顺序拼接结果（同样的段数/长度限制与续接门槛），
得到拼接文本与逐字来源后，对每个输出位置回查所有来源原字并投票：

- 以**原始段**为投票单位：同一来源段在同一位置出现多次只计一票；
- 原始字为 ``?``（未辨认字）不投票；
- 仅当某位置出现**至少两种不同已知字**时，才作为异文位置列出；
  单纯的 ``?`` 补字（只有一种已知字）不列入；
- 建议字取**唯一最高票**候选；最高票并列时建议为 ``None``。

校勘只给出建议，不自动改写拼接文本。
"""

from __future__ import annotations

from .aligner import WILDCARD
from .assembler import assemble


def tally_position(ch: str, srcs: list[dict], segments: list[str]) -> dict | None:
    """对单个输出位置回查来源原字并计票。

    ``srcs`` 为 assembler 给出的逐字来源（``{"segment", "pos"}``）。
    返回异文条目；不足两种已知字（含纯 ``?`` 补字）时返回 ``None``。
    """
    # 段序号 -> 该段在此位置投出的已知原字。
    # 同段重复来源只计一次（setdefault 取先出现者）；"?" 不投票。
    votes: dict[int, str] = {}
    for s in srcs:
        seg = s["segment"]
        original = segments[seg][s["pos"]]
        if original == WILDCARD or seg in votes:
            continue
        votes[seg] = original

    # 候选字 -> 支持它的段序号列表
    tallies: dict[str, list[int]] = {}
    for seg, original in votes.items():
        tallies.setdefault(original, []).append(seg)

    if len(tallies) < 2:
        return None  # 补字但无异文的位置不列入

    candidates = [
        {"char": cand, "segments": sorted(segs)}
        for cand, segs in tallies.items()
    ]
    # 票数降序，票数相同按字形码位升序，保证输出稳定
    candidates.sort(key=lambda c: (-len(c["segments"]), c["char"]))

    top_votes = len(candidates[0]["segments"])
    top_chars = [c for c in candidates if len(c["segments"]) == top_votes]
    suggested = top_chars[0]["char"] if len(top_chars) == 1 else None

    return {"char": ch, "candidates": candidates, "suggested": suggested}


def collate(segments: list[str]) -> dict:
    """拼接多段转写并逐位置回查异文。

    返回 ``{"text": ..., "variants": ...}``；拼接失败时透传
    :class:`~app.assembler.AssemblyError`（由接口层转为 422）。
    """
    result = assemble(segments)
    text = result["text"]

    variants = [
        {"pos": pos, **entry}
        for pos, (ch, srcs) in enumerate(zip(text, result["sources"]))
        if (entry := tally_position(ch, srcs, segments)) is not None
    ]

    return {"text": text, "variants": variants}
