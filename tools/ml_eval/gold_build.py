"""Merge hand labels with sample; map short codes to catalog part groups."""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO, E

CODES = {
    "검사": "검사·계수장치",
    "계측": "계측·계량기",
    "구동제어": "구동제어기",
    "날인": "날인·인쇄장치",
    "로봇": "로봇",
    "모터": "모터",
    "배선": "배선·접속부",
    "센서": "센서·검출",
    "스위치": "스위치·릴레이",
    "전원": "전원·보호장치",
    "점화": "점화장치",
    "제어기": "제어기·I/O·통신",
    "조작": "조작·표시장치",
    "히터": "히터·온도제어",
    "가이드": "가이드·레일",
    "감속기": "감속기",
    "교반": "교반기구",
    "그리퍼": "그리퍼·후크",
    "기어": "기어·스프라켓",
    "롤러": "롤러·브러시",
    "배출": "배출·낙하기구",
    "베어링": "베어링·부싱",
    "벨트": "벨트·풀리",
    "성형": "성형기구",
    "스틱": "스틱공급기구",
    "스프링": "스프링·탄성부품",
    "씰러": "씰링기구",
    "용기공급": "용기공급기구",
    "이송부속": "이송부속",
    "인계": "인계·정렬기구",
    "체결": "체결부",
    "체인": "체인·링크",
    "축": "축·커플링·키",
    "충진": "충진·분사기구",
    "캡핑": "캡핑부",
    "커팅": "커팅기구",
    "컨베어": "컨베어",
    "클러치": "클러치",
    "블레이드": "판·블레이드",
    "포장설비": "포장설비",
    "푸셔": "푸셔·디버터·스토퍼",
    "프레임": "프레임·고정부",
    "피스톤": "피스톤기구",
    "공압밸브": "공압밸브·조절기",
    "솔밸브": "솔레노이드밸브",
    "실린더": "실린더",
    "에어배관": "에어배관·피팅",
    "진공": "진공·석션",
    "배관": "배관·호스",
    "밸브": "밸브·액추에이터",
    "씰": "씰·패킹",
    "탱크": "탱크·용기",
    "펌프": "펌프",
    "필터": "필터",
    "냉동": "냉동·냉각장치",
    "프리저": "동결설비",
    "열교환기": "열교환기",
    "포장자재": "포장자재",
    "제품": "제품·자재",
    "없음": "없음",
}
cat = json.load(open(REPO / "config/classification_catalog.json", encoding="utf-8"))
assert set(CODES.values()) - {"없음"} <= {g["middle"] for g in cat["groups"]}, set(
    CODES.values()
) - {g["middle"] for g in cat["groups"]}
rows = []
for f in sorted(E.glob("gold_labels_*.txt")):
    for line in f.read_text().splitlines():
        parts = line.split()
        gid, labels, amb = int(parts[0]), parts[1].split(","), len(parts) > 2
        rows.append({"gid": gid, "gold": [CODES[x] for x in labels], "ambiguous": amb})
g = pd.DataFrame(rows)
assert g.gid.is_unique
s = pd.read_pickle(E / "gold_sample.pkl").merge(g, on="gid")
s["gold_primary"] = s.gold.str[0]
s.to_pickle(E / "gold.pkl")
print(len(s), "ambiguous", s.ambiguous.sum(), "none", (s.gold_primary == "없음").sum())
print(s.groupby("status").ambiguous.mean().round(2))
