"""
Таблицы лута для survival-локаций.
Ключ -> список исходов с весом.
"""
from __future__ import annotations

import random
from typing import Dict, List, Tuple


LOOT_TABLES: Dict[str, List[Tuple[str, int, int, int]]] = {
    # key, weight, min_qty, max_qty
    "forest_basic": [
        ("resource_wood", 60, 1, 4),
        ("resource_stone", 25, 1, 2),
        ("resource_scrap", 10, 1, 1),
        ("resource_metal", 5, 1, 1),
    ],
    "quarry_basic": [
        ("resource_stone", 55, 2, 5),
        ("resource_scrap", 25, 1, 2),
        ("resource_metal", 15, 1, 2),
        ("resource_wood", 5, 1, 1),
    ],
    "bunker_rare": [
        ("resource_scrap", 45, 2, 4),
        ("resource_metal", 35, 1, 3),
        ("resource_stone", 15, 1, 2),
        ("resource_wood", 5, 1, 1),
    ],
}


def roll_loot(loot_table_key: str) -> dict:
    """
    Возвращает один исход лута:
    {"item_key": str, "qty": int}
    """
    table = LOOT_TABLES.get(loot_table_key) or LOOT_TABLES["forest_basic"]
    total_weight = sum(row[1] for row in table)
    pick = random.randint(1, total_weight)
    cursor = 0
    for item_key, weight, min_qty, max_qty in table:
        cursor += weight
        if pick <= cursor:
            return {"item_key": item_key, "qty": random.randint(min_qty, max_qty)}
    # fallback на случай неконсистентной таблицы
    return {"item_key": "resource_wood", "qty": 1}
