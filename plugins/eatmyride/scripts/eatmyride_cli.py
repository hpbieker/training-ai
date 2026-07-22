#!/usr/bin/env python3
"""Command-line tool for live EatMyRide API access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eatmyride_api import (
    build_custom_product_payload,
    create_product,
    delete_product,
    get_activity,
    get_foodplan,
    get_suggested_products,
    list_activities,
    list_products,
    load_eatmyride_credentials,
    replace_foodplan,
    summarize_activity,
    summarize_foodplan_events,
    summarize_fueling,
    search_products,
    summarize_foodplan,
    update_product,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Live EatMyRide API tool.")
    parser.add_argument(
        "--env",
        default=".env",
        help="Dotenv file containing EATMYRIDE_EMAIL and EATMYRIDE_PASSWORD",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    activity = subparsers.add_parser("activity", help="Fetch one EatMyRide activity")
    activity.add_argument("activity_id")
    activity.add_argument("--summary", action="store_true", help="Return compact fueling fields")

    foodplan = subparsers.add_parser("foodplan", help="Fetch one activity food plan")
    foodplan.add_argument("activity_id")
    foodplan.add_argument("--summary", action="store_true", help="Include calculated totals")

    fueling = subparsers.add_parser(
        "fueling",
        help="Fetch compact activity energy state and food-plan intake",
    )
    fueling.add_argument("activity_id")
    fueling.add_argument("--summary", action="store_true", required=True, help="Return compact fueling summary")

    day = subparsers.add_parser(
        "activities",
        help="List activities for an inclusive local date range",
    )
    day.add_argument(
        "start_date",
        metavar="start-YYYY-MM-DD",
        help="First local date to include",
    )
    day.add_argument(
        "end_date",
        metavar="end-YYYY-MM-DD",
        help="Last local date to include",
    )

    search = subparsers.add_parser("products-search", help="Search EatMyRide products")
    search.add_argument("query")
    search.add_argument("--filter", dest="product_filter")
    search.add_argument("--limit", type=int, default=10)

    products = subparsers.add_parser("products-custom", help="List custom EatMyRide products")
    products.add_argument("--contains", help="Case-insensitive label/description filter")
    products.add_argument("--limit", type=int, default=50)

    suggested = subparsers.add_parser("products-suggested", help="List suggested products")
    suggested.add_argument("activity_id")
    suggested.add_argument("kind", choices=["food", "drinks"])
    suggested.add_argument("--contains", help="Case-insensitive label/description filter")
    suggested.add_argument("--limit", type=int, default=50)

    replace = subparsers.add_parser(
        "foodplan-replace",
        help="Replace one activity food plan from a reviewed JSON file",
    )
    replace.add_argument("activity_id")
    replace.add_argument("json_file", type=Path)
    replace.add_argument("--yes", action="store_true", help="Confirm replacement")

    create = subparsers.add_parser("product-create", help="Create a custom product")
    create.add_argument("--label", required=True)
    create.add_argument("--weight-grams", type=float, help="Serving weight in grams")
    create.add_argument("--volume-ml", type=float, help="Serving volume in milliliters")
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
        "product-update",
        help="Update a custom product from a reviewed JSON object",
    )
    update.add_argument("product_id")
    update.add_argument("json_file", type=Path)
    update.add_argument("--yes", action="store_true", help="Confirm remote product update")

    delete = subparsers.add_parser("product-delete", help="Delete a custom product")
    delete.add_argument("product_id")
    delete.add_argument("--yes", action="store_true", help="Confirm remote product deletion")

    args = parser.parse_args()

    if args.command == "product-create":
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
            _print_json({"product": product})
            return
        _require_confirmation(args.yes, "Product creation")
        token = _login(args.env)
        _print_json(create_product(product, token=token))
        return

    if args.command == "product-update":
        _require_confirmation(args.yes, "Product update")
        product = _read_json_object(args.json_file)
        token = _login(args.env)
        _print_json(update_product(args.product_id, product, token=token))
        return

    if args.command == "product-delete":
        _require_confirmation(args.yes, "Product deletion")
        token = _login(args.env)
        _print_json({"response": delete_product(args.product_id, token=token)})
        return

    if args.command == "foodplan-replace":
        _require_confirmation(args.yes, "Food-plan replacement")
        foodplan = _read_json_list(args.json_file)
        token = _login(args.env)
        verified = replace_foodplan(args.activity_id, foodplan, token=token)
        _print_json(
            {
                "activity": summarize_activity(verified["activity"]),
                "foodplan": summarize_foodplan_events(verified["foodplan"]),
                "summary": summarize_foodplan(verified["foodplan"]),
            }
        )
        return

    token = _login(args.env)

    if args.command == "activity":
        activity_payload = get_activity(args.activity_id, token=token)
        if args.summary:
            _print_json({"activity": summarize_activity(activity_payload)})
        else:
            _print_json(activity_payload)
        return

    if args.command == "foodplan":
        foodplan_payload = get_foodplan(args.activity_id, token=token)
        if args.summary:
            payload = {
                "foodplan": summarize_foodplan_events(foodplan_payload),
                "summary": summarize_foodplan(foodplan_payload),
            }
        else:
            payload = {"foodplan": foodplan_payload}
        _print_json(payload)
        return

    if args.command == "fueling":
        activity_payload = get_activity(args.activity_id, token=token)
        foodplan_payload = get_foodplan(args.activity_id, token=token)
        _print_json(summarize_fueling(activity_payload, foodplan_payload))
        return

    if args.command == "activities":
        _print_json({"activities": list_activities(args.start_date, args.end_date, token=token)})
        return

    if args.command == "products-search":
        products = search_products(args.query, token=token, product_filter=args.product_filter)
        _print_json({"products": products[: args.limit], "matched_count": len(products)})
        return

    if args.command == "products-custom":
        products = list_products(token=token)
        products = _filter_products(products, args.contains)
        _print_json({"products": products[: args.limit], "matched_count": len(products)})
        return

    if args.command == "products-suggested":
        products = get_suggested_products(args.activity_id, args.kind, token=token)
        products = _filter_products(products, args.contains)
        _print_json({"products": products[: args.limit], "matched_count": len(products)})
        return


def _login(env_path: str) -> str:
    return load_eatmyride_credentials(env_path).login()


def _filter_products(products: list[dict[str, Any]], contains: str | None) -> list[dict[str, Any]]:
    if not contains:
        return products
    needle = contains.casefold()
    return [
        product
        for product in products
        if needle in str(product.get("label") or "").casefold()
        or needle in str(product.get("description") or "").casefold()
    ]


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Expected JSON object: {path}")
    return payload


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit(f"Expected JSON list: {path}")
    return payload


def _require_confirmation(confirmed: bool, action: str) -> None:
    if not confirmed:
        raise SystemExit(f"{action} requires --yes")


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
