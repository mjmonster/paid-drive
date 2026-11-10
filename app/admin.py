"""Local operator tools. No administrative endpoints are exposed over HTTP."""
import argparse
import json

from .access import audit, enqueue_link, now
from .config import Settings
from .db import Database


def main():
    parser = argparse.ArgumentParser(description="PaidDrive local support tools")
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list-orders", help="List recent order references without buyer email or credentials")
    listing.add_argument("--limit", type=int, default=20)
    for command in ("restore", "revoke"):
        p = sub.add_parser(command)
        p.add_argument("--reference", required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    settings.validate()
    db = Database(settings.database_path)
    with db.transaction() as con:
        if args.command == "list-orders":
            records = con.execute("SELECT o.reference,o.collection_id,o.version,o.amount_cents,o.status,o.mode,o.created_at,o.paid_at,p.revoked_at FROM orders o LEFT JOIN purchases p ON p.order_id=o.id WHERE o.mode=? ORDER BY o.created_at DESC LIMIT ?", (settings.app_mode, max(1, min(args.limit, 200)))).fetchall()
            print(json.dumps([dict(r) for r in records], indent=2))
            return
        order = con.execute("SELECT * FROM orders WHERE reference=? AND mode=?", (args.reference, settings.app_mode)).fetchone()
        if not order:
            parser.error("No matching order in the selected APP_MODE")
        purchase = con.execute("SELECT * FROM purchases WHERE order_id=?", (order["id"],)).fetchone()
        if not purchase or order["status"] != "paid":
            parser.error("Only a verified, paid purchase can be restored or revoked")
        if args.command == "revoke":
            con.execute("UPDATE purchases SET revoked_at=? WHERE id=?", (now(), purchase["id"]))
            con.execute("UPDATE recovery_tokens SET used_at=? WHERE purchase_id=? AND used_at IS NULL", (now(), purchase["id"]))
            audit(con, "support_revoked", order["reference"])
            print("Hosted access revoked. This does not issue a payment refund or remove previously downloaded files.")
        else:
            if purchase["revoked_at"]:
                parser.error("This purchase has been revoked")
            con.execute("UPDATE recovery_tokens SET used_at=? WHERE purchase_id=? AND purpose='manual' AND used_at IS NULL", (now(), purchase["id"]))
            url = enqueue_link(con, settings, purpose="manual", purchase_id=purchase["id"], ttl=900)
            audit(con, "support_recovery_issued", order["reference"])
            print("Share this one-use, 15-minute link only after verifying payment ownership against merchant records:")
            print(url)


if __name__ == "__main__":
    main()
