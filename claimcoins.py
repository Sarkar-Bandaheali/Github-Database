#!/usr/bin/env python3
import argparse
import concurrent.futures
import hashlib
import json
import logging
import time
import random
import traceback
from datetime import datetime
from getpass import getpass
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ── Endpoints ───────────────────────────────────────────────────────────
BASE        = "https://www.bounty-news.com/api"
LOGIN       = f"{BASE}/member/login"
DAILY_INFO  = f"{BASE}/memberReadingReward/info"
DAILY_CLAIM = f"{BASE}/memberReadingReward/getAward"

# ── Config ───────────────────────────────────────────────────────────────
DEFAULT_THREADS  = 5
DEFAULT_TIMEOUT  = 15
DEFAULT_RETRIES  = 3
DEFAULT_BACKOFF  = 2
DEFAULT_SALES_ID = "232"
LOG_FILE         = Path("daily_verbose.log")
OUT_FILE         = Path("daily_verbose_report.json")

# ── Credentials ─────────────────────────────────────────────────────────
credentials = [
    {"phone":"09582811870","code":"755"},
    {"phone":"09291078442","code":"586"},
    {"phone":"09497941608","code":"964"},
    {"phone":"09344474585","code":"922"},
    {"phone":"09465307245","code":"715"},
    {"phone":"09137520214","code":"872"},
    {"phone":"09170363921","code":"521"},
    {"phone":"09258785549","code":"835"},
    {"phone":"09554072913","code":"602"},
    {"phone":"09220359954","code":"609"},
    {"phone":"09489110740","code":"638"},
    {"phone":"09194589054","code":"254"},
    {"phone":"09137666532","code":"993"},
    {"phone":"09248750308","code":"298"},
    {"phone":"09506615700","code":"399"},
    {"phone":"09362605643","code":"794"},
    {"phone":"09494997709","code":"700"},
    {"phone":"09546494096","code":"767"},
    {"phone":"09154011245","code":"395"},
    {"phone":"09200451732","code":"729"},
    {"phone":"09470493591","code":"820"},
    {"phone":"09267209118","code":"825"},
    {"phone":"09363840678","code":"877"},
    {"phone":"09523781152","code":"395"},
    {"phone":"09457865133","code":"855"},
    {"phone":"09217197100","code":"443"},
    {"phone":"09103198637","code":"473"},
    {"phone":"09276897178","code":"408"},
    {"phone":"09475319134","code":"376"},
    {"phone":"09404418585","code":"162"},
    {"phone":"09325562525","code":"258"},
    {"phone":"09208981743","code":"344"},
    {"phone":"09507874412","code":"726"},
    {"phone":"09341058232","code":"868"},
    {"phone":"09381108034","code":"801"},
    {"phone":"09498165386","code":"654"},
    {"phone":"09311290235","code":"297"},
    {"phone":"09175596662","code":"638"},
    {"phone":"09270872633","code":"411"},
    {"phone":"09278534509","code":"791"},
    {"phone":"09568868916","code":"965"},
    {"phone":"09456985513","code":"644"},
    {"phone":"09343432491","code":"293"},
    {"phone":"09517723306","code":"504"},
    {"phone":"09176891014","code":"501"},
    {"phone":"09202974667","code":"336"},
    {"phone":"09177568570","code":"242"},
    {"phone":"09198389703","code":"673"},
    {"phone":"09210478623","code":"354"},
    {"phone":"09497128182","code":"351"},
]

