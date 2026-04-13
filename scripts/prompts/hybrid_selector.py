# hybrid_selector.py — 冒頭/結末パターン + テーマカテゴリのハイブリッド選択
#
# 冒頭6パターン x 結末5パターン x テーマカテゴリ5種のローテーションに
# テーマ相性チェックを掛け合わせ、量産型回避と視聴体験の最適化を両立する。
#
# 状態は state/creatures_rotation.json で永続化。

import json
import os
import re
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STATE_DIR = BASE_DIR / "state"
STATE_FILE = STATE_DIR / "creatures_rotation.json"

# ── テーマカテゴリ定義（物語の切り口） ──────────────────────

THEME_CATEGORIES = {
    "A": {
        "name": "壮絶サバイバー",
        "description": "過酷な環境・天敵・低生存率と戦う生き物の物語",
        "keywords": [
            "サバイバル", "過酷", "砂漠", "極地", "深海", "天敵", "絶滅危惧",
            "生存率", "氷河期", "猛毒", "ゴキブリ", "クマムシ", "ラーテル",
            "サソリ", "ヤドカリ", "カンガルー", "シャチ",
        ],
    },
    "B": {
        "name": "意外な身近生き物",
        "description": "身近にいるのに知られていない驚きの生態を持つ生き物",
        "keywords": [
            "身近", "庭", "公園", "都市", "家", "ペット", "カラス", "スズメ",
            "ネコ", "イヌ", "ハト", "セミ", "アリ", "ダンゴムシ", "クモ",
            "ミミズ", "トンボ", "カタツムリ", "ゴキブリ", "ネズミ",
        ],
    },
    "C": {
        "name": "命がけの繁殖",
        "description": "繁殖のために命を懸ける生き物の壮絶なドラマ",
        "keywords": [
            "繁殖", "産卵", "求愛", "子育て", "交尾", "ハーレム", "巣",
            "カマキリ", "サケ", "ウミガメ", "ペンギン", "タツノオトシゴ",
            "クジャク", "ホタル", "アンコウ", "ミツバチ",
        ],
    },
    "D": {
        "name": "驚きの能力者",
        "description": "驚異的な能力・特殊な進化を持つ生き物",
        "keywords": [
            "能力", "進化", "擬態", "再生", "電気", "毒", "超音波",
            "カメレオン", "タコ", "デンキウナギ", "モンハナシャコ",
            "ハヤブサ", "チーター", "ミミックオクトパス", "プラナリア",
            "ラフレシア", "テッポウエビ",
        ],
    },
    "E": {
        "name": "旅する生き物",
        "description": "長距離の移動・渡り・大回遊で知られる生き物",
        "keywords": [
            "渡り", "移動", "回遊", "旅", "大陸", "季節",
            "ツバメ", "クジラ", "ウナギ", "オオカバマダラ", "ヌー",
            "サケ", "アホウドリ", "キョクアジサシ", "レミング",
            "カリブー", "マグロ",
        ],
    },
}

# ── 相性マトリクス ──────────────────────────────────────────
# 値: 2=推奨, 0=中立, -2=非推奨
# 冒頭パターン × テーマカテゴリ

OPENING_AFFINITY = {
    #          壮絶  身近  繁殖  能力  旅
    "A": {"A":  0, "B":  0, "C":  0, "D":  2, "E":  0},  # 魔理沙の発見 → 驚き能力と好相性
    "B": {"A":  0, "B":  2, "C":  0, "D":  0, "E":  0},  # 霊夢の悩みリンク → 身近と好相性
    "C": {"A":  2, "B":  0, "C":  0, "D":  2, "E":  0},  # 衝撃の事実 → サバイバー/能力と好相性
    "D": {"A":  0, "B":  2, "C":  0, "D":  0, "E":  0},  # 霊夢の勘違い → 身近と好相性
    "E": {"A":  0, "B":  2, "C":  0, "D":  0, "E":  2},  # ニュース導入 → 身近/旅と好相性
    "F": {"A":  2, "B": -2, "C":  2, "D":  0, "E":  2},  # 途中から → サバイバー/繁殖/旅と好相性、身近は非推奨
}

# 結末パターン × テーマカテゴリ

ENDING_AFFINITY = {
    #          壮絶  身近  繁殖  能力  旅
    "1": {"A":  2, "B":  0, "C":  2, "D":  0, "E":  2},  # 達成型 → サバイバー/繁殖/旅と好相性
    "2": {"A":  2, "B":  0, "C":  0, "D":  2, "E":  0},  # 転換型 → サバイバー/能力と好相性
    "3": {"A":  0, "B":  0, "C":  2, "D":  0, "E":  0},  # 継承型 → 繁殖と好相性
    "4": {"A":  2, "B":  0, "C":  0, "D":  0, "E":  2},  # 認知型 → サバイバー/旅と好相性
    "5": {"A":  0, "B":  2, "C":  0, "D":  0, "E":  0},  # 日常回帰型 → 身近と好相性
}

