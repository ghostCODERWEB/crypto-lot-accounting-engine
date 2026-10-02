"""Track inventory lots, partial disposals, transfer continuity and realized cost basis under FIFO and LIFO."""

from decimal import Decimal, localcontext
from .validation import decimal, identifier, chronological
import copy


class Inventory:
    def __init__(self, method):
        if method not in ("FIFO", "LIFO"):
            raise ValueError("unsupported lot method")
        self.method = method
        self.lots = []
        self.disposals = []
        self.ids = set()

    def acquire(self, e):
        key = identifier(e["id"])
        if key in self.ids:
            raise ValueError("duplicate lot id")
        self.ids.add(key)
        quantity = decimal(e["quantity"], positive=True)
        cost = decimal(e["cost"]) + decimal(e.get("fee", 0))
        self.lots.append(
            {
                "id": key,
                "asset": identifier(e["asset"]),
                "wallet": identifier(e["wallet"]),
                "quantity": quantity,
                "unit_cost": cost / quantity,
                "timestamp": e["timestamp"],
            }
        )

    def consume(self, asset, wallet, quantity, method=None):
        candidates = [
            l
            for l in self.lots
            if l["asset"] == asset and l["wallet"] == wallet and l["quantity"] > 0
        ]
        candidates.sort(
            key=lambda l: (l["timestamp"], l["id"]),
            reverse=(method or self.method) == "LIFO",
        )
        if sum(l["quantity"] for l in candidates) < quantity:
            raise ValueError("insufficient lot inventory")
        consumed = []
        remaining = quantity
        for lot in candidates:
            amount = min(remaining, lot["quantity"])
            if amount:
                lot["quantity"] -= amount
                remaining -= amount
                consumed.append({**lot, "quantity": amount})
            if remaining == 0:
                break
        return consumed

    def apply(self, e):
        kind = e["type"]
        if kind == "acquire":
            self.acquire(e)
            return {"type": kind, "id": e["id"]}
        if kind == "dispose":
            amount = decimal(e["quantity"], positive=True)
            parts = self.consume(e["asset"], e["wallet"], amount)
            basis = sum(p["quantity"] * p["unit_cost"] for p in parts)
            proceeds = decimal(e["proceeds"])
            fee = decimal(e.get("fee", 0))
            gain = proceeds - fee - basis
            record = {
                "id": identifier(e["id"]),
                "asset": e["asset"],
                "quantity": str(amount),
                "cost_basis": str(basis),
                "net_proceeds": str(proceeds - fee),
                "realized_gain": str(gain),
                "lots": [
                    {
                        "id": p["id"],
                        "quantity": str(p["quantity"]),
                        "basis": str(p["quantity"] * p["unit_cost"]),
                    }
                    for p in parts
                ],
            }
            self.disposals.append(record)
            return {"type": kind, **record}
        if kind == "transfer":
            target = identifier(e["to_wallet"])
            source = identifier(e["from_wallet"])
            key = identifier(e["id"])
            if key in self.ids or source == target:
                raise ValueError("invalid transfer identity")
            self.ids.add(key)
            parts = self.consume(
                e["asset"], source, decimal(e["quantity"], positive=True)
            )
            for index, part in enumerate(parts):
                self.lots.append(
                    {**part, "id": key + ":" + str(index), "wallet": target}
                )
            return {"type": kind, "parts": len(parts), "realized_gain": "0"}
        raise ValueError("unknown lot event")


def analyze(data):
    with localcontext() as ctx:
        ctx.prec = 50
        book = Inventory(data.get("method", "FIFO"))
        events = [book.apply(e) for e in chronological(data["events"])]
        positions = {}
        for lot in book.lots:
            if lot["quantity"] == 0:
                continue
            key = lot["wallet"] + ":" + lot["asset"]
            position = positions.setdefault(
                key, {"quantity": Decimal(0), "basis": Decimal(0)}
            )
            position["quantity"] += lot["quantity"]
            position["basis"] += lot["quantity"] * lot["unit_cost"]
        lots = [
            {**l, "quantity": str(l["quantity"]), "unit_cost": str(l["unit_cost"])}
            for l in book.lots
            if l["quantity"] > 0
        ]
        return {
            "method": book.method,
            "positions": {
                k: {f: str(v) for f, v in p.items()} for k, p in positions.items()
            },
            "lots": lots,
            "disposals": book.disposals,
            "realized_gain": str(
                sum((Decimal(d["realized_gain"]) for d in book.disposals), Decimal(0))
            ),
            "events": events,
        }
