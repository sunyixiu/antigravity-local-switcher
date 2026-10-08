"""Project offline window recovery without mutating confirmed quota caches."""
import copy
import math

import auto_refresh


def project(cache, now, offline):
    result = copy.deepcopy(cache)
    estimates = 0
    updated = cache.get("updated")
    if type(updated) not in (float, int) or not math.isfinite(updated):
        updated = None
    for row in result.get("groups", []):
        value = row.get("percentage")
        due = auto_refresh.reset_epoch(row.get("reset"))
        if (offline and row.get("family") in ("gemini", "thirdparty") and row.get("window") in ("weekly", "5h")
                and type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 100
                and updated is not None and due is not None and updated < due <= now):
            row["confirmed_percentage"] = value
            row["estimated"] = True
            row["percentage"] = 100
            estimates += 1
    result["offline"] = bool(offline)
    result["has_estimates"] = estimates > 0
    return result
