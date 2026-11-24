from app.business import decision


def policy(result):
    return decision(result, "OFFSET_LIMIT" if result["flag"] else None)
