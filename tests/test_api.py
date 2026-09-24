"""API 接口测试。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_align_endpoint():
    resp = client.post("/api/align", json={"left": "学而?习之", "right": "时习之不亦"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["score"] == 4
    assert data["merged"] == "学而时习之不亦"
    assert data["left_interval"] == {"start": 2, "end": 5, "text": "?习之"}
    assert data["right_interval"] == {"start": 0, "end": 3, "text": "时习之"}
    assert len(data["columns"]) == 3
    assert data["resolved_wildcards"] == [
        {"segment": "left", "pos": 2, "resolved_char": "时"}
    ]


def test_align_endpoint_with_conflict():
    resp = client.post("/api/align", json={"left": "甲乙丙丁", "right": "丙戌戊"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["merged"] == "甲乙丙丁戊"
    assert data["conflicts"] == [
        {"left_pos": 3, "left_char": "丁", "right_pos": 1, "right_char": "戌"}
    ]


def test_empty_segment_rejected():
    resp = client.post("/api/align", json={"left": "", "right": "abc"})
    assert resp.status_code == 422
    resp = client.post("/api/align", json={"left": "abc", "right": ""})
    assert resp.status_code == 422


def test_missing_field_rejected():
    resp = client.post("/api/align", json={"left": "abc"})
    assert resp.status_code == 422


def test_assemble_endpoint():
    resp = client.post(
        "/api/assemble",
        json={"segments": ["学而?习之", "时习之不", "之不亦乐乎"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "学而时习之不亦乐乎"
    sources = data["sources"]
    assert len(sources) == len(data["text"]) == 9
    # 相同字累积来源
    assert sources[4] == [
        {"segment": 0, "pos": 4},
        {"segment": 1, "pos": 2},
        {"segment": 2, "pos": 0},
    ]
    # "?" 补字双方来源保留
    assert sources[2] == [{"segment": 0, "pos": 2}, {"segment": 1, "pos": 0}]


def test_assemble_gate_failure_returns_422_with_segment_index():
    resp = client.post(
        "/api/assemble",
        json={"segments": ["孔子曰未知", "未知生焉", "完全无关文本"]},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["failed_segment"] == 2


def test_assemble_two_same_pairs_required():
    # 仅一对相同字：422 且指出失败的是第 2 段（序号 1）
    resp = client.post("/api/assemble", json={"segments": ["甲乙丙", "乙"]})
    assert resp.status_code == 422
    assert resp.json()["detail"]["failed_segment"] == 1


def test_assemble_too_few_or_many_segments_rejected():
    resp = client.post("/api/assemble", json={"segments": ["abc"]})
    assert resp.status_code == 422
    resp = client.post(
        "/api/assemble",
        json={"segments": ["aa", "bb", "cc", "dd", "ee", "ff"]},
    )
    assert resp.status_code == 422


def test_assemble_individual_segment_too_long_rejected():
    resp = client.post(
        "/api/assemble",
        json={"segments": ["a" * 500, "b" * 501]},
    )
    assert resp.status_code == 422


def test_assemble_total_too_long_rejected():
    resp = client.post(
        "/api/assemble",
        json={"segments": ["字" * 400, "字" * 401]},
    )
    assert resp.status_code == 422


def test_assemble_empty_segment_rejected():
    resp = client.post("/api/assemble", json={"segments": ["abc", ""]})
    assert resp.status_code == 422


def test_collate_endpoint_returns_variants():
    resp = client.post(
        "/api/collate",
        json={"segments": ["甲乙丙丁戊己", "甲乙丙艮戊己", "甲乙丙丁戊己庚辛"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "甲乙丙丁戊己庚辛"
    assert data["variants"] == [
        {
            "pos": 3,
            "current": "丁",
            "candidates": [
                {"char": "丁", "segments": [0, 2]},
                {"char": "艮", "segments": [1]},
            ],
            "suggestion": "丁",
        }
    ]


def test_collate_tie_suggestion_null():
    resp = client.post(
        "/api/collate",
        json={"segments": ["甲乙丙丁戊己", "甲乙丙艮戊己"]},
    )
    assert resp.status_code == 200
    v = resp.json()["variants"][0]
    assert v["suggestion"] is None
    assert [c["segments"] for c in v["candidates"]] == [[0], [1]]


def test_collate_wildcard_fill_not_listed():
    resp = client.post(
        "/api/collate",
        json={"segments": ["学而?习之", "时习之"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "学而时习之"
    assert data["variants"] == []


def test_collate_gate_failure_returns_422_with_segment_index():
    resp = client.post(
        "/api/collate",
        json={"segments": ["孔子曰未知", "未知生焉", "完全无关文本"]},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["failed_segment"] == 2


def test_collate_reuses_assemble_segment_limits():
    # 段数不足 / 超上限
    assert client.post("/api/collate", json={"segments": ["abc"]}).status_code == 422
    assert client.post(
        "/api/collate",
        json={"segments": ["aa", "bb", "cc", "dd", "ee", "ff"]},
    ).status_code == 422
    # 单段过长
    assert client.post(
        "/api/collate",
        json={"segments": ["a" * 500, "b" * 501]},
    ).status_code == 422
    # 总长超限
    assert client.post(
        "/api/collate",
        json={"segments": ["字" * 400, "字" * 401]},
    ).status_code == 422
    # 空段
    assert client.post("/api/collate", json={"segments": ["abc", ""]}).status_code == 422
    # 缺字段
    assert client.post("/api/collate", json={}).status_code == 422
