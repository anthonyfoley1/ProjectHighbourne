"""
One-time script to reconcile existing duration caches with annual 10-K data.
Fetches annual + quarterly entries with start/end dates from EDGAR,
then derives missing Q4 = Annual - Q1 - Q2 - Q3.
Run once, then delete this file.
"""
import json
import os
import time
import requests
from edgar_utils import _reconcile_quarterly_with_annual

SEC_HEADERS = {"User-Agent": "ProjectHighbourne research@example.com"}

# Load CIK lookup
resp = requests.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_HEADERS)
cik_lookup = {v["ticker"]: str(v["cik_str"]).zfill(10) for v in resp.json().values()}

DURATION_CACHES = {
    "edgar_revenue_cache.json": "Revenues",
    "edgar_netincome_cache.json": "NetIncomeLoss",
    "edgar_opincome_cache.json": "OperatingIncomeLoss",
    "edgar_dna_cache.json": "DepreciationDepletionAndAmortization",
}

for cache_file, concept in DURATION_CACHES.items():
    print(f"\n=== Reconciling {concept} ({cache_file}) ===")

    with open(cache_file) as f:
        cache = json.load(f)

    tickers = [t for t in cache if cache[t] and t in cik_lookup]
    print(f"  {len(tickers)} tickers to reconcile")

    reconciled = 0
    added_q4 = 0
    corrected_q4 = 0

    for i, t in enumerate(tickers):
        if (i + 1) % 100 == 0:
            print(f"  Progress: {i + 1}/{len(tickers)}...")

        cik = cik_lookup[t]
        url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{concept}.json"

        try:
            resp = requests.get(url, headers=SEC_HEADERS)
            if resp.status_code != 200:
                continue

            data = resp.json()
            entries = data.get("units", {}).get("USD", [])

            quarterly_entries = []
            annual_entries = []
            for e in entries:
                if e["form"] in ("10-Q", "10-K") and "frame" in e and "start" in e:
                    frame = e["frame"]
                    if "Q" in frame and not frame.endswith("I"):
                        quarterly_entries.append({"start": e["start"], "end": e["end"], "val": e["val"]})
                    elif frame.startswith("CY") and "Q" not in frame and not frame.endswith("I"):
                        annual_entries.append({"start": e["start"], "end": e["end"], "val": e["val"]})

            if annual_entries:
                old = dict(cache[t])
                new = _reconcile_quarterly_with_annual(quarterly_entries, annual_entries)
                if new != old:
                    new_keys = set(new) - set(old)
                    changed_keys = {k for k in set(new) & set(old) if new[k] != old[k]}
                    added_q4 += len(new_keys)
                    corrected_q4 += len(changed_keys)
                    cache[t] = new
                    reconciled += 1

        except Exception as ex:
            print(f"  Error on {t}: {ex}")

        time.sleep(0.11)

    # Save updated cache
    with open(cache_file, "w") as f:
        json.dump(cache, f)

    print(f"  Done. {reconciled} tickers changed, {added_q4} Q4s added, {corrected_q4} Q4s corrected.")

print("\nAll caches reconciled.")
