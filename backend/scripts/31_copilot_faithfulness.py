import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Important: Setup the DB and Copilot context
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from nexafreight.models import Shipment
from nexafreight.services.copilot import answer_shipment_question, load_shipment_context, needs_llm
from nexafreight.eval.faithfulness import extract_numbers, faithfulness_rate
from nexafreight.services.alert_engine import latest_planned_arrival
from nexafreight.services.financial_engine import DEMURRAGE_DAILY_RATE, DEMURRAGE_FREE_DAYS, calculate_demurrage
import subprocess

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

UTC = timezone.utc

def get_git_sha():
    try:
        return subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode('ascii').strip()
    except Exception:
        return "unknown"

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=25, help="Number of shipments")
    args = parser.parse_args()
    
    # 1) Resolve and guard DATABASE_URL
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        db_url = "sqlite+aiosqlite:///eval_artifacts_scratch.db"
        print("DATABASE_URL unset, defaulting to sqlite+aiosqlite:///eval_artifacts_scratch.db")
    
    if "sqlite" not in db_url:
        print("REPORT > SCRIPT 31 REFUSED: DATABASE_URL is not sqlite - dummy-fixture run forbidden on real DB")
        sys.exit(2)
        
    engine = create_async_engine(db_url)
    
    async with engine.begin() as conn:
        from nexafreight.models import Base
        await conn.run_sync(Base.metadata.create_all)
        
    SessionLocal = sessionmaker(class_=AsyncSession, autocommit=False, autoflush=False, bind=engine)
    
    async with SessionLocal() as session:
        from nexafreight.models import Shipment, Order, Leg, Location
        import random
        from datetime import timedelta
        
        # Create Nodes
        orig_id = 1
        dest_id = 2
        session.add(Location(id=orig_id, name="Origin Port", locode="ORPOR", country_code="IN", location_type="PORT", lat=0.0, lon=0.0))
        session.add(Location(id=dest_id, name="Dest Port", locode="DEPOR", country_code="IN", location_type="PORT", lat=0.0, lon=0.0))
        await session.flush()
        
        # Insert N dummy shipments
        for i in range(args.n):
            now = datetime.now(UTC)
            ship = Shipment(
                origin_id=orig_id,
                destination_id=dest_id,
                status="IN_TRANSIT",
                primary_transport_mode="SEA",
                cargo_class="GENERAL",
                container_count=random.randint(1, 10),
                planned_departure=now - timedelta(days=10),
                provenance="TEST"
            )
            session.add(ship)
            await session.flush()
            
            # Orders
            order = Order(
                shipment_id=ship.id,
                order_number=f"ORD-{i}",
                revenue=random.uniform(5000, 20000),
                shipping_cost=random.uniform(1000, 5000),
                sla_status="AT_RISK",
                sla_deadline=now + timedelta(days=5),
                shipping_mode="Standard Class",
                cargo_class="GENERAL"
            )
            session.add(order)
            
            # Legs
            leg = Leg(
                shipment_id=ship.id,
                sequence_number=1,
                route_version=1,
                transport_mode="SEA",
                status="IN_TRANSIT",
                origin_id=orig_id,
                destination_id=dest_id,
                distance_km=random.uniform(1000, 5000),
                planned_departure=now,
                planned_arrival=now + timedelta(days=2),
                provenance="TEST"
            )
            session.add(leg)
            
        await session.commit()
        
        from sqlalchemy import select
        # 2) Select up to N shipments
        stmt = select(Shipment).limit(args.n)
        result = await session.execute(stmt)
        shipments = result.scalars().all()
            
        questions = [
            "What is the ETA status of this shipment?",
            "What is the demurrage exposure?",
            "Summarize this shipment's risk"
        ]
        
        results = []
        
        for shipment in shipments:
            # Recompute load_shipment_context
            # Need eager loads first
            await session.refresh(shipment, ["legs", "orders", "alerts", "origin", "destination"])
            context = load_shipment_context(shipment)
            
            # RECOMPUTATION OF PRIVATE HELPERS _rules_answer AND _demurrage_answer
            # Documented: Recomputing Delivery Status (_rules_answer)
            orders = shipment.orders
            eta = latest_planned_arrival(shipment)
            now = datetime.now(UTC)
            if eta is not None and eta.tzinfo is None:
                eta = eta.replace(tzinfo=UTC)
            
            if orders:
                order = min(orders, key=lambda o: o.sla_deadline)
                deadline = order.sla_deadline
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=UTC)
                if eta and eta > deadline:
                    days = max(1, (eta - deadline).days)
                    base_eta_status = (
                        f"SLA breach: order {order.order_number} misses its deadline "
                        f"{deadline:%Y-%m-%d} by ~{days} day(s) "
                        f"(latest planned arrival {eta:%Y-%m-%d})."
                    )
                else:
                    eta_text = f"{eta:%Y-%m-%d}" if eta else "unknown"
                    base_eta_status = (
                        f"On track: order {order.order_number} due {deadline:%Y-%m-%d}; "
                        f"current ETA {eta_text} ({str(order.sla_status).lower()})."
                    )
            elif eta is None:
                base_eta_status = "No schedule data is available for this shipment yet."
            else:
                days_out = max(0, (eta - now).days)
                base_eta_status = (
                    f"Shipment {shipment.id} is currently estimated to arrive {eta:%Y-%m-%d} "
                    f"(~{days_out} day(s) out)."
                )

            # Documented: Recomputing Demurrage (_demurrage_answer)
            dwell_days = 0
            if eta is not None:
                dwell_days = max(0, (now - eta).days)
            per_container = calculate_demurrage(
                extra_days=dwell_days,
                free_days=DEMURRAGE_FREE_DAYS,
                daily_rate=DEMURRAGE_DAILY_RATE,
            )
            total = per_container * max(1, shipment.container_count)
            base_demurrage = (
                f"Demurrage exposure: ~${total:,.0f} "
                f"({shipment.container_count} container(s) × "
                f"${DEMURRAGE_DAILY_RATE:,.0f}/day after {DEMURRAGE_FREE_DAYS} free days; "
                f"current port dwell {dwell_days} day(s) past planned arrival)."
            )

            # Extract allowed numbers
            allowed_nums = extract_numbers(json.dumps(context))
            allowed_nums.extend(extract_numbers(base_eta_status))
            allowed_nums.extend(extract_numbers(base_demurrage))
            
            for q in questions:
                # Need to use ask_copilot
                ans_dict = await answer_shipment_question(session, shipment=shipment, question=q)
                ans = ans_dict["answer"]
                path = ans_dict["source"]
                if path == "rules_fallback":
                    path = "rules"
                    
                results.append({
                    "question": q,
                    "answer": ans,
                    "allowed_numbers": allowed_nums,
                    "path": path,
                    "model": "gemini" if path == "llm" else None # simplifying model name
                })
                
    # Process with faithfulness_rate
    results_llm = [r for r in results if r["path"] == "llm"]
    results_rules = [r for r in results if r["path"] == "rules"]
    
    stats_llm = faithfulness_rate(results_llm)
    stats_rules = faithfulness_rate(results_rules)
    
    llm_ok = False
    rules_ok = False
    llm_poor = False
    rules_poor = False
    
    llm_rate = stats_llm['rate'] * 100
    if stats_llm['total'] >= 10 and stats_llm['passed'] == stats_llm['total']:
        llm_ok = True
    elif llm_rate < 80 and stats_llm['total'] > 0:
        llm_poor = True
        
    rules_rate = stats_rules['rate'] * 100
    if stats_rules['total'] >= 10 and stats_rules['passed'] == stats_rules['total']:
        rules_ok = True
    elif rules_rate < 80 and stats_rules['total'] > 0:
        rules_poor = True
        
    verdict = "MIXED"
    if llm_ok and rules_ok:
        verdict = "OK"
    elif llm_poor or rules_poor:
        verdict = "POOR"
        
    hallucinated = (stats_llm['total'] - stats_llm['passed']) + (stats_rules['total'] - stats_rules['passed'])
    
    if stats_llm['total'] == 0:
        print("REPORT > COPILOT faithfulness (llm): SKIPPED (no adapter)")
    else:
        print(f"REPORT > COPILOT faithfulness (llm): {stats_llm['passed']}/{stats_llm['total']} ({llm_rate:.1f}%)")
        
    if stats_rules['total'] == 0:
        print("REPORT > COPILOT faithfulness (rules): SKIPPED (no answers)")
    else:
        print(f"REPORT > COPILOT faithfulness (rules): {stats_rules['passed']}/{stats_rules['total']} ({rules_rate:.1f}%)")
        
    print(f"REPORT > COPILOT hallucinated numbers: {hallucinated}")
    print(f"REPORT > COPILOT VERDICT: {verdict}")
    
    artifact = {
        "totals_per_path": {
            "llm": stats_llm,
            "rules": stats_rules
        },
        "per_answer_detail": [],
        "n": args.n,
        "model_name": "gemini",
        "git_sha": get_git_sha(),
        "timestamp": datetime.now(UTC).isoformat(),
        "review_spec": "EVALUATION_REVIEW 5"
    }
    
    for r in results:
        is_pass = False
        ext_count = 0
        if r["path"] == "llm":
            for detail in stats_llm["details"]:
                if detail["answer"] == r["answer"]:
                    is_pass = detail["pass"]
                    ext_count = len(detail["extracted"])
        else:
            for detail in stats_rules["details"]:
                if detail["answer"] == r["answer"]:
                    is_pass = detail["pass"]
                    ext_count = len(detail["extracted"])
                    
        artifact["per_answer_detail"].append({
            "question": r["question"],
            "path": r["path"],
            "extracted_count": ext_count,
            "pass": is_pass
        })
        
    out_path = Path(__file__).resolve().parent.parent / "eval" / "artifacts" / "copilot_faithfulness.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(artifact, f, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
