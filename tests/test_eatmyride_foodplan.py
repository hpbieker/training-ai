from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "plugins" / "eatmyride" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from eatmyride_api import (  # noqa: E402
    build_foodplan_with_set_products,
    summarize_foodplan_change,
)


def _product(product_id: int, label: str, unit: str = "piece") -> dict:
    return {
        "id": product_id,
        "label": label,
        "ingredientsQty": 1,
        "ingredientsQtyUnit": unit,
        "carbohydrates": 10000,
        "calories": 40,
    }


class EatMyRideFoodplanTests(unittest.TestCase):
    def test_set_products_expands_pieces_and_preserves_other_items(self) -> None:
        old_piece = _product(10, "Piece")
        drink = _product(20, "Drink", "gram")
        preserved = {"productId": 30, "product": _product(30, "Other")}
        current = [
            {"productId": 10, "product": old_piece},
            {"productId": 10, "product": old_piece},
            preserved,
        ]

        updated = build_foodplan_with_set_products(
            99,
            current,
            [
                {"product_id": 10, "pieces": 3},
                {"product_id": 20, "ml": 500, "gram": 33},
            ],
            {10: old_piece, 20: drink},
        )

        self.assertIn(preserved, updated)
        self.assertEqual(
            sum(event["productId"] == 10 for event in updated),
            3,
        )
        self.assertTrue(
            all(event["gram"] == 1 for event in updated if event["productId"] == 10)
        )
        drink_event = next(event for event in updated if event["productId"] == 20)
        self.assertEqual(drink_event["ml"], 500)
        self.assertEqual(drink_event["gram"], 33)

    def test_pieces_are_spread_evenly_within_period(self) -> None:
        product = _product(10, "Piece")
        updated = build_foodplan_with_set_products(
            99,
            [],
            [{"product_id": 10, "pieces": 4, "start": 100, "end": 200}],
            {10: product},
        )

        self.assertEqual(
            [event["time"] for event in updated],
            [112.5, 137.5, 162.5, 187.5],
        )

    def test_same_product_can_have_multiple_periods(self) -> None:
        product = _product(10, "Piece")
        updated = build_foodplan_with_set_products(
            99,
            [],
            [
                {"product_id": 10, "pieces": 2, "start": 100, "end": 200},
                {"product_id": 10, "pieces": 2, "start": 300, "end": 400},
            ],
            {10: product},
        )

        self.assertEqual(
            [event["time"] for event in updated],
            [125, 175, 325, 375],
        )

    def test_grams_can_be_registered_in_multiple_periods(self) -> None:
        product = _product(20, "Haribo", "gram")
        updated = build_foodplan_with_set_products(
            99,
            [],
            [
                {"product_id": 20, "gram": 50, "start": 100, "end": 200},
                {"product_id": 20, "gram": 75, "start": 300, "end": 500},
            ],
            {20: product},
        )

        self.assertEqual(
            [(event["gram"], event["time"]) for event in updated],
            [(50, 150), (75, 400)],
        )

    def test_set_products_is_idempotent(self) -> None:
        product = _product(10, "Piece")
        item = {"product_id": 10, "pieces": 12}
        first = build_foodplan_with_set_products(99, [], [item], {10: product})
        second = build_foodplan_with_set_products(99, first, [item], {10: product})

        self.assertEqual(len(first), 12)
        self.assertEqual(len(second), 12)
        change = summarize_foodplan_change(first, second, [10])
        self.assertEqual(
            change["products"],
            [
                {
                    "product_id": 10,
                    "events_before": 12,
                    "events_after": 12,
                    "times_before_s": [0] * 12,
                    "times_after_s": [0] * 12,
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
