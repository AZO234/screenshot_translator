import json
import os
import hashlib
from datetime import datetime

USAGE_FILE = "usage_stats.json"

def _get_key_hash(api_key):
    """APIキーをハッシュ化して識別子を作成する"""
    if not api_key:
        return "unknown"
    return hashlib.sha256(api_key.encode()).hexdigest()[:12]

def _load_all_stats():
    if os.path.exists(USAGE_FILE):
        try:
            with open(USAGE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def _save_all_stats(stats):
    with open(USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

def _get_current_stats(api_key):
    all_stats = _load_all_stats()
    key_hash = _get_key_hash(api_key)
    current_month = datetime.now().strftime("%Y-%m")
    
    # キーごとのデータがなければ作成
    if key_hash not in all_stats:
        all_stats[key_hash] = {}
    
    # 月ごとのデータがなければ作成（リセット）
    if current_month not in all_stats[key_hash]:
        all_stats[key_hash][current_month] = {
            "vision_units": 0,
            "translation_chars": 0
        }
    
    return all_stats, key_hash, current_month

def record_vision(api_key, units=1):
    all_stats, key_hash, month = _get_current_stats(api_key)
    all_stats[key_hash][month]["vision_units"] += units
    _save_all_stats(all_stats)

def record_translation(api_key, text_list):
    all_stats, key_hash, month = _get_current_stats(api_key)
    chars = sum(len(text) for text in text_list)
    all_stats[key_hash][month]["translation_chars"] += chars
    _save_all_stats(all_stats)

def get_current_usage(api_key):
    all_stats, key_hash, month = _get_current_stats(api_key)
    return {
        "month": month,
        "key_id": key_hash,
        **all_stats[key_hash][month]
    }
