import json
import os
import re
import sys
import time
import urllib.parse
from datetime import date, timedelta

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    requests = None
    BeautifulSoup = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_JSON = os.path.join(BASE_DIR, "data", "data.json")
DATA_JS = os.path.join(BASE_DIR, "data", "data.js")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/report/",
}

LIST_API = "https://reportapi.eastmoney.com/report/jg"
LIST_API_STOCK = "https://reportapi.eastmoney.com/report/list"
DETAIL_TPL = "https://data.eastmoney.com/report/zw_strategy.jshtml?encodeUrl="
STOCK_PDF_TPL = "https://pdf.dfcfw.com/pdf/H3_{}_1.pdf"

WINDOW_DAYS = 7
FETCH_SUMMARY = True
DISPLAY_LEN = 200
STOCK_CAP = 6000

SECTOR_KEYWORDS = [
    "AI", "人工智能", "半导体", "芯片", "电子", "计算机", "通信", "软件",
    "医药", "医疗", "创新药", "中药", "消费", "白酒", "家电", "汽车",
    "新能源", "光伏", "锂电", "储能", "电动车", "军工", "国防", "有色",
    "化工", "钢铁", "煤炭", "石油", "银行", "券商", "保险", "地产",
    "建筑", "建材", "机械", "农业", "食品", "红利", "高股息", "港股",
    "中特估", "机器人", "算力", "数字经济", "黄金", "周期",
]


def iso_week_key(d=None):
    d = d or date.today()
    y, w, _ = d.isocalendar()
    return "%d-W%02d" % (y, w)


def week_range(d=None):
    d = d or date.today()
    monday = d - timedelta(days=d.weekday())
    friday = monday + timedelta(days=4)
    fmt = lambda x: "%02d-%02d" % (x.month, x.day)
    return "%s ~ %s" % (fmt(monday), fmt(friday))


def month_key(d=None):
    d = d or date.today()
    return "%04d-%02d" % (d.year, d.month)


def month_range(y, m):
    first = date(y, m, 1)
    if m == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m + 1, 1)
    last = nxt - timedelta(days=1)
    return "%02d-%02d ~ %02d-%02d" % (first.month, first.day, last.month, last.day)


