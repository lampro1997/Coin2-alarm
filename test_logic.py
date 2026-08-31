"""Kiểm thử offline: logic ngưỡng, cooldown, đảo chiều, định dạng tin nhắn."""
import time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crypto_alert_bot as bot

cfg = dict(bot.DEFAULT_CONFIG)
cfg["threshold_percent"] = 2.0
cfg["cooldown_minutes"] = 60
cfg["rearm_step_percent"] = 1.0

fails = []
def check(name, got, want):
    ok = got == want
    print(("PASS  " if ok else "FAIL  ") + name + f"  (got={got}, want={want})")
    if not ok: fails.append(name)

# 1. Dưới ngưỡng -> không báo
st = {"last_alert": {}}
check("1.9% khong bao", bot.should_alert("BTCUSDT", 1.9, cfg, st), False)
check("-1.99% khong bao", bot.should_alert("BTCUSDT", -1.99, cfg, st), False)

# 2. Vượt ngưỡng lần đầu -> báo
check("2.0% bao", bot.should_alert("BTCUSDT", 2.0, cfg, st), True)
check("-3.5% bao", bot.should_alert("BTCUSDT", -3.5, cfg, st), True)

# 3. Vừa báo xong, cùng chiều, chưa tăng thêm 1% -> im (chống spam)
st = {"last_alert": {"BTCUSDT": {"pct": 2.3, "ts": time.time()}}}
check("cooldown chan lap lai", bot.should_alert("BTCUSDT", 2.5, cfg, st), False)

# 4. Cùng chiều nhưng mạnh thêm >= 1% -> báo lại ngay
check("tang manh them 1% -> bao", bot.should_alert("BTCUSDT", 3.4, cfg, st), True)

# 5. Đảo chiều -> báo ngay
check("dao chieu -> bao", bot.should_alert("BTCUSDT", -2.2, cfg, st), True)

# 6. Hết cooldown -> báo lại
st = {"last_alert": {"BTCUSDT": {"pct": 2.3, "ts": time.time() - 61 * 60}}}
check("het cooldown -> bao", bot.should_alert("BTCUSDT", 2.4, cfg, st), True)

# 7. Coin khác không bị ảnh hưởng bởi cooldown của BTC
st = {"last_alert": {"BTCUSDT": {"pct": 2.3, "ts": time.time()}}}
check("coin khac doc lap", bot.should_alert("ETHUSDT", 2.1, cfg, st), True)

# 8. Định dạng
check("pretty_symbol", bot.pretty_symbol("BTCUSDT"), "BTC/USDT")
check("fmt_price lon", bot.fmt_price(64231.5), "64,231.50")
check("fmt_price nho", bot.fmt_price(0.00004321), "0.000043")

# 9. Luồng check_once đầy đủ với dữ liệu giả
sent = []
fake = {
    "BTCUSDT": {"price": 64000.0, "pct": 2.6, "open": 62378.0},
    "ETHUSDT": {"price": 3100.0, "pct": -3.1, "open": 3199.0},
    "BNBUSDT": {"price": 600.0, "pct": 0.4, "open": 597.6},
}
bot.get_stats = lambda symbols, window: fake
bot.save_state = lambda s: None
st = {"last_alert": {}}
cfg["symbols"] = list(fake)
bot.check_once(cfg, st, lambda m: (sent.append(m), True)[1])
check("so alert gui ra", len(sent), 2)
check("BNB duoi nguong khong gui", any("BNB" in m for m in sent), False)

# Chạy lại ngay -> không gửi thêm (cooldown)
bot.check_once(cfg, st, lambda m: (sent.append(m), True)[1])
check("chay lai khong spam", len(sent), 2)

print("\n--- Tin nhắn mẫu ---\n")
print(sent[0])
print()
print(sent[1])

print("\n" + ("TAT CA TEST PASS" if not fails else f"CO {len(fails)} TEST FAIL: {fails}"))
sys.exit(1 if fails else 0)