def make_session(cfg):
    s = requests.Session()
    retry = Retry(
        total=cfg.retries,
        backoff_factor=cfg.backoff,
        status_forcelist=[429,500,502,503,504],
        allowed_methods=["GET","POST"]
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers.update({
        "Content-Type":"application/json",
        "Accept":"application/json",
        "salesPersonId": cfg.sales_id
    })
    return s

def safe_json(resp):
    try:
        return resp.json()
    except Exception:
        return {"_raw": resp.text}

def login_and_claim(cred, cfg):
    phone, code = cred["phone"], cred["code"]
    out = {"phone": phone, "ts": datetime.now().isoformat(), "errors": []}

    sess = make_session(cfg)
    # 1) LOGIN
    try:
        pwd = cfg.password + code
        md5 = hashlib.md5(pwd.encode()).hexdigest()
        r = sess.post(LOGIN, json={"phone": phone, "password": md5}, timeout=cfg.timeout)
        out["login_status_code"] = r.status_code
        out["login_response"]    = safe_json(r)
        r.raise_for_status()
        token = out["login_response"].get("result", {}).get("token")
        head  = out["login_response"].get("result", {}).get("tokenHead")
        uid   = out["login_response"].get("result", {}).get("sysUserId")
        if not token or not head:
            raise ValueError("Missing token/head")
        sess.headers.update({
            "Authorization": f"{head} {token}",
            "memberInfoId": str(uid)
        })
    except Exception as e:
        tb = traceback.format_exc()
        out["errors"].append({"stage": "login", "error": str(e), "trace": tb})
        return out

    # 2) FETCH DAILY INFO
    try:
        r = sess.post(DAILY_INFO, json={}, timeout=cfg.timeout)
        out["info_status_code"] = r.status_code
        info = safe_json(r)
        out["info_response"] = info
        r.raise_for_status()
    except Exception as e:
        tb = traceback.format_exc()
        out["errors"].append({"stage": "fetch_info", "error": str(e), "trace": tb})
        return out

    # 3) CLAIM ONLY COMPLETE TIERS
    completed = []
    try:
        tiers = info.get("result", {}).get("memberReadingRewardDetailVoList", [])
        for tier in tiers:
            if tier.get("memberReadingRewardStatus") == "complete":
                num = tier.get("workInfoReadingNum")
                try:
                    rr = sess.post(DAILY_CLAIM, json={"workInfoReadingNum": num}, timeout=cfg.timeout)
                    out.setdefault("claim_responses", []).append({
                        "tier": num,
                        "status_code": rr.status_code,
                        "response": safe_json(rr)
                    })
                    rr.raise_for_status()
                    completed.append(num)
                except Exception as ce:
                    tb = traceback.format_exc()
                    out.setdefault("errors", []).append({
                        "stage": f"claim_{num}",
                        "error": str(ce),
                        "trace": tb,
                        "response": safe_json(rr)
                    })
                time.sleep(random.uniform(0.5,1.2))
        out["claimed_tiers"] = completed
    except Exception as e:
        tb = traceback.format_exc()
        out["errors"].append({"stage": "claim_loop", "error": str(e), "trace": tb})
    return out

def main():
    p = argparse.ArgumentParser("Verbose daily bonus claimer")
    p.add_argument("-t","--threads", type=int, default=DEFAULT_THREADS)
    p.add_argument("-s","--sales-id", default=DEFAULT_SALES_ID)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--retries", type=int, default=DEFAULT_RETRIES)
    p.add_argument("--backoff", type=float, default=DEFAULT_BACKOFF)
    p.add_argument("-p","--password", action="store_true", help="prompt for shared pw")
    args = p.parse_args()

    pwd = getpass("Shared password base: ") if args.password else "password"

    # simple console log only
    print(f"🔔 Starting verbose daily claims for {len(credentials)} accounts in {args.threads} threads\n")

    class C: pass
    C.sales_id = args.sales_id
    C.timeout  = args.timeout
    C.retries  = args.retries
    C.backoff  = args.backoff
    C.password = pwd

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.threads) as exe:
        futures = [exe.submit(login_and_claim, c, C) for c in credentials]
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            print("----")
            print(f"Phone: {res['phone']} @ {res['ts']}")
            if res.get("errors"):
                for err in res["errors"]:
                    print(f"ERROR stage={err['stage']}: {err['error']}")
                    print(err["trace"])
            else:
                print("Login and fetch ok.")
                print("Claim responses:")
                for cr in res.get("claim_responses", []):
                    print(f"  tier={cr['tier']} code={cr['status_code']} resp={json.dumps(cr['response'])}")
                print("Claimed tiers:", res.get("claimed_tiers", []))
            results.append(res)

    OUT_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n🎉 Done – see full JSON report in {OUT_FILE}")

if __name__ == "__main__":
    main()