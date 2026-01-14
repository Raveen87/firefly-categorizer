from datetime import datetime, timedelta

from firefly_categorizer.integration.firefly import FireflyClient


def is_all_scope(scope: str | None) -> bool:
    return (scope or "").lower() == "all"


def resolve_date_range(
    start_date: str | None,
    end_date: str | None,
    scope: str | None,
) -> tuple[datetime | None, datetime | None]:
    if is_all_scope(scope):
        return None, None

    if not start_date:
        start_date_obj = datetime.now() - timedelta(days=30)
    else:
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")

    if not end_date:
        end_date_obj = datetime.now()
    else:
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

    return start_date_obj, end_date_obj


async def fetch_category_names(
    firefly: FireflyClient,
    *,
    sort: bool = False,
) -> list[str]:
    raw_cats = await firefly.get_categories()
    categories = [c["attributes"]["name"] for c in raw_cats] if raw_cats else []
    return sorted(categories) if sort else categories