OPENING_ORDER = ["A", "B", "C", "D", "E", "F"]
ENDING_ORDER = ["1", "2", "3", "4", "5"]
CATEGORY_ORDER = ["A", "B", "C", "D", "E"]


# ── 状態管理 ────────────────────────────────────────────────

def _load_state() -> dict:
    """ローテーション状態を読み込む。ファイルがなければ初期状態を返す。"""
    if not STATE_FILE.exists():
        return {
            "last_opening": None,
            "last_ending": None,
            "last_category": None,
            "history": [],
        }
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"last_opening": None, "last_ending": None, "last_category": None, "history": []}
        return data
    except (json.JSONDecodeError, OSError):
        return {"last_opening": None, "last_ending": None, "last_category": None, "history": []}


def _save_state(state: dict) -> None:
    """ローテーション状態を保存する。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(str(tmp), str(STATE_FILE))


# ── テーマカテゴリ分類 ──────────────────────────────────────

def classify_theme(theme: str) -> str:
    """テーマ名からカテゴリをキーワードマッチで推定する。

    一致しない場合は最も使用頻度の低いカテゴリを返す（均等分散）。

    Returns:
        カテゴリID ("A"〜"E")
    """
    theme_lower = theme.lower()
    scores = {}
    for cat_id, cat in THEME_CATEGORIES.items():
        score = 0
        for kw in cat["keywords"]:
            if kw.lower() in theme_lower or kw in theme:
                score += 1
        scores[cat_id] = score

    best = max(scores.values())
    if best > 0:
        # 最高スコアのカテゴリを返す（同点ならIDが若い方）
        for cat_id in CATEGORY_ORDER:
            if scores[cat_id] == best:
                return cat_id

    # キーワードマッチなし → 使用頻度の低いカテゴリを割り当て
    state = _load_state()
    usage = {c: 0 for c in CATEGORY_ORDER}
    for h in state.get("history", []):
        cat = h.get("category", "")
        if cat in usage:
            usage[cat] += 1
    min_usage = min(usage.values())
    for cat_id in CATEGORY_ORDER:
        if usage[cat_id] == min_usage:
            return cat_id
    return "A"


# ── メイン選択ロジック ──────────────────────────────────────

def _next_in_rotation(order: list, last_used: str | None) -> list:
    """ローテーション順で次の候補リストを返す（last_used の次から順に）。"""
    if last_used is None or last_used not in order:
        return list(order)
    idx = order.index(last_used)
    return order[idx + 1:] + order[:idx + 1]


def select_pattern(theme: str) -> dict:
    """テーマに対して最適な冒頭/結末パターンを選択する。

    ローテーション（前回の次）をベースに、相性マトリクスで非推奨を回避する。

    Args:
        theme: 生き物のテーマ名

    Returns:
        {"opening": "A"〜"F", "ending": "1"〜"5", "category": "A"〜"E"}
    """
    state = _load_state()
    category = classify_theme(theme)

    # 冒頭パターン選択: ローテーション順の候補を相性でフィルタ
    opening_candidates = _next_in_rotation(OPENING_ORDER, state.get("last_opening"))
    opening = opening_candidates[0]  # デフォルト
    for candidate in opening_candidates:
        affinity = OPENING_AFFINITY.get(candidate, {}).get(category, 0)
        if affinity >= 0:
            opening = candidate
            break
    else:
        opening = opening_candidates[0]  # 全て非推奨なら最初の候補

    # 結末パターン選択: ローテーション順の候補を相性でフィルタ
    ending_candidates = _next_in_rotation(ENDING_ORDER, state.get("last_ending"))
    ending = ending_candidates[0]  # デフォルト
    for candidate in ending_candidates:
        affinity = ENDING_AFFINITY.get(candidate, {}).get(category, 0)
        if affinity >= 0:
            ending = candidate
            break
    else:
        ending = ending_candidates[0]

    # 状態を更新して保存
    state["last_opening"] = opening
    state["last_ending"] = ending
    state["last_category"] = category
    history = state.get("history", [])
    history.append({
        "theme": theme,
        "opening": opening,
        "ending": ending,
        "category": category,
        "date": datetime.now().strftime("%Y-%m-%d"),
    })
    # 履歴は直近50件まで保持
    state["history"] = history[-50:]
    _save_state(state)

    return {"opening": opening, "ending": ending, "category": category}


def get_category_name(category_id: str) -> str:
    """カテゴリIDからカテゴリ名を返す。"""
    cat = THEME_CATEGORIES.get(category_id)
    return cat["name"] if cat else "不明"
