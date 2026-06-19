#!/usr/bin/env python3
"""Cache EatMyRide activities and recorded food-plan events."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from eatmyride_api import (
    LOCAL_TIMEZONE,
    build_custom_product_payload,
    cache_activity,
    cache_day,
    cache_latest_activity,
    create_product,
    delete_product,
    get_activity,
    get_foodplan,
    get_suggested_products,
    list_products,
    list_activities_for_day,
    load_eatmyride_credentials,
    replace_foodplan,
    search_products,
    summarize_foodplan,
    update_product,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cache EatMyRide activity details and recorded food-plan events.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    activity = subparsers.add_parser("activity", help="Cache one EatMyRide activity id")
    activity.add_argument("activity_id")

    day = subparsers.add_parser("day", help="Cache activities for one local Oslo date")
    day.add_argument("date", nargs="?", default=datetime.now(LOCAL_TIMEZONE).date().isoformat())

    latest = subparsers.add_parser("latest", help="Cache the latest EatMyRide activity")
    latest.add_argument("--lookback-days", type=int, default=7)

    previous_foodplan = subparsers.add_parser(
        "previous-foodplan",
        help="Find the nearest earlier activity with recorded food or drink",
    )
    previous_foodplan.add_argument(
        "--before",
        default=datetime.now(LOCAL_TIMEZONE).date().isoformat(),
        help="Search strictly before this local Oslo date",
    )
    previous_foodplan.add_argument("--lookback-days", type=int, default=60)

    replace = subparsers.add_parser(
        "replace-foodplan",
        help="Replace one activity food plan from a local JSON file",
    )
    replace.add_argument("activity_id")
    replace.add_argument("json_file", type=Path)
    replace.add_argument("--yes", action="store_true", help="Confirm replacement")

    set_event = subparsers.add_parser(
        "set-event",
        help="Adjust one existing food-plan event and verify the server result",
    )
    set_event.add_argument("activity_id")
    set_event.add_argument("--label", required=True, help="Exact product label")
    set_event.add_argument("--match-time", required=True, type=int, help="Existing time in seconds")
    set_event.add_argument("--time", type=int, help="New time in seconds from activity start")
    set_event.add_argument("--ml", type=int, help="New consumed volume in milliliters")
    set_event.add_argument("--gram", type=int, help="New consumed quantity in grams")
    set_event.add_argument("--yes", action="store_true", help="Confirm replacement")

    search = subparsers.add_parser("search-products", help="Search EatMyRide products")
    search.add_argument("query")
    search.add_argument("--filter", dest="product_filter")
    search.add_argument("--limit", type=int, default=10)

    products = subparsers.add_parser("products", help="List EatMyRide products")
    products.add_argument("--contains", help="Case-insensitive label/description filter")
    products.add_argument("--limit", type=int, default=50)

    suggested = subparsers.add_parser("suggested-products", help="List suggested EatMyRide products")
    suggested.add_argument("activity_id")
    suggested.add_argument("kind", choices=["food", "drinks"])
    suggested.add_argument("--contains", help="Case-insensitive label/description filter")
    suggested.add_argument("--limit", type=int, default=50)

    create = subparsers.add_parser("create-product", help="Create a custom EatMyRide product")
    create.add_argument("--label", required=True)
    create.add_argument("--weight-grams", type=float, help="Product serving weight in grams")
    create.add_argument("--volume-ml", type=float, help="Product serving volume in milliliters")
    create.add_argument("--calories-kcal", type=float, default=0)
    create.add_argument("--carbohydrates-grams", type=float, default=0)
    create.add_argument("--fat-grams", type=float, default=0)
    create.add_argument("--protein-grams", type=float, default=0)
    create.add_argument("--serving-quantity", type=float, default=1)
    create.add_argument("--serving-unit", default="piece", choices=["piece", "gram", "ml"])
    create.add_argument("--tags")
    create.add_argument("--salt-grams", type=float, default=0)
    create.add_argument("--sugars-grams", type=float, default=0)
    create.add_argument("--saturated-fat-grams", type=float, default=0)
    create.add_argument("--fibers-grams", type=float, default=0)
    create.add_argument("--caffeine-mg", type=float, default=0)
    create.add_argument("--per-minute-ms", type=int, default=4000)
    create.add_argument("--dry-run", action="store_true", help="Print payload without posting it")
    create.add_argument("--yes", action="store_true", help="Confirm remote product creation")

    update = subparsers.add_parser(
        "update-product",
        help="Update a custom EatMyRide product from a reviewed JSON object",
    )
    update.add_argument("product_id")
    update.add_argument("json_file", type=Path)
    update.add_argument("--yes", action="store_true", help="Confirm remote product update")

    delete = subparsers.add_parser("delete-product", help="Delete a custom EatMyRide product")
    delete.add_argument("product_id")
    delete.add_argument("--yes", action="store_true", help="Confirm remote product deletion")

    args = parser.parse_args()
    if args.command in {"replace-foodplan", "set-event"}:
        _require_confirmation(args.yes)
    if args.command == "create-product" and not args.dry_run:
        _require_confirmation(args.yes, action="Product creation")
    if args.command == "update-product":
        _require_confirmation(args.yes, action="Product update")
    if args.command == "delete-product":
        _require_confirmation(args.yes, action="Product deletion")

    if args.command == "activity":
        token = load_eatmyride_credentials().login()
        _print_artifacts(cache_activity(args.activity_id, token=token))
        return

    if args.command == "day":
        token = load_eatmyride_credentials().login()
        cached = cache_day(args.date, token=token)
        for artifacts in cached:
            _print_artifacts(artifacts)
        print(f"cached_count: {len(cached)}")
        return

    if args.command == "latest":
        token = load_eatmyride_credentials().login()
        _print_artifacts(cache_latest_activity(token=token, lookback_days=args.lookback_days))
        return

    if args.command == "previous-foodplan":
        token = load_eatmyride_credentials().login()
        result = _previous_foodplan(
            args.before,
            lookback_days=args.lookback_days,
            token=token,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return

    if args.command == "replace-foodplan":
        token = load_eatmyride_credentials().login()
        foodplan = json.loads(args.json_file.read_text(encoding="utf-8"))
        if not isinstance(foodplan, list):
            raise SystemExit("Expected foodplan JSON file to contain a list")
        _replace_and_cache(args.activity_id, foodplan, token=token)
        return

    if args.command == "set-event":
        token = load_eatmyride_credentials().login()
        foodplan = get_foodplan(args.activity_id, token=token)
        event = _find_event(foodplan, label=args.label, match_time=args.match_time)
        if args.time is not None:
            event["time"] = args.time
            event["distance"] = None
        if args.ml is not None:
            event["ml"] = args.ml
        if args.gram is not None:
            event["gram"] = args.gram
        _replace_and_cache(args.activity_id, foodplan, token=token)
        return

    if args.command == "search-products":
        token = load_eatmyride_credentials().login()
        products = search_products(args.query, token=token, product_filter=args.product_filter)
        print(json.dumps(products[: args.limit], ensure_ascii=False, indent=2, sort_keys=True))
        return

    if args.command == "products":
        token = load_eatmyride_credentials().login()
        products = list_products(token=token)
        if args.contains:
            needle = args.contains.casefold()
            products = [
                product
                for product in products
                if needle in str(product.get("label") or "").casefold()
                or needle in str(product.get("description") or "").casefold()
            ]
        print(json.dumps(products[: args.limit], ensure_ascii=False, indent=2, sort_keys=True))
        print(f"matched_count: {len(products)}")
        return

    if args.command == "suggested-products":
        token = load_eatmyride_credentials().login()
        products = get_suggested_products(args.activity_id, args.kind, token=token)
        if args.contains:
            needle = args.contains.casefold()
            products = [
                product
                for product in products
                if needle in str(product.get("label") or "").casefold()
                or needle in str(product.get("description") or "").casefold()
            ]
        print(json.dumps(products[: args.limit], ensure_ascii=False, indent=2, sort_keys=True))
        print(f"matched_count: {len(products)}")
        return

    if args.command == "create-product":
        product = build_custom_product_payload(
            label=args.label,
            weight_grams=args.weight_grams,
            volume_ml=args.volume_ml,
            calories_kcal=args.calories_kcal,
            carbohydrates_grams=args.carbohydrates_grams,
            fat_grams=args.fat_grams,
            protein_grams=args.protein_grams,
            ingredients_qty=args.serving_quantity,
            ingredients_qty_unit=args.serving_unit,
            tags=args.tags,
            salt_grams=args.salt_grams,
            sugars_grams=args.sugars_grams,
            saturated_fat_grams=args.saturated_fat_grams,
            fibers_grams=args.fibers_grams,
            caffeine_mg=args.caffeine_mg,
            per_minute_ms=args.per_minute_ms,
        )
        if args.dry_run:
            print(json.dumps(product, ensure_ascii=False, indent=2, sort_keys=True))
            return
        token = load_eatmyride_credentials().login()
        created = create_product(product, token=token)
        print(json.dumps(created, ensure_ascii=False, indent=2, sort_keys=True))
        print(f"created_product_id: {created.get('id')}")
        print(f"created_product_label: {created.get('label')}")
        return

    if args.command == "update-product":
        product = json.loads(args.json_file.read_text(encoding="utf-8"))
        if not isinstance(product, dict):
            raise SystemExit("Expected product JSON file to contain an object")
        token = load_eatmyride_credentials().login()
        updated = update_product(args.product_id, product, token=token)
        print(json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True))
        print(f"updated_product_id: {updated.get('id')}")
        print(f"updated_product_label: {updated.get('label')}")
        return

    if args.command == "delete-product":
        token = load_eatmyride_credentials().login()
        response = delete_product(args.product_id, token=token)
        print(response)
        return


def _print_artifacts(artifacts: dict[str, Path]) -> None:
    for name, path in artifacts.items():
        print(f"{name}: {path}")


def _replace_and_cache(activity_id: str, foodplan: list[dict[str, Any]], *, token: str) -> None:
    verified = replace_foodplan(activity_id, foodplan, token=token)
    _print_artifacts(cache_activity(activity_id, token=token))
    totals = summarize_foodplan(verified["foodplan"])
    print(f"foodplan_events: {len(verified['foodplan'])}")
    print(f"carbohydrates_grams: {totals['carbohydrates_grams']:.1f}")
    print(f"fluids_ml: {totals['fluids_ml']:.0f}")
    print(
        "server_food_energy_kcal: "
        f"{verified['activity'].get('carbohydratesFromFood')}"
    )


def _previous_foodplan(
    before: str,
    *,
    lookback_days: int,
    token: str,
) -> dict[str, Any]:
    before_date = date.fromisoformat(before)
    checked_activities = 0
    for offset in range(1, lookback_days + 1):
        day = before_date - timedelta(days=offset)
        activities = sorted(
            list_activities_for_day(day, token=token),
            key=lambda item: str(item.get("date") or ""),
            reverse=True,
        )
        for summary in activities:
            activity_id = summary["id"]
            foodplan = get_foodplan(activity_id, token=token)
            checked_activities += 1
            if not foodplan:
                continue
            activity = get_activity(activity_id, token=token)
            return {
                "activity": {
                    "id": activity.get("id"),
                    "label": activity.get("label"),
                    "date": activity.get("date"),
                    "duration": activity.get("duration"),
                    "distance": activity.get("distance"),
                    "sport": activity.get("sport"),
                    "subSport": activity.get("subSport"),
                    "tracker": activity.get("tracker"),
                    "carbohydratesFromFood": activity.get("carbohydratesFromFood"),
                    "usedBalancer": activity.get("usedBalancer"),
                },
                "foodplan_events": len(foodplan),
                "products": sorted(
                    {
                        event.get("product", {}).get("label")
                        for event in foodplan
                        if event.get("product", {}).get("label")
                    }
                ),
                "events": [
                    {
                        "time": event.get("time"),
                        "distance": event.get("distance"),
                        "label": event.get("product", {}).get("label"),
                        "ml": event.get("ml"),
                        "gram": event.get("gram"),
                    }
                    for event in foodplan
                ],
                "checked_activities": checked_activities,
            }
    raise SystemExit(
        f"No earlier EatMyRide food plan found in the last {lookback_days} days"
    )


def _find_event(
    foodplan: list[dict[str, Any]],
    *,
    label: str,
    match_time: int,
) -> dict[str, Any]:
    matches = [
        event
        for event in foodplan
        if event.get("time") == match_time
        and event.get("product", {}).get("label") == label
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"Expected exactly one event for {label!r} at {match_time}s, got {len(matches)}"
        )
    return matches[0]


def _require_confirmation(confirmed: bool, *, action: str = "Food-plan replacement") -> None:
    if not confirmed:
        raise SystemExit(f"{action} requires --yes")


if __name__ == "__main__":
    main()
