"""Register an explicitly reviewed broker instrument specification; never infer values."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import get_settings  # noqa: E402
from app.database import open_database  # noqa: E402

ACK = "I REVIEWED THE AUTHORITATIVE INSTRUMENT SPECIFICATION"

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", required=True)
    parser.add_argument("--epic", required=True)
    parser.add_argument("--minimum-size", type=Decimal, required=True)
    parser.add_argument("--size-increment", type=Decimal, required=True)
    parser.add_argument("--minimum-stop-distance", type=Decimal, required=True)
    parser.add_argument("--value-per-point-zar", type=Decimal, required=True)
    parser.add_argument("--margin-factor-pct", type=Decimal, required=True)
    parser.add_argument("--evidence-source", required=True)
    parser.add_argument("--verified-at", required=True)
    parser.add_argument("--revalidate-at", required=True)
    parser.add_argument("--reviewer-email", required=True)
    parser.add_argument("--acknowledgement", required=True)
    args = parser.parse_args()
    if args.acknowledgement != ACK:
        raise SystemExit("Exact administrator review acknowledgement is required")
    verified = datetime.fromisoformat(args.verified_at.replace("Z", "+00:00"))
    revalidate = datetime.fromisoformat(args.revalidate_at.replace("Z", "+00:00"))
    if verified.tzinfo is None or revalidate.tzinfo is None or revalidate <= datetime.now(timezone.utc):
        raise SystemExit("Timezone-aware verification and future revalidation timestamps are required")
    values = (args.minimum_size, args.size_increment, args.minimum_stop_distance,
              args.value_per_point_zar, args.margin_factor_pct)
    if any(value <= 0 for value in values):
        raise SystemExit("All reviewed numeric values must be positive")
    evidence = {key: str(value) for key, value in vars(args).items() if key != "acknowledgement"}
    digest = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    settings = get_settings()
    with open_database(settings) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT market_id,ig_epic FROM app.markets WHERE symbol=%s AND enabled=1", (args.market.upper(),))
        market = cursor.fetchone()
        cursor.execute("SELECT user_id FROM app.users WHERE email=%s AND role IN ('owner','administrator','admin') AND status='active'", (args.reviewer_email.lower(),))
        reviewer = cursor.fetchone()
        if not market or str(market[1]) != args.epic or not reviewer:
            raise SystemExit("Enabled market/epic and active administrator reviewer must match")
        cursor.execute("SELECT COALESCE(MAX(version),0)+1 FROM app.instrument_specification_overrides WHERE market_id=%s", (str(market[0]),))
        version = int(cursor.fetchone()[0])
        cursor.execute("UPDATE app.instrument_specification_overrides SET status='REVOKED' WHERE market_id=%s AND status='APPROVED'", (str(market[0]),))
        cursor.execute("""INSERT app.instrument_specification_overrides
          (instrument_specification_override_id,market_id,version,epic,minimum_size,
           authoritative_size_increment,minimum_stop_distance,value_per_point_zar,margin_factor_pct,
           evidence_source,evidence_sha256,verified_at_utc,reviewed_by_user_id,
           review_acknowledgement,revalidate_at_utc,status)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'APPROVED')""",
          (str(uuid4()),str(market[0]),version,args.epic,*values,args.evidence_source,digest,
           verified.astimezone(timezone.utc),str(reviewer[0]),ACK,revalidate.astimezone(timezone.utc)))
        cursor.execute("""UPDATE app.broker_market_rules SET size_increment=%s,
          size_increment_source=%s,size_increment_authoritative=1 WHERE market_id=%s""",
          (args.size_increment,f"ADMIN_OVERRIDE_V{version}",str(market[0])))
        connection.commit()
    print(json.dumps({"status":"APPROVED","market":args.market.upper(),"version":version,
                      "evidence_sha256":digest,"execution_enabled":False}))
