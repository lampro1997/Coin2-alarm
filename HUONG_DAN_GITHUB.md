# Chạy bot cảnh báo coin 24/7 miễn phí bằng GitHub Actions

Bot chạy trên máy chủ của GitHub, **không tốn tiền, không cần thẻ tín dụng, không cần để máy mở**.
Cứ 10 phút GitHub tự chạy bot một lần: lấy giá, so với 1 giờ trước, nếu biến động ≥ 2% thì nhắn Telegram.

---

## Bước 1 — Tạo bot Telegram (nếu chưa có)

1. Telegram → tìm **@BotFather** → gõ `/newbot` → đặt tên và username kết thúc bằng `bot`.
2. Copy token dạng `8123456789:AAF9xYz-abc...`
3. Bấm vào bot vừa tạo, nhấn **Start**, nhắn một tin bất kỳ (bắt buộc, nếu không bot không được phép nhắn cho bạn).
4. Lấy Chat ID: mở trình duyệt, dán link sau (thay TOKEN bằng token của bạn):

   ```
   https://api.telegram.org/botTOKEN/getUpdates
   ```

   Tìm đoạn `"chat":{"id":6123456789` — con số đó là **Chat ID**.

---

## Bước 2 — Tạo repo trên GitHub

1. Vào https://github.com/new
2. Đặt tên bất kỳ, ví dụ `coin-alert`.
3. Chọn **Public**. ⚠️ Bắt buộc Public thì mới **miễn phí không giới hạn phút chạy** (repo Private chỉ được 2.000 phút/tháng, chạy 10 phút/lần sẽ hết trong ~2 tuần).
4. Bấm **Create repository**.

> **Token có bị lộ khi để repo Public không?** Không. Token nằm trong GitHub Secrets, không nằm trong code. Chỉ cần bạn **không** tự tay điền token vào `config.json` rồi upload.

---

## Bước 3 — Upload code

Trong repo vừa tạo, bấm **Add file → Upload files**, kéo thả **toàn bộ** nội dung thư mục này vào (kể cả thư mục `.github`), rồi **Commit changes**.

> Nếu giao diện web không cho kéo thả thư mục ẩn `.github`, dùng Git:
> ```bash
> git init
> git add .
> git commit -m "coin alert bot"
> git branch -M main
> git remote add origin https://github.com/TEN_CUA_BAN/coin-alert.git
> git push -u origin main
> ```

---

## Bước 4 — Nạp token vào Secrets

Trong repo: **Settings → Secrets and variables → Actions → New repository secret**

Tạo **2** secret (tên phải viết hoa chính xác):

| Name                  | Secret                          |
|-----------------------|---------------------------------|
| `TELEGRAM_BOT_TOKEN`  | token lấy từ BotFather          |
| `TELEGRAM_CHAT_ID`    | chat ID lấy ở bước 1            |

---

## Bước 5 — Bật và chạy thử

1. Mở tab **Actions**. Nếu hiện nút xanh "I understand my workflows, go ahead and enable them" → bấm vào.
2. Chọn workflow **Coin Alert** ở cột trái → bấm **Run workflow** → **Run workflow**.
3. Đợi ~40 giây, bấm vào lần chạy để xem log. Nếu có coin nào đang biến động ≥ 2%, Telegram sẽ nhận được tin ngay.

Xong. Từ giờ GitHub tự chạy mỗi 10 phút, kể cả khi bạn tắt máy.

Muốn kiểm tra bot còn sống: nhắn `/status` hoặc `/gia` cho bot trên Telegram — bot sẽ trả lời **trong lần chạy kế tiếp** (tối đa 10 phút sau, vì bot không online liên tục).

---

## Đổi cấu hình

Sửa file `.github/workflows/coin-alert.yml`, phần `env:`:

```yaml
      SYMBOLS: "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT"   # thêm/bớt coin
      THRESHOLD_PERCENT: "2"        # ngưỡng %
      WINDOW: "1h"                  # 5m / 15m / 1h / 4h / 24h
      COOLDOWN_MINUTES: "60"        # nghỉ bao lâu trước khi báo lại cùng 1 coin
```

Đổi tần suất chạy ở dòng `cron`:

| Tần suất      | cron              |
|---------------|-------------------|
| 5 phút/lần    | `"*/5 * * * *"`   |
| 10 phút/lần   | `"*/10 * * * *"`  |
| 30 phút/lần   | `"*/30 * * * *"`  |
| 1 giờ/lần     | `"0 * * * *"`     |

Sửa xong bấm **Commit changes**, GitHub áp dụng ngay.

---

## Những điều cần biết trước (nói thật để bạn không bất ngờ)

1. **Không đúng "thời gian thực".** GitHub chỉ cho chạy tối thiểu 5 phút/lần, và vào giờ cao điểm lịch chạy có thể **trễ 5–15 phút**. Với cảnh báo khung 1h thì không sao, nhưng nếu bạn muốn bắt biến động trong 1–2 phút thì phải dùng VPS.

2. **Đôi khi bị bỏ lỡ một nhịp.** GitHub không cam kết chạy đúng 100% số lần đã lên lịch. Hiếm, nhưng có.

3. **Workflow tự bị tắt sau 60 ngày repo không có hoạt động.** Mình đã kèm sẵn `keepalive.yml` commit một dấu thời gian mỗi tháng để chống việc này; ngoài ra mỗi lần bot gửi cảnh báo nó cũng commit `state.json` nên repo hiếm khi "im lặng" đủ 60 ngày. Nếu vẫn bị tắt, GitHub sẽ gửi email và bạn chỉ cần vào tab Actions bấm **Enable workflow** là xong.

4. **Đừng dùng cho việc sống còn.** Đây là cảnh báo tham khảo, không nên dựa vào nó để cắt lỗ tự động.

---

## File trong thư mục

| File | Công dụng |
|------|-----------|
| `.github/workflows/coin-alert.yml` | Lịch chạy 10 phút/lần + cấu hình |
| `.github/workflows/keepalive.yml`  | Giữ repo hoạt động, chống bị tắt sau 60 ngày |
| `crypto_alert_bot.py`              | Bot (chạy `--once` trên Actions, chạy liên tục nếu để trên máy/VPS) |
| `state.json`                       | Nhớ lần cảnh báo cuối để không spam — **phải commit lên repo** |
| `config.json`                      | Cấu hình mặc định (Secrets/env sẽ ghi đè) — **không điền token vào đây** |
| `test_logic.py`                    | Kiểm thử logic, chạy `python test_logic.py` |

---

## Lỗi thường gặp

| Hiện tượng | Nguyên nhân / cách sửa |
|-----------|------------------------|
| Job đỏ, log ghi `Unauthorized` | Sai `TELEGRAM_BOT_TOKEN` trong Secrets |
| Job đỏ, log ghi `Chat not found` | Sai `TELEGRAM_CHAT_ID`, hoặc bạn chưa nhấn Start với bot |
| Job xanh nhưng không có tin nhắn | Bình thường — chưa coin nào biến động đủ 2%. Gõ `/gia` để kiểm tra bot vẫn hoạt động |
| Bước "Luu trang thai" đỏ | Repo thiếu quyền ghi: **Settings → Actions → General → Workflow permissions** → chọn **Read and write permissions** |
| Nhận cùng một cảnh báo lặp lại | `state.json` không được commit. Kiểm tra bước trên |
| Lịch chạy không tự kích hoạt | Repo mới đôi khi cần chạy tay (**Run workflow**) một lần trước |
