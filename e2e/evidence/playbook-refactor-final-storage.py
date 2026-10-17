import json
import os
from pathlib import Path
from money import line_total


def _stage_rows(current, batches):
    seen = {row["id"] for row in current}
    staged = list(current)
    for batch in batches:
        for row in batch:
            if row["id"] in seen:
                raise ValueError("duplicate transaction: " + row["id"])
            if any(type(row[k]) is not int or row[k] < 0
                   for k in ("quantity", "unit_price_cents", "discount_bp")):
                raise ValueError("invalid money field")
            if row["discount_bp"] > 10000:
                raise ValueError("invalid discount")
            seen.add(row["id"])
            staged.append(dict(row, total_cents=line_total(
                row["quantity"], row["unit_price_cents"], row["discount_bp"])))
    return staged


def apply_batch(store, batches):
    path = Path(store)
    current = json.loads(path.read_text()) if path.exists() else []
    staged = _stage_rows(current, batches)
    temporary = path.with_suffix(".pending")
    temporary.write_text(json.dumps(staged, sort_keys=True))
    os.replace(temporary, path)
    return {"count": len(staged), "total_cents": sum(r["total_cents"] for r in staged)}
