"""多段转写异文校勘（collate）测试。"""

import pytest

from app.assembler import AssemblyError, assemble
from app.collator import collate, tally_position


def test_no_variant_for_plain_wildcard_fill():
    # "?" 被补成"时"，只有一种已知字：不列入异文
    r = collate(["学而时习之", "学而?习之"])
    assert r["text"] == "学而时习之"
    assert r["variants"] == []


def test_unique_top_vote_is_suggested():
    r = collate(["甲乙丙丁戊", "甲乙戌丁戊", "甲乙丙丁戊"])
    assert r["text"] == "甲乙丙丁戊"
    assert len(r["variants"]) == 1
    v = r["variants"][0]
    assert v["pos"] == 2
    assert v["char"] == "丙"  # 当前拼接字不被改写（保留左段字）
    assert v["candidates"] == [
        {"char": "丙", "segments": [0, 2]},
        {"char": "戌", "segments": [1]},
    ]
    assert v["suggested"] == "丙"


def test_tied_top_votes_suggested_null():
    r = collate(["甲乙丙丁戊", "甲乙戌丁戊", "甲乙亥丁戊"])
    (v,) = r["variants"]
    assert v["pos"] == 2
    assert v["char"] == "丙"
    assert {c["char"]: c["segments"] for c in v["candidates"]} == {
        "丙": [0],
        "戌": [1],
        "亥": [2],
    }
    assert v["suggested"] is None


def test_three_way_overlap_votes_per_segment():
    # 段1、段2 均以"丙X戊"与前文重叠：X 处汇聚三种已知字，各段一票
    r = collate(["甲乙丙丁戊", "丙戌戊", "丙亥戊"])
    (v,) = r["variants"]
    assert v["pos"] == 3
    assert {c["char"]: c["segments"] for c in v["candidates"]} == {
        "丁": [0],
        "戌": [1],
        "亥": [2],
    }
    assert v["suggested"] is None
    # 同一段在任一位置最多投一票（段序号在候选间不重复）
    seen = [s for c in v["candidates"] for s in c["segments"]]
    assert len(seen) == len(set(seen))


def test_tally_position_skips_wildcard_and_dedups_segment():
    segments = ["甲乙", "?乙"]
    # 位置 1（乙）：段0 与段1 都为"乙"，且模拟同段重复来源
    entry = tally_position(
        "乙",
        [
            {"segment": 0, "pos": 1},
            {"segment": 0, "pos": 1},  # 同段重复来源
            {"segment": 1, "pos": 1},
        ],
        segments,
    )
    assert entry is None  # 只有一种已知字

    # "?" 不投票：段1 在位置 0 是 ?，即便与段0"甲"汇聚也不产生异文
    assert tally_position(
        "甲",
        [{"segment": 0, "pos": 0}, {"segment": 1, "pos": 0}],
        ["甲乙", "?乙"],
    ) is None


def test_text_unchanged_and_matches_assemble():
    segments = ["甲乙丙丁戊", "甲乙戌丁戊", "甲乙亥丁戊"]
    r = collate(segments)
    assert r["text"] == assemble(segments)["text"]
    # 异文字段仍是拼接文本原字（不自动改写）
    for v in r["variants"]:
        assert v["char"] == r["text"][v["pos"]]


def test_gate_failure_propagates():
    with pytest.raises(AssemblyError) as exc:
        collate(["孔子曰未知", "未知生焉", "完全无关文本"])
    assert exc.value.failed_segment == 2
