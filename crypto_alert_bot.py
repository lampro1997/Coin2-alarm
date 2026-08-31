#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Crypto Alert Bot -> Telegram
Cảnh báo khi giá coin tăng/giảm vượt ngưỡng (mặc định 2%) trong khung thời gian cấu hình.

Nguồn dữ liệu: Binance public API (không cần API key).
Chạy:  python crypto_alert_bot.py
Lấy chat ID:  python crypto_alert_bot.py --get-chat-id
Gửi thử 1 tin: python crypto_alert_bot.py --test
"""

import json
import os
import sys
import time
import logging
import threading
from datetime import datetime, timezone, timedelta

try:
    import requests
except ImportError:
    print("Thiếu thư viện 'requests'. Chạy: pip install requests")
    sys.exit(1)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STATE_PATH = os.path.join(BASE_DIR, "state.json")
LOG_PATH = os.path.join(BASE_DIR, "bot.log")

BINANCE = "https://api.binance.com"
TG_API = "https://api.telegram.org/bot{token}/{method}"

VN_TZ = timezone(timedelta(hours=7))

DEFAULT_CONFIG = {
    "telegram_bot_token": "DAN_TOKEN_CUA_BAN_VAO_DAY",
    "telegram_chat_id": "DAN_CHAT_ID_CUA_BAN_VAO_DAY",
    "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"],
    "threshold_percent": 2.0,
    "window": "1h",
    "check_interval_seconds": 60,
    "cooldown_minutes": 60,
    "rearm_step_percent": 1.0,
    "send_startup_message": True,
    "enable_commands": True,
}

log = logging.getLogger("cryptobot")


# ----------------------------------------------------------------------------
# Cấu hình & trạng thái
# ----------------------------------------------------------------------------
def setup_logging():
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)
    try:
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except OSError:
        pass


def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        print(f"Đã tạo file cấu hình mẫu: {CONFIG_PATH}")
        print("Hãy điền telegram_bot_token và telegram_chat_id rồi chạy lại.")
        sys.exit(0)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)

    # Cho phép ghi đè bằng biến môi trường (tiện khi chạy GitHub Actions/VPS/Docker)
    merged["telegram_bot_token"] = os.getenv("TELEGRAM_BOT_TOKEN", merged["telegram_bot_token"])
    merged["telegram_chat_id"] = os.getenv("TELEGRAM_CHAT_ID", merged["telegram_chat_id"])
    if os.getenv("SYMBOLS"):
        merged["symbols"] = [s.strip() for s in os.getenv("SYMBOLS").replace(",", " ").split()]
    if os.getenv("THRESHOLD_PERCENT"):
        merged["threshold_percent"] = float(os.getenv("THRESHOLD_PERCENT"))
    if os.getenv("WINDOW"):
        merged["window"] = os.getenv("WINDOW")
    if os.getenv("COOLDOWN_MINUTES"):
        merged["cooldown_minutes"] = float(os.getenv("COOLDOWN_MINUTES"))

    if "DAN_TOKEN" in str(merged["telegram_bot_token"]):
        print("Chưa cấu hình telegram_bot_token trong config.json.")
        sys.exit(1)
    merged["symbols"] = [s.upper().strip() for s in merged["symbols"] if s.strip()]
    return merged


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {"last_alert": {}}


def save_state(state):
    try:
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_PATH)
    except OSError as e:
        log.warning("Không ghi được state: %s", e)


# ----------------------------------------------------------------------------
# Telegram
# ----------------------------------------------------------------------------
def tg_call(token, method, params=None, timeout=20):
    url = TG_API.format(token=token, method=method)
    r = requests.get(url, params=params or {}, timeout=timeout)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram lỗi ({method}): {data.get('description')}")
    return data["result"]


def send_message(token, chat_id, text):
    for attempt in range(3):
        try:
            tg_call(token, "sendMessage", {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            return True
        except Exception as e:
            log.warning("Gửi Telegram thất bại (lần %d): %s", attempt + 1, e)
            time.sleep(2 * (attempt + 1))
    return False


# ----------------------------------------------------------------------------
# Dữ liệu giá (Binance)
# ----------------------------------------------------------------------------
def fetch_rolling_stats(symbols, window):
    """Trả về {symbol: {'price': float, 'pct': float, 'open': float}} cho khung `window`."""
    params = {
        "symbols": json.dumps(symbols, separators=(",", ":")),
        "windowSize": window,
    }
    r = requests.get(f"{BINANCE}/api/v3/ticker", params=params, timeout=20)
    r.raise_for_status()
    out = {}
    for item in r.json():
        out[item["symbol"]] = {
            "price": float(item["lastPrice"]),
            "pct": float(item["priceChangePercent"]),
            "open": float(item["openPrice"]),
        }
    return out


def fetch_rolling_stats_fallback(symbols, window):
    """Dự phòng: tính % từ nến 1 phút nếu endpoint /ticker không dùng được."""
    minutes = {"m": 1, "h": 60, "d": 1440}
    n = int(window[:-1]) * minutes[window[-1]]
    n = max(2, min(n, 1000))
    out = {}
    for sym in symbols:
        r = requests.get(f"{BINANCE}/api/v3/klines",
                         params={"symbol": sym, "interval": "1m", "limit": n + 1},
                         timeout=20)
        r.raise_for_status()
        k = r.json()
        if len(k) < 2:
            continue
        old = float(k[0][1])          # giá mở của nến cũ nhất
        now = float(k[-1][4])         # giá đóng gần nhất
        out[sym] = {"price": now, "pct": (now - old) / old * 100.0, "open": old}
        time.sleep(0.1)
    return out


def get_stats(symbols, window):
    try:
        data = fetch_rolling_stats(symbols, window)
        if data:
            return data
    except Exception as e:
        log.warning("Endpoint /ticker lỗi (%s), dùng phương án nến 1m.", e)
    return fetch_rolling_stats_fallback(symbols, window)


# ----------------------------------------------------------------------------
# Định dạng
# ----------------------------------------------------------------------------
def fmt_price(p):
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:.6f}"


def pretty_symbol(sym):
    for quote in ("USDT", "BUSD", "FDUSD", "USDC", "BTC", "ETH"):
        if sym.endswith(quote):
            return f"{sym[:-len(quote)]}/{quote}"
    return sym


def now_vn():
    return datetime.now(VN_TZ).strftime("%H:%M:%S %d/%m/%Y")


def build_alert(sym, info, window, threshold):
    up = info["pct"] >= 0
    icon = "🟢📈" if up else "🔴📉"
    word = "TĂNG" if up else "GIẢM"
    return (
        f"{icon} <b>{pretty_symbol(sym)} {word} {abs(info['pct']):.2f}%</b> "
        f"(khung {window})\n\n"
        f"💵 Giá hiện tại: <b>{fmt_price(info['price'])}</b>\n"
        f"↩️ Giá {window} trước: {fmt_price(info['open'])}\n"
        f"🎯 Ngưỡng cảnh báo: {threshold}%\n"
        f"🕒 {now_vn()} (giờ VN)"
    )


# ----------------------------------------------------------------------------
# Logic cảnh báo
# ----------------------------------------------------------------------------
def should_alert(sym, pct, cfg, state):
    """Quyết định có gửi cảnh báo không (có cooldown + tái kích hoạt khi biến động mạnh thêm)."""
    if abs(pct) < cfg["threshold_percent"]:
        return False

    rec = state["last_alert"].get(sym)
    if not rec:
        return True

    now = time.time()
    same_direction = (pct >= 0) == (rec["pct"] >= 0)
    elapsed_min = (now - rec["ts"]) / 60.0

    # Đảo chiều -> báo ngay
    if not same_direction:
        return True
    # Biến động mạnh thêm rearm_step_percent -> báo lại dù còn cooldown
    if abs(pct) >= abs(rec["pct"]) + cfg["rearm_step_percent"]:
        return True
    # Hết cooldown -> báo lại
    return elapsed_min >= cfg["cooldown_minutes"]


def check_once(cfg, state, send):
    data = get_stats(cfg["symbols"], cfg["window"])
    if not data:
        log.warning("Không lấy được dữ liệu giá.")
        return data

    summary = " | ".join(f"{pretty_symbol(s)} {d['pct']:+.2f}%" for s, d in data.items())
    log.info("Kiểm tra: %s", summary)

    for sym, info in data.items():
        if should_alert(sym, info["pct"], cfg, state):
            msg = build_alert(sym, info, cfg["window"], cfg["threshold_percent"])
            if send(msg):
                state["last_alert"][sym] = {"pct": info["pct"], "ts": time.time()}
                save_state(state)
                log.info("ĐÃ GỬI CẢNH BÁO: %s %+.2f%%", sym, info["pct"])
    return data


# ----------------------------------------------------------------------------
# Lắng nghe lệnh Telegram (/gia, /status, /nguong ...)
# ----------------------------------------------------------------------------
HELP_TEXT = (
    "<b>Các lệnh khả dụng</b>\n"
    "/gia – xem giá &amp; % thay đổi hiện tại\n"
    "/status – trạng thái bot &amp; cấu hình\n"
    "/nguong 3 – đổi ngưỡng cảnh báo sang 3%\n"
    "/help – hiện trợ giúp"
)


def handle_command(cfg, text, mode="loop"):
    """Xử lý một lệnh Telegram. Trả về True nếu là lệnh đã nhận diện."""
    token = cfg["telegram_bot_token"]
    chat_id = str(cfg["telegram_chat_id"])
    cmd = text.split()[0].split("@")[0].lower()

    if cmd in ("/start", "/help"):
        send_message(token, chat_id, HELP_TEXT)

    elif cmd in ("/gia", "/price"):
        data = get_stats(cfg["symbols"], cfg["window"])
        lines = [f"<b>Giá hiện tại</b> (thay đổi {cfg['window']})\n"]
        for s, d in data.items():
            arrow = "🟢" if d["pct"] >= 0 else "🔴"
            lines.append(f"{arrow} <b>{pretty_symbol(s)}</b>: "
                         f"{fmt_price(d['price'])}  ({d['pct']:+.2f}%)")
        lines.append(f"\n🕒 {now_vn()}")
        send_message(token, chat_id, "\n".join(lines))

    elif cmd == "/status":
        if mode == "once":
            nhip = "chạy theo lịch trên GitHub Actions"
        else:
            nhip = f"mỗi {cfg['check_interval_seconds']}s"
        send_message(token, chat_id,
                     "<b>Bot đang chạy ✅</b>\n"
                     f"Coin: {', '.join(pretty_symbol(s) for s in cfg['symbols'])}\n"
                     f"Ngưỡng: {cfg['threshold_percent']}% / khung {cfg['window']}\n"
                     f"Nhịp kiểm tra: {nhip}\n"
                     f"Cooldown: {cfg['cooldown_minutes']} phút\n"
                     f"🕒 {now_vn()}")

    elif cmd == "/nguong":
        parts = text.split()
        if len(parts) > 1:
            try:
                val = float(parts[1].replace("%", "").replace(",", "."))
            except ValueError:
                send_message(token, chat_id, "Cú pháp: /nguong 3")
                return True
            if 0.1 <= val <= 100:
                cfg["threshold_percent"] = val
                extra = ("\n⚠️ Ở chế độ GitHub Actions, thay đổi này chỉ áp dụng cho lần chạy "
                         "hiện tại. Muốn đổi vĩnh viễn hãy sửa THRESHOLD_PERCENT trong workflow.")
                send_message(token, chat_id,
                             f"✅ Đã đổi ngưỡng cảnh báo sang <b>{val}%</b>."
                             + (extra if mode == "once" else ""))
            else:
                send_message(token, chat_id, "Ngưỡng phải trong khoảng 0.1 – 100.")
        else:
            send_message(token, chat_id, "Cú pháp: /nguong 3")
    else:
        return False
    return True


def process_commands_once(cfg, state):
    """Chế độ --once: đọc hết tin nhắn đang chờ, trả lời, rồi thoát."""
    token = cfg["telegram_bot_token"]
    chat_id = str(cfg["telegram_chat_id"])
    offset = state.get("tg_offset")
    try:
        updates = tg_call(token, "getUpdates", {"offset": offset, "timeout": 0}, timeout=20)
    except Exception as e:
        log.warning("Không đọc được lệnh Telegram: %s", e)
        return

    for u in updates:
        state["tg_offset"] = u["update_id"] + 1
        msg = u.get("message") or u.get("channel_post") or {}
        text = (msg.get("text") or "").strip()
        frm = str(msg.get("chat", {}).get("id", ""))
        if not text or frm != chat_id or not text.startswith("/"):
            continue
        try:
            handle_command(cfg, text, mode="once")
        except Exception as e:
            log.warning("Xử lý lệnh '%s' lỗi: %s", text, e)


def command_loop(cfg, state, stop_event):
    token = cfg["telegram_bot_token"]
    chat_id = str(cfg["telegram_chat_id"])
    offset = state.get("tg_offset")

    while not stop_event.is_set():
        try:
            updates = tg_call(token, "getUpdates",
                              {"offset": offset, "timeout": 25}, timeout=35)
        except Exception as e:
            log.debug("getUpdates lỗi: %s", e)
            stop_event.wait(5)
            continue

        for u in updates:
            offset = u["update_id"] + 1
            state["tg_offset"] = offset
            msg = u.get("message") or u.get("channel_post") or {}
            text = (msg.get("text") or "").strip()
            frm = str(msg.get("chat", {}).get("id", ""))
            if not text or frm != chat_id:
                continue
            try:
                handle_command(cfg, text, mode="loop")
            except Exception as e:
                log.warning("Xử lý lệnh '%s' lỗi: %s", text, e)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def cmd_get_chat_id(token):
    print("Hãy mở Telegram, nhắn bất kỳ tin nào cho bot của bạn, rồi đợi...")
    for _ in range(30):
        try:
            updates = tg_call(token, "getUpdates", {"timeout": 5}, timeout=15)
        except Exception as e:
            print("Lỗi:", e)
            return
        seen = {}
        for u in updates:
            m = u.get("message") or u.get("channel_post") or {}
            c = m.get("chat")
            if c:
                seen[c["id"]] = c.get("title") or c.get("username") or c.get("first_name", "")
        if seen:
            print("\nTìm thấy chat ID:")
            for cid, name in seen.items():
                print(f"  chat_id = {cid}   ({name})")
            print("\nDán giá trị chat_id vào 'telegram_chat_id' trong config.json.")
            return
        time.sleep(2)
    print("Không nhận được tin nhắn nào. Hãy chắc chắn bạn đã nhắn cho bot rồi thử lại.")


def main():
    setup_logging()
    args = sys.argv[1:]
    cfg = load_config()
    token = cfg["telegram_bot_token"]
    chat_id = cfg["telegram_chat_id"]

    if "--get-chat-id" in args:
        cmd_get_chat_id(token)
        return

    if "--test" in args:
        ok = send_message(token, chat_id,
                          "✅ <b>Kết nối thành công!</b>\nBot cảnh báo giá coin đã sẵn sàng.\n"
                          f"🕒 {now_vn()}")
        print("Gửi thử:", "OK" if ok else "THẤT BẠI")
        return

    state = load_state()
    send = lambda m: send_message(token, chat_id, m)

    # --once: kiểm tra 1 lần rồi thoát (dùng cho GitHub Actions / cron)
    if "--once" in args:
        log.info("Chế độ --once | coin=%s | ngưỡng=%s%% | khung=%s",
                 ",".join(cfg["symbols"]), cfg["threshold_percent"], cfg["window"])
        if cfg.get("enable_commands"):
            process_commands_once(cfg, state)
        try:
            check_once(cfg, state, send)
        except Exception as e:
            log.error("Lỗi khi kiểm tra giá: %s", e)
            save_state(state)
            sys.exit(1)
        save_state(state)
        return

    log.info("Khởi động bot | coin=%s | ngưỡng=%s%% | khung=%s | chu kỳ=%ss",
             ",".join(cfg["symbols"]), cfg["threshold_percent"],
             cfg["window"], cfg["check_interval_seconds"])

    if cfg.get("send_startup_message"):
        send(f"🤖 <b>Bot cảnh báo giá coin đã khởi động</b>\n"
             f"Theo dõi: {', '.join(pretty_symbol(s) for s in cfg['symbols'])}\n"
             f"Cảnh báo khi biến động ≥ <b>{cfg['threshold_percent']}%</b> trong {cfg['window']}\n"
             f"Gõ /help để xem các lệnh.\n🕒 {now_vn()}")

    stop_event = threading.Event()
    if cfg.get("enable_commands"):
        t = threading.Thread(target=command_loop, args=(cfg, state, stop_event), daemon=True)
        t.start()

    fail_streak = 0
    try:
        while True:
            try:
                check_once(cfg, state, send)
                fail_streak = 0
            except Exception as e:
                fail_streak += 1
                log.error("Lỗi vòng kiểm tra (%d): %s", fail_streak, e)
                if fail_streak == 5:
                    send(f"⚠️ Bot gặp lỗi khi lấy dữ liệu 5 lần liên tiếp:\n<code>{e}</code>")
            time.sleep(max(10, int(cfg["check_interval_seconds"])))
    except KeyboardInterrupt:
        log.info("Đã dừng bot.")
        stop_event.set()


if __name__ == "__main__":
    main()