def fetch_json(url, params):
    if requests is None:
        raise RuntimeError("缺少依赖，请先运行: pip install requests beautifulsoup4")
    resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    text = resp.text
    if text.lstrip().startswith("{"):
        return resp.json()
    m = re.search(r"\((\{.*\})\)", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    return resp.json()


def fetch_strategy_reports(begin, end):
    items = []
    page = 1
    while True:
        params = {
            "pageSize": 50,
            "pageNo": page,
            "beginTime": begin,
            "endTime": end,
            "qType": 2,
            "fields": "",
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "orgCode": "",
            "rcode": "",
            "_": int(time.time() * 1000),
        }
        data = fetch_json(LIST_API, params)
        batch = data.get("data") or []
        for it in batch:
            items.append({
                "broker": (it.get("orgSName") or it.get("orgName") or "").strip(),
                "title": (it.get("title") or "").strip(),
                "date": (it.get("publishDate") or "")[:10],
                "encodeUrl": it.get("encodeUrl") or "",
                "researcher": (it.get("researcher") or "").strip(),
            })
        total = data.get("TotalPage", 1)
        print("  列表进度: 第 %d/%d 页，已抓取 %d 篇" % (page, total, len(items)))
        if page >= total or not batch:
            break
        page += 1
        time.sleep(0.3)
    return items


def fetch_summary(encode_url):
    url = DETAIL_TPL + urllib.parse.quote_plus(encode_url)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.encoding = "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")
        node = soup.find(id="ctx-content")
        if not node:
            return ""
        text = node.get_text("\n", strip=True)
        text = re.sub(r"\n{2,}", "\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        return text
    except Exception:
        return ""


def match_sectors(text):
    found = []
    low = text.lower()
    for kw in SECTOR_KEYWORDS:
        if kw.lower() in low:
            found.append(kw)
    return found


def collect(begin, end):
    raw = fetch_strategy_reports(begin, end)
    print("抓取券商策略 %d 篇" % len(raw))
    results = []
    for idx, it in enumerate(raw):
        full = ""
        if FETCH_SUMMARY and it["encodeUrl"]:
            full = fetch_summary(it["encodeUrl"])
            print("  正文进度: %d/%d (%.0f%%)" % (
                idx + 1, len(raw), 100 * (idx + 1) / max(1, len(raw))))
            time.sleep(0.2)
        text_blob = it["title"] + " " + full
        results.append({
            "type": "策略",
            "broker": it["broker"],
            "title": it["title"],
            "date": it["date"],
            "summary": full[:DISPLAY_LEN],
            "content": full,
            "sectors": match_sectors(text_blob),
            "url": DETAIL_TPL + urllib.parse.quote_plus(it["encodeUrl"]) if it["encodeUrl"] else "",
        })
    return results


def fetch_stock_reports(begin, end):
    items = []
    page = 1
    while True:
        params = {
            "pageSize": 50,
            "pageNo": page,
            "beginTime": begin,
            "endTime": end,
            "qType": 0,
            "industry": "*",
            "industryCode": "*",
            "rating": "*",
            "ratingChange": "*",
            "orgCode": "",
            "code": "*",
            "rcode": "",
            "_": int(time.time() * 1000),
        }
        data = fetch_json(LIST_API_STOCK, params)
        batch = data.get("data") or []
        for it in batch:
            items.append({
                "broker": (it.get("orgSName") or it.get("orgName") or "").strip(),
                "title": (it.get("title") or "").strip(),
                "date": (it.get("publishDate") or "")[:10],
                "stock": (it.get("stockName") or "").strip(),
                "stockCode": (it.get("stockCode") or "").strip(),
                "rating": (it.get("emRatingName") or "").strip(),
                "industry": (it.get("indvInduName") or it.get("industryName") or "").strip(),
                "infoCode": it.get("infoCode") or "",
                "encodeUrl": it.get("encodeUrl") or "",
            })
        total = data.get("TotalPage", 1)
        if page >= total or not batch:
            break
        page += 1
        time.sleep(0.2)
        if len(items) >= STOCK_CAP:
            break
    return items


def collect_stock(begin, end):
    raw = fetch_stock_reports(begin, end)
    print("抓取个股研报 %d 篇" % len(raw))
    results = []
    for idx, it in enumerate(raw):
        if idx % 200 == 0:
            print("  个股研报进度: %d/%d" % (idx, len(raw)))
        results.append({
            "type": "个股研报",
            "broker": it["broker"],
            "title": it["title"],
            "date": it["date"],
            "stock": it["stock"],
            "stockCode": it["stockCode"],
            "rating": it["rating"],
            "summary": "",
            "content": "",
            "sectors": [it["industry"]] if it["industry"] else [],
            "url": STOCK_PDF_TPL.format(it["infoCode"]) if it["infoCode"] else "",
        })
    return results


def merge_items(store, key, items, today, rng):
    bucket = store["weeks"].setdefault(key, {
        "updatedAt": today.isoformat(),
        "monthRange": rng,
        "count": 0,
        "items": [],
    })
    bucket["updatedAt"] = today.isoformat()
    bucket["monthRange"] = rng
    seen = set()
    for ex in bucket["items"]:
        seen.add((ex.get("type", "策略"), ex.get("broker", ""), ex.get("title", ""),
                  ex.get("date", ""), ex.get("stockCode", "")))
    added = 0
    for it in items:
        key = (it["type"], it.get("broker", ""), it.get("title", ""),
               it.get("date", ""), it.get("stockCode", ""))
        if key in seen:
            continue
        seen.add(key)
        bucket["items"].append(it)
        added += 1
    bucket["count"] = len(bucket["items"])
    return added


def load_store():
    if os.path.exists(DATA_JSON):
        with open(DATA_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"latest": None, "weeks": {}}


def save_store(store):
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    with open(DATA_JS, "w", encoding="utf-8") as f:
        f.write("window.STRATEGY_DATA = ")
        json.dump(store, f, ensure_ascii=False, indent=2)
        f.write(";\n")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=WINDOW_DAYS, help="抓取最近 N 天（按月分桶，每月抓完即保存）")
    parser.add_argument("--no-stock", action="store_true", help="只抓券商策略，不抓个股研报")
    args = parser.parse_args()

    today = date.today()
    store = load_store()
    meta = store.setdefault("_meta", {"done": {}})

    old_week_keys = [k for k in list(store["weeks"].keys()) if re.match(r"^\d{4}-W\d{2}$", k)]
    if old_week_keys:
        print("迁移 %d 个旧周桶为月桶…" % len(old_week_keys))
        for wk in old_week_keys:
            for it in store["weeks"][wk].get("items", []):
                dstr = it.get("date") or today.isoformat()
                try:
                    mk = month_key(date.fromisoformat(dstr[:10]))
                except Exception:
                    mk = month_key(today)
                y, m = map(int, mk.split("-"))
                store["weeks"].setdefault(mk, {
                    "updatedAt": today.isoformat(),
                    "monthRange": month_range(y, m),
                    "count": 0,
                    "items": [],
                })["items"].append(it)
            del store["weeks"][wk]
        for mk, b in store["weeks"].items():
            b["count"] = len(b["items"])
            if any(it.get("type", "策略") == "策略" for it in b["items"]):
                meta["done"].setdefault(mk, {})["strategy"] = True
            if any(it.get("type") == "个股研报" for it in b["items"]):
                meta["done"].setdefault(mk, {})["stock"] = True
        save_store(store)

    begin = today - timedelta(days=max(1, args.days) - 1)
    end = today
    begin_s = begin.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")
    print("抓取区间 %s ~ %s" % (begin_s, end_s))

    all_items = []
    print("抓取券商策略…")
    all_items += collect(begin_s, end_s)
    if not args.no_stock:
        print("抓取个股研报…")
        all_items += collect_stock(begin_s, end_s)

    groups = {}
    for it in all_items:
        dstr = it.get("date") or today.isoformat()
        try:
            mk = month_key(date.fromisoformat(dstr[:10]))
        except Exception:
            mk = month_key(today)
        groups.setdefault(mk, []).append(it)

    added_total = 0
    for mk, its in groups.items():
        y, m = map(int, mk.split("-"))
        added_total += merge_items(store, mk, its, today, month_range(y, m))

    latest = sorted(store["weeks"].keys())[-1]
    store["latest"] = latest
    save_store(store)
    print("完成：共 %d 个月桶，最新 %s；本次抓取 %d 篇，去重后新增 %d 篇" % (
        len(store["weeks"]), latest, len(all_items), added_total))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        if sys.stdin.isatty() and not os.environ.get('GITHUB_ACTIONS'):
            input("出现错误，按回车退出...")
        sys.exit(1)
    else:
        if sys.stdin.isatty() and not os.environ.get('GITHUB_ACTIONS'):
            input("完成，按回车退出...")
