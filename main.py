import sys
from types import ModuleType

import sys
from types import ModuleType

# Robust wsgiref mock
def mock_wsgiref():
    wsgiref_mock = ModuleType("wsgiref")
    sys.modules["wsgiref"] = wsgiref_mock
    sys.modules["wsgiref.handlers"] = ModuleType("wsgiref.handlers")
    sys.modules["wsgiref.util"] = ModuleType("wsgiref.util")
    sys.modules["wsgiref.simple_server"] = ModuleType("wsgiref.simple_server")

    for mod in ["handlers", "util", "simple_server"]:
        name = f"wsgiref.{mod}"
        sys.modules[name].__path__ = []

mock_wsgiref()


import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
import ccxt
import flet as ft

# Optional import for Native Android OS Notifications inside APK
try:
    from android_notify import Notification
    ANDROID_NOTIFY_AVAILABLE = True
except ImportError:
    ANDROID_NOTIFY_AVAILABLE = False

# --- BINANCE OFFICIAL COLOR PALETTE ---
BG_DARK = "#0B0E11"       # Binance Main Background
CARD_BG = "#1E2329"       # Binance Card Surface
BORDER_COL = "#2B3139"    # Subtle Card Border
BN_YELLOW = "#FCD535"     # Binance Brand Gold/Yellow
BN_GREEN = "#0ECB81"      # Binance Buy Emerald Green
BN_RED = "#F6465D"        # Binance Sell Crimson Red
TEXT_PRIMARY = "#EAECEF"  # Crisp White-Grey
TEXT_MUTED = "#848E9C"    # Muted Subtitle Grey


def send_local_android_notification(title: str, message: str):
    if ANDROID_NOTIFY_AVAILABLE:
        try:
            Notification(title=title, message=message).send()
        except Exception:
            pass


def send_telegram_alert(bot_token: str, chat_id: str, message: str):
    if not bot_token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{bot_token.strip()}/sendMessage"
        payload = urllib.parse.urlencode({
            "chat_id": chat_id.strip(),
            "text": message,
            "parse_mode": "Markdown"
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="POST")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


def calculate_indicators(ohlcv, order_book=None, rsi_len=14, fast_len=9, slow_len=21):
    closes = [x[4] for x in ohlcv]
    lows = [x[3] for x in ohlcv]
    highs = [x[2] for x in ohlcv]
    volumes = [x[5] for x in ohlcv]

    def calc_ema(values, period):
        ema = [values[0]]
        k = 2 / (period + 1)
        for price in values[1:]:
            ema.append(price * k + ema[-1] * (1 - k))
        return ema

    ema_fast = calc_ema(closes, fast_len)
    ema_slow = calc_ema(closes, slow_len)

    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[-rsi_len:]) / rsi_len
    avg_loss = sum(losses[-rsi_len:]) / rsi_len
    rs = avg_gain / avg_loss if avg_loss != 0 else 100
    rsi = 100 - (100 / (1 + rs))

    vol_avg_20 = sum(volumes[-20:]) / 20.0
    vol_ratio = volumes[-1] / vol_avg_20 if vol_avg_20 > 0 else 1.0
    support_20 = min(lows[-20:])
    resistance_20 = max(highs[-20:])

    # Order Book Buy vs Sell Pressure (Whale Depth)
    buy_pressure_pct = 50.0
    if order_book and "bids" in order_book and "asks" in order_book:
        bid_vol = sum([b[1] for b in order_book["bids"][:15]])
        ask_vol = sum([a[1] for a in order_book["asks"][:15]])
        total_ob = bid_vol + ask_vol
        if total_ob > 0:
            buy_pressure_pct = (bid_vol / total_ob) * 100.0

    # --- PUMP SCORE CALCULATION ---
    score = 0
    if vol_ratio >= 2.0:
        score += 35
    elif vol_ratio >= 1.3:
        score += 22
    elif vol_ratio >= 1.0:
        score += 10

    if ema_fast[-1] > ema_slow[-1]:
        score += 25

    if 52 <= rsi <= 68:
        score += 20
    elif 45 <= rsi < 52:
        score += 12

    dist_to_res = ((resistance_20 - closes[-1]) / closes[-1]) * 100
    if dist_to_res <= 0.6:
        score += 10

    if buy_pressure_pct >= 58:
        score += 10

    volatility_range_pct = ((resistance_20 - support_20) / support_20) * 100
    est_pump_pct = max(1.2, min(15.0, volatility_range_pct * min(vol_ratio, 2.5) * 0.85))
    change_20_bars = ((closes[-1] - closes[-20]) / closes[-20]) * 100

    return {
        "price": closes[-1],
        "change_pct": change_20_bars,
        "rsi": rsi,
        "ema_fast_now": ema_fast[-1],
        "ema_slow_now": ema_slow[-1],
        "ema_fast_prev": ema_fast[-2],
        "ema_slow_prev": ema_slow[-2],
        "volume_now": volumes[-1],
        "vol_avg_20": vol_avg_20,
        "vol_ratio": vol_ratio,
        "support": support_20,
        "resistance": resistance_20,
        "buy_pressure": buy_pressure_pct,
        "pump_score": min(score, 98),
        "est_pump_pct": est_pump_pct,
    }


def main(page: ft.Page):
    page.title = "Binance Multi-Bot Pro"
    page.bgcolor = BG_DARK
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0

    # Load Persistent State
    saved_usdt = page.client_storage.get("usdt") or 1000.0
    saved_pnl = page.client_storage.get("total_pnl") or 0.0
    saved_wins = page.client_storage.get("wins") or 0
    saved_losses = page.client_storage.get("losses") or 0

    state = {
        "running": False,
        "usdt": float(saved_usdt),
        "crypto": 0.0,
        "entry_price": None,
        "highest_price": None,
        "dca_count": 0,
        "last_rsi": 50.0,
        "total_pnl": float(saved_pnl),
        "wins": int(saved_wins),
        "losses": int(saved_losses),
        "btc_dumping": False,
    }

    def save_settings(e=None):
        page.client_storage.set("usdt", state["usdt"])
        page.client_storage.set("total_pnl", state["total_pnl"])
        page.client_storage.set("wins", state["wins"])
        page.client_storage.set("losses", state["losses"])
        page.client_storage.set("tg_token", tg_token_input.value)
        page.client_storage.set("tg_chat", tg_chat_input.value)
        page.client_storage.set("api_key", api_key_input.value)
        page.client_storage.set("api_secret", api_secret_input.value)

    # --- HEADER BAR ---
    status_dot = ft.Container(width=10, height=10, border_radius=5, bgcolor=BN_RED)
    status_label = ft.Text("STOPPED", size=12, weight=ft.FontWeight.BOLD, color=TEXT_MUTED)

    def toggle_bot(e):
        state["running"] = not state["running"]
        if state["running"]:
            status_dot.bgcolor = BN_GREEN
            status_label.value = "ACTIVE (10s)"
            status_label.color = BN_GREEN
            start_btn.text = "STOP BOT"
            start_btn.bgcolor = BN_RED
            start_btn.color = "white"
            add_log(f"🚀 Started [{bot_mode_dropdown.value}]", BN_YELLOW)
            threading.Thread(target=bot_worker, daemon=True).start()
        else:
            status_dot.bgcolor = BN_RED
            status_label.value = "STOPPED"
            status_label.color = TEXT_MUTED
            start_btn.text = "START BOT"
            start_btn.bgcolor = BN_YELLOW
            start_btn.color = "#000000"
            add_log("⏸️ Bot paused by user.", TEXT_MUTED)
        page.update()

    start_btn = ft.ElevatedButton(
        "START BOT",
        on_click=toggle_bot,
        bgcolor=BN_YELLOW,
        color="#000000",
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=6)),
    )

    top_app_bar = ft.Container(
        bgcolor=CARD_BG,
        padding=ft.padding.symmetric(horizontal=16, vertical=12),
        border=ft.border.only(bottom=ft.BorderSide(1, BORDER_COL)),
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Row([
                    ft.Icon(ft.Icons.CANDLESTICK_CHART_ROUNDED, color=BN_YELLOW, size=26),
                    ft.Text("BINANCE", weight=ft.FontWeight.BOLD, size=18, color=BN_YELLOW),
                    ft.Text("MULTI-BOT", weight=ft.FontWeight.W_600, size=14, color=TEXT_PRIMARY),
                ], spacing=6),
                ft.Row([status_dot, status_label, start_btn], spacing=8),
            ],
        ),
    )

    # --- TAB 1: TRADE TERMINAL ---
    bot_mode_dropdown = ft.Dropdown(
        label="Select Active Bot Strategy",
        value="Scalper Bot (EMA+RSI)",
        bgcolor=CARD_BG,
        border_color=BN_YELLOW,
        text_size=13,
        options=[
            ft.dropdown.Option("Scalper Bot (EMA+RSI)"),
            ft.dropdown.Option("AI Pump Sniper Bot"),
            ft.dropdown.Option("Grid / DCA Averaging Bot"),
            ft.dropdown.Option("Support / Resistance Bounce Bot"),
        ],
    )

    pair_input = ft.TextField(
        label="Pair", value="ETH/USDT", width=135, height=45, text_size=14,
        bgcolor=CARD_BG, border_color=BORDER_COL, focused_border_color=BN_YELLOW
    )
    tf_dropdown = ft.Dropdown(
        label="TF", value="5m", width=85, height=45, text_size=13,
        bgcolor=CARD_BG, border_color=BORDER_COL,
        options=[ft.dropdown.Option("1m"), ft.dropdown.Option("5m"), ft.dropdown.Option("15m")],
    )
    order_size_input = ft.TextField(
        label="USDT Size", value="100", width=105, height=45, text_size=14,
        bgcolor=CARD_BG, border_color=BORDER_COL, focused_border_color=BN_YELLOW
    )

    live_pair_title = ft.Text("ETH/USDT", size=20, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY)
    live_price_big = ft.Text("$0.0000", size=30, weight=ft.FontWeight.BOLD, color=BN_GREEN)
    live_change_badge = ft.Container(
        bgcolor=BN_GREEN, padding=ft.padding.symmetric(horizontal=8, vertical=4), border_radius=4,
        content=ft.Text("+0.00%", size=12, weight=ft.FontWeight.BOLD, color="white")
    )

    stat_support = ft.Text("$0.00", size=13, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY)
    stat_resistance = ft.Text("$0.00", size=13, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY)
    stat_rsi = ft.Text("--", size=13, weight=ft.FontWeight.BOLD, color=BN_YELLOW)
    stat_vol = ft.Text("--", size=13, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY)

    # Order Book Buy vs Sell Pressure Gauge
    ob_buy_text = ft.Text("Buyers (Bids): 50%", size=11, color=BN_GREEN, weight=ft.FontWeight.BOLD)
    ob_sell_text = ft.Text("Sellers (Asks): 50%", size=11, color=BN_RED, weight=ft.FontWeight.BOLD)
    ob_progress_bar = ft.ProgressBar(value=0.5, color=BN_GREEN, bgcolor=BN_RED, height=8, border_radius=4)

    signal_box = ft.Container(
        bgcolor="#161A1E", padding=12, border_radius=8, border=ft.border.all(1, BORDER_COL),
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Column([
                    ft.Text("ACTIVE BOT SIGNAL", size=10, color=TEXT_MUTED, weight=ft.FontWeight.BOLD),
                    signal_banner := ft.Text("WAITING FOR START...", size=14, weight=ft.FontWeight.BOLD, color=BN_YELLOW),
                ], spacing=2),
                pump_badge_mini := ft.Container(
                    bgcolor=CARD_BG, padding=8, border_radius=6,
                    content=ft.Text("Pump Score: --%", size=12, weight=ft.FontWeight.BOLD, color=BN_YELLOW)
                )
            ]
        )
    )

    active_pos_card = ft.Container(
        bgcolor=CARD_BG, padding=12, border_radius=8, border=ft.border.all(1, BORDER_COL),
        content=ft.Column([
            ft.Row([
                ft.Text("OPEN POSITION & DCA STATUS", size=11, color=TEXT_MUTED, weight=ft.FontWeight.BOLD),
                pos_pnl_badge := ft.Text("No Open Trade", size=12, weight=ft.FontWeight.BOLD, color=TEXT_MUTED),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            pos_details_text := ft.Text("Select a Bot Mode above and press START BOT.", size=12, color=TEXT_MUTED),
        ], spacing=4)
    )

    def manual_action(side):
        try:
            symbol = pair_input.value.strip().upper()
            exchange = ccxt.binance({"enableRateLimit": True})
            ticker = exchange.fetch_ticker(symbol)
            execute_trade(side, ticker["last"], symbol, float(order_size_input.value), exchange, reason="Manual Tap")
            update_wallet_ui()
            page.update()
        except Exception as ex:
            add_log(f"Manual Order Error: {ex}", BN_RED)

    manual_buttons_row = ft.Row(
        spacing=12,
        controls=[
            ft.Container(
                expand=True,
                content=ft.ElevatedButton(
                    "BUY / LONG",
                    on_click=lambda _: manual_action("BUY"),
                    bgcolor=BN_GREEN, color="white", height=46,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=6)),
                ),
            ),
            ft.Container(
                expand=True,
                content=ft.ElevatedButton(
                    "SELL / CLOSE",
                    on_click=lambda _: manual_action("SELL"),
                    bgcolor=BN_RED, color="white", height=46,
                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=6)),
                ),
            ),
        ],
    )

    trade_tab_view = ft.Container(
        padding=14,
        content=ft.Column(
            scroll=ft.ScrollMode.ADAPTIVE,
            spacing=12,
            controls=[
                bot_mode_dropdown,
                ft.Row([pair_input, tf_dropdown, order_size_input], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Container(
                    bgcolor=CARD_BG, padding=16, border_radius=10, border=ft.border.all(1, BORDER_COL),
                    content=ft.Column([
                        ft.Row([
                            ft.Column([live_pair_title, live_price_big], spacing=2),
                            live_change_badge,
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ft.Divider(color=BORDER_COL, height=16),
                        ft.Row([
                            ft.Column([ft.Text("20-Bar Support", size=11, color=TEXT_MUTED), stat_support], spacing=2),
                            ft.Column([ft.Text("20-Bar Resistance", size=11, color=TEXT_MUTED), stat_resistance], spacing=2),
                            ft.Column([ft.Text("RSI (14)", size=11, color=TEXT_MUTED), stat_rsi], spacing=2),
                            ft.Column([ft.Text("Vol Surge", size=11, color=TEXT_MUTED), stat_vol], spacing=2),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ])
                ),
                ft.Container(
                    bgcolor=CARD_BG, padding=12, border_radius=10, border=ft.border.all(1, BORDER_COL),
                    content=ft.Column([
                        ft.Text("ORDER BOOK WHALE PRESSURE (LIVE DEPTH)", size=10, color=TEXT_MUTED, weight=ft.FontWeight.BOLD),
                        ft.Row([ob_buy_text, ob_sell_text], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ob_progress_bar,
                    ], spacing=6)
                ),
                signal_box,
                active_pos_card,
                manual_buttons_row,
            ],
        ),
    )

    # --- TAB 2: PUMP RADAR ---
    watchlist_input = ft.TextField(
        label="Radar Watchlist (Comma separated)",
        value="ETH/USDT, OP/USDT, SOL/USDT, BTC/USDT, SUI/USDT, PEPE/USDT",
        bgcolor=CARD_BG, border_color=BORDER_COL, text_size=13
    )
    auto_switch_coin = ft.Switch(
        label="Auto-Switch Bot to Top Pumping Coin (>=70%)", value=True, active_color=BN_YELLOW
    )
    pump_column = ft.Column(spacing=10)

    def select_pair(coin_pair):
        if state["crypto"] > 0:
            page.snack_bar = ft.SnackBar(ft.Text("⚠️ Close active trade before switching coin!"))
            page.snack_bar.open = True
            page.update()
            return
        pair_input.value = coin_pair
        live_pair_title.value = coin_pair
        nav_bar.selected_index = 0
        body_container.content = trade_tab_view
        page.snack_bar = ft.SnackBar(ft.Text(f"✅ Switched active pair to {coin_pair}"))
        page.snack_bar.open = True
        page.update()

    def scan_pump_watchlist(e=None):
        pump_column.controls.clear()
        pump_column.controls.append(ft.Text("🔍 Scanning Binance Order Books & Volume...", color=BN_YELLOW, size=13))
        page.update()

        def _scan_thread():
            try:
                exchange = ccxt.binance({"enableRateLimit": True})
                coins = [c.strip().upper() for c in watchlist_input.value.split(",") if c.strip()]
                results = []
                for c in coins:
                    try:
                        ohlcv = exchange.fetch_ohlcv(c, timeframe=tf_dropdown.value, limit=40)
                        ob = exchange.fetch_order_book(c, limit=15)
                        ind = calculate_indicators(ohlcv, ob)
                        results.append((c, ind))
                    except Exception:
                        continue

                results.sort(key=lambda x: x[1]["pump_score"], reverse=True)
                pump_column.controls.clear()

                if results and auto_switch_coin.value and state["crypto"] == 0:
                    top_coin, top_data = results[0]
                    if top_data["pump_score"] >= 70 and pair_input.value != top_coin:
                        pair_input.value = top_coin
                        live_pair_title.value = top_coin
                        add_log(f"🔥 Auto-Switched to {top_coin} (Pump Score: {top_data['pump_score']}%)", BN_YELLOW)

                for coin, data in results:
                    score = data["pump_score"]
                    est_pump = data["est_pump_pct"]
                    vol_x = data["vol_ratio"]
                    bar_col = BN_GREEN if score >= 70 else (BN_YELLOW if score >= 45 else TEXT_MUTED)
                    tag_text = "🔥 HIGH BREAKOUT" if score >= 70 else ("⚡ ACCUMULATING" if score >= 45 else "💤 NEUTRAL")

                    card = ft.Container(
                        bgcolor=CARD_BG, padding=14, border_radius=10, border=ft.border.all(1, BORDER_COL),
                        content=ft.Column([
                            ft.Row([
                                ft.Column([
                                    ft.Text(coin, weight=ft.FontWeight.BOLD, size=16, color=TEXT_PRIMARY),
                                    ft.Text(f"${data['price']:,.4f}  •  Vol: {vol_x:.1f}x  •  RSI: {data['rsi']:.0f}", size=12, color=TEXT_MUTED),
                                ], spacing=2),
                                ft.ElevatedButton(
                                    "Trade",
                                    on_click=lambda _, cp=coin: select_pair(cp),
                                    bgcolor=BN_YELLOW, color="#000000", height=34,
                                    style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=6)),
                                ),
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.Row([
                                ft.Text(f"{tag_text} ({score}%)", size=12, weight=ft.FontWeight.BOLD, color=bar_col),
                                ft.Text(f"Est. Potential: +{est_pump:.1f}%", size=12, weight=ft.FontWeight.BOLD, color=BN_GREEN),
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                            ft.ProgressBar(value=score / 100.0, color=bar_col, bgcolor="#0B0E11", height=6, border_radius=3),
                        ], spacing=8)
                    )
                    pump_column.controls.append(card)
                page.update()
            except Exception as ex:
                pump_column.controls.clear()
                pump_column.controls.append(ft.Text(f"Radar error: {ex}", color=BN_RED))
                page.update()

        threading.Thread(target=_scan_thread, daemon=True).start()

    radar_tab_view = ft.Container(
        padding=14,
        content=ft.Column(
            scroll=ft.ScrollMode.ADAPTIVE,
            spacing=12,
            controls=[
                ft.Row([
                    ft.Text("🚀 AI Pump & Breakout Radar", size=18, weight=ft.FontWeight.BOLD, color=BN_YELLOW),
                    ft.OutlinedButton("Refresh Radar", on_click=scan_pump_watchlist),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                watchlist_input,
                auto_switch_coin,
                pump_column,
            ],
        ),
    )

    # --- TAB 3: WALLET, PNL & LOGS ---
    wallet_usdt_text = ft.Text(f"${state['usdt']:,.2f}", size=26, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY)
    wallet_crypto_text = ft.Text("0.00000 Coins Held", size=13, color=BN_YELLOW)
    wallet_pnl_text = ft.Text("$0.00", size=18, weight=ft.FontWeight.BOLD, color=BN_GREEN)
    wallet_winrate_text = ft.Text("0% (0W / 0L)", size=18, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY)
    log_column = ft.Column(spacing=6)

    def update_wallet_ui():
        sym_coin = pair_input.value.split("/")[0]
        wallet_usdt_text.value = f"${state['usdt']:,.2f} USDT"
        wallet_crypto_text.value = f"Active Holding: {state['crypto']:.5f} {sym_coin}"
        wallet_pnl_text.value = f"${state['total_pnl']:+.2f}"
        wallet_pnl_text.color = BN_GREEN if state["total_pnl"] >= 0 else BN_RED
        tot = state["wins"] + state["losses"]
        wr = (state["wins"] / tot * 100) if tot > 0 else 0.0
        wallet_winrate_text.value = f"{wr:.0f}% ({state['wins']}W / {state['losses']}L)"

    update_wallet_ui()

    def reset_paper_wallet(e):
        state["usdt"] = 1000.0
        state["crypto"] = 0.0
        state["entry_price"] = None
        state["dca_count"] = 0
        state["total_pnl"] = 0.0
        state["wins"] = 0
        state["losses"] = 0
        save_settings()
        update_wallet_ui()
        add_log("🔄 Paper Wallet reset to $1,000.00 USDT", BN_YELLOW)
        page.update()

    def add_log(msg, color=TEXT_PRIMARY):
        ts = datetime.now().strftime("%H:%M:%S")
        log_column.controls.insert(
            0,
            ft.Container(
                bgcolor=CARD_BG, padding=10, border_radius=6, border=ft.border.all(1, BORDER_COL),
                content=ft.Text(f"[{ts}] {msg}", color=color, size=12)
            )
        )
        if len(log_column.controls) > 35:
            log_column.controls.pop()
        page.update()

    wallet_tab_view = ft.Container(
        padding=14,
        content=ft.Column(
            scroll=ft.ScrollMode.ADAPTIVE,
            spacing=12,
            controls=[
                ft.Container(
                    bgcolor=CARD_BG, padding=16, border_radius=10, border=ft.border.all(1, BORDER_COL),
                    content=ft.Column([
                        ft.Row([
                            ft.Text("ESTIMATED PAPER BALANCE", size=11, color=TEXT_MUTED, weight=ft.FontWeight.BOLD),
                            ft.TextButton("Reset $1,000", on_click=reset_paper_wallet),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        wallet_usdt_text,
                        wallet_crypto_text,
                        ft.Divider(color=BORDER_COL, height=16),
                        ft.Row([
                            ft.Column([ft.Text("Realized PnL", size=11, color=TEXT_MUTED), wallet_pnl_text]),
                            ft.Column([ft.Text("Bot Win Rate", size=11, color=TEXT_MUTED), wallet_winrate_text]),
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    ])
                ),
                ft.Text("📋 Live Trade Execution History", size=15, weight=ft.FontWeight.BOLD, color=TEXT_PRIMARY),
                log_column,
            ],
        ),
    )

    # --- TAB 4: PRO CONFIG & RISK SHIELD ---
    sl_input = ft.TextField(label="Stop-Loss (%)", value="2.0", width=150, bgcolor=CARD_BG, border_color=BORDER_COL)
    tp_input = ft.TextField(label="Take-Profit (%)", value="3.5", width=150, bgcolor=CARD_BG, border_color=BORDER_COL)
    max_loss_input = ft.TextField(label="Daily Max Loss Limit ($)", value="50.0", bgcolor=CARD_BG, border_color=BORDER_COL)
    trailing_sl_switch = ft.Switch(label="Trailing Stop-Loss (Locks Profit on Pump)", value=True, active_color=BN_YELLOW)
    btc_shield_switch = ft.Switch(label="BTC Crash Shield (Pause Buy if BTC Dumps)", value=True, active_color=BN_YELLOW)

    rsi_buy_slider = ft.Slider(min=15, max=45, divisions=30, value=32, active_color=BN_GREEN, label="Buy RSI < {value}")
    rsi_sell_slider = ft.Slider(min=55, max=85, divisions=30, value=68, active_color=BN_RED, label="Sell RSI > {value}")

    local_push_switch = ft.Switch(label="Android Status-Bar Notifications", value=True, active_color=BN_YELLOW)
    tg_token_input = ft.TextField(
        label="Telegram Bot Token", password=True, bgcolor=CARD_BG, border_color=BORDER_COL,
        value=page.client_storage.get("tg_token") or "", on_change=save_settings
    )
    tg_chat_input = ft.TextField(
        label="Telegram Chat ID", bgcolor=CARD_BG, border_color=BORDER_COL,
        value=page.client_storage.get("tg_chat") or "", on_change=save_settings
    )

    mode_switch = ft.Switch(label="LIVE BINANCE API TRADING (Real Money)", value=False, active_color=BN_RED)
    api_key_input = ft.TextField(
        label="Binance API Key", password=True, bgcolor=CARD_BG, border_color=BORDER_COL,
        value=page.client_storage.get("api_key") or "", on_change=save_settings
    )
    api_secret_input = ft.TextField(
        label="Binance API Secret", password=True, bgcolor=CARD_BG, border_color=BORDER_COL,
        value=page.client_storage.get("api_secret") or "", on_change=save_settings
    )

    def dispatch_notifications(title: str, body: str):
        if local_push_switch.value:
            send_local_android_notification(title, body)
        if tg_token_input.value and tg_chat_input.value:
            threading.Thread(
                target=send_telegram_alert,
                args=(tg_token_input.value, tg_chat_input.value, f"*{title}*\n{body}"),
                daemon=True,
            ).start()
        page.snack_bar = ft.SnackBar(ft.Text(f"{title}: {body}"))
        page.snack_bar.open = True
        page.update()

    settings_tab_view = ft.Container(
        padding=14,
        content=ft.Column(
            scroll=ft.ScrollMode.ADAPTIVE,
            spacing=12,
            controls=[
                ft.Text("🛡️ Pro Risk & Crash Protection", size=16, weight=ft.FontWeight.BOLD, color=BN_YELLOW),
                ft.Row([sl_input, tp_input], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                max_loss_input,
                trailing_sl_switch,
                btc_shield_switch,
                ft.Divider(color=BORDER_COL),
                ft.Text("📈 RSI Indicator Thresholds", size=16, weight=ft.FontWeight.BOLD, color=BN_YELLOW),
                ft.Text("Oversold Buy Trigger (RSI <):", size=12, color=TEXT_MUTED),
                rsi_buy_slider,
                ft.Text("Overbought Sell Trigger (RSI >):", size=12, color=TEXT_MUTED),
                rsi_sell_slider,
                ft.Divider(color=BORDER_COL),
                ft.Text("🔔 Push & Telegram Alerts", size=16, weight=ft.FontWeight.BOLD, color=BN_YELLOW),
                local_push_switch,
                tg_token_input,
                tg_chat_input,
                ft.OutlinedButton(
                    "Send Test Notification",
                    on_click=lambda _: dispatch_notifications("Binance Multi-Bot Pro", "Test alert successful!"),
                ),
                ft.Divider(color=BORDER_COL),
                ft.Text("🔑 Exchange API Connection", size=16, weight=ft.FontWeight.BOLD, color=BN_YELLOW),
                mode_switch,
                api_key_input,
                api_secret_input,
            ],
        ),
    )

    # --- TRADE EXECUTION & MULTI-BOT WORKER ENGINE ---
    def execute_trade(side, price, symbol, order_usdt, exchange, reason="Signal"):
        qty = round(order_usdt / price, 5)
        mode_label = "LIVE" if mode_switch.value else "PAPER"

        if not mode_switch.value:
            if side == "BUY" and state["usdt"] >= order_usdt:
                state["usdt"] -= order_usdt
                if state["crypto"] > 0 and state["entry_price"]:
                    # DCA Average Price calculation
                    total_cost = (state["crypto"] * state["entry_price"]) + order_usdt
                    state["crypto"] += qty
                    state["entry_price"] = total_cost / state["crypto"]
                    state["dca_count"] += 1
                else:
                    state["crypto"] = qty
                    state["entry_price"] = price
                    state["highest_price"] = price
                    state["dca_count"] = 0

                msg = f"Bought {qty} {symbol} @ ${price:,.4f} ({reason})"
                add_log(f"🟢 [{mode_label}] {msg}", BN_GREEN)
                dispatch_notifications(f"🟢 {mode_label} BUY: {symbol}", msg)
                update_wallet_ui()
                save_settings()

            elif side == "SELL" and state["crypto"] > 0:
                sold_qty = state["crypto"]
                proceeds = sold_qty * price
                pnl = proceeds - (sold_qty * state["entry_price"])
                state["usdt"] += proceeds
                state["crypto"] = 0.0
                state["entry_price"] = None
                state["highest_price"] = None
                state["dca_count"] = 0

                state["total_pnl"] += pnl
                if pnl >= 0:
                    state["wins"] += 1
                else:
                    state["losses"] += 1
                update_wallet_ui()
                save_settings()

                msg = f"Sold {sold_qty:.5f} {symbol} @ ${price:,.4f} | PnL: ${pnl:+.2f} ({reason})"
                add_log(f"🔴 [{mode_label}] {msg}", BN_RED)
                dispatch_notifications(f"🔴 {mode_label} SELL: {symbol}", msg)
        else:
            if side == "BUY":
                exchange.create_market_buy_order(symbol, qty)
                state["crypto"] += qty
                state["entry_price"] = price
                state["highest_price"] = price
                msg = f"Bought {qty} {symbol} @ ${price:,.4f} ({reason})"
                add_log(f"🟢 [LIVE] {msg}", BN_GREEN)
                dispatch_notifications(f"🟢 LIVE BUY: {symbol}", msg)
            elif side == "SELL" and state["crypto"] > 0:
                sold_qty = state["crypto"]
                exchange.create_market_sell_order(symbol, sold_qty)
                state["crypto"] = 0.0
                state["entry_price"] = None
                state["highest_price"] = None
                msg = f"Sold {sold_qty} {symbol} @ ${price:,.4f} ({reason})"
                add_log(f"🔴 [LIVE] {msg}", BN_RED)
                dispatch_notifications(f"🔴 LIVE SELL: {symbol}", msg)

    def bot_worker():
        scan_counter = 0
        while state["running"]:
            try:
                # 1. Check Daily Max Loss Circuit Breaker
                max_loss_limit = float(max_loss_input.value or 50.0)
                if state["total_pnl"] <= -abs(max_loss_limit):
                    state["running"] = False
                    status_dot.bgcolor = BN_RED
                    status_label.value = "MAX LOSS HIT"
                    add_log(f"🛑 Circuit Breaker: Daily Max Loss (-${max_loss_limit}) reached. Bot stopped.", BN_RED)
                    page.update()
                    break

                symbol = pair_input.value.strip().upper()
                tf = tf_dropdown.value
                order_usdt = float(order_size_input.value)
                sl_pct = float(sl_input.value)
                tp_pct = float(tp_input.value)
                active_bot = bot_mode_dropdown.value

                config = {"enableRateLimit": True}
                if mode_switch.value and api_key_input.value:
                    config["apiKey"] = api_key_input.value.strip()
                    config["secret"] = api_secret_input.value.strip()

                exchange = ccxt.binance(config)

                # 2. BTC Crash Shield Check
                btc_safe = True
                if btc_shield_switch.value and symbol != "BTC/USDT":
                    btc_ohlcv = exchange.fetch_ohlcv("BTC/USDT", timeframe="5m", limit=5)
                    btc_drop = ((btc_ohlcv[-1][4] - btc_ohlcv[0][1]) / btc_ohlcv[0][1]) * 100
                    if btc_drop <= -1.2:
                        btc_safe = False

                ohlcv = exchange.fetch_ohlcv(symbol, timeframe=tf, limit=60)
                ob = exchange.fetch_order_book(symbol, limit=15)
                ind = calculate_indicators(ohlcv, ob)

                price = ind["price"]
                rsi = ind["rsi"]
                state["last_rsi"] = rsi

                # Update Ticker Card
                live_pair_title.value = f"{symbol}  •  {tf}"
                live_price_big.value = f"${price:,.4f}"
                is_up = ind["change_pct"] >= 0
                live_price_big.color = BN_GREEN if is_up else BN_RED
                live_change_badge.bgcolor = BN_GREEN if is_up else BN_RED
                live_change_badge.content.value = f"{ind['change_pct']:+.2f}%"

                stat_support.value = f"${ind['support']:,.3f}"
                stat_resistance.value = f"${ind['resistance']:,.3f}"
                stat_rsi.value = f"{rsi:.1f}"
                stat_vol.value = f"{ind['vol_ratio']:.1f}x"

                bp = ind["buy_pressure"]
                ob_buy_text.value = f"Buyers: {bp:.0f}%"
                ob_sell_text.value = f"Sellers: {100 - bp:.0f}%"
                ob_progress_bar.value = bp / 100.0
                pump_badge_mini.content.value = f"Pump: {ind['pump_score']}% (+{ind['est_pump_pct']:.1f}%)"

                vol_spike = ind["volume_now"] >= (ind["vol_avg_20"] * 1.2)
                bull_cross = ind["ema_fast_prev"] <= ind["ema_slow_prev"] and ind["ema_fast_now"] > ind["ema_slow_now"]
                bear_cross = ind["ema_fast_prev"] >= ind["ema_slow_prev"] and ind["ema_fast_now"] < ind["ema_slow_now"]

                # --- 4 DISTINCT BOT STRATEGY ENGINES ---
                buy_sig = False
                sell_sig = False

                if active_bot == "Scalper Bot (EMA+RSI)":
                    buy_sig = (rsi <= rsi_buy_slider.value) or (bull_cross and vol_spike)
                    sell_sig = (rsi >= rsi_sell_slider.value) or bear_cross

                elif active_bot == "AI Pump Sniper Bot":
                    buy_sig = (ind["pump_score"] >= 72) and (bp >= 56) and (rsi < 68)
                    sell_sig = (rsi >= 74) or (bp < 42)

                elif active_bot == "Support / Resistance Bounce Bot":
                    dist_sup = ((price - ind["support"]) / ind["support"]) * 100
                    dist_res = ((ind["resistance"] - price) / price) * 100
                    buy_sig = (dist_sup <= 0.5) and (rsi < 45)
                    sell_sig = (dist_res <= 0.4) or (rsi > 68)

                elif active_bot == "Grid / DCA Averaging Bot":
                    buy_sig = (rsi <= 38) or (bull_cross and vol_spike)
                    sell_sig = (rsi >= 66)

                # Active Position, DCA & Trailing SL Check
                risk_exit_reason = None
                if state["crypto"] > 0 and state["entry_price"]:
                    entry = state["entry_price"]
                    if price > (state["highest_price"] or entry):
                        state["highest_price"] = price

                    change_from_entry_pct = ((price - entry) / entry) * 100
                    drop_from_peak_pct = ((state["highest_price"] - price) / state["highest_price"]) * 100

                    pos_pnl_badge.value = f"PnL: {change_from_entry_pct:+.2f}% (DCA #{state['dca_count']})"
                    pos_pnl_badge.color = BN_GREEN if change_from_entry_pct >= 0 else BN_RED
                    pos_details_text.value = f"Avg Entry: ${entry:,.4f}  |  Peak: ${state['highest_price']:,.4f}  |  Qty: {state['crypto']:.4f}"

                    # Grid / DCA Safety Order Logic (Buy Dip if enabled)
                    if active_bot == "Grid / DCA Averaging Bot" and state["dca_count"] < 2 and change_from_entry_pct <= -2.0:
                        execute_trade("BUY", price, symbol, order_usdt, exchange, reason=f"DCA Safety Dip #{state['dca_count']+1}")
                    elif change_from_entry_pct >= tp_pct:
                        risk_exit_reason = f"Take-Profit (+{change_from_entry_pct:.2f}%)"
                    elif change_from_entry_pct <= -sl_pct and active_bot != "Grid / DCA Averaging Bot":
                        risk_exit_reason = f"Stop-Loss ({change_from_entry_pct:.2f}%)"
                    elif trailing_sl_switch.value and change_from_entry_pct > 0.8 and drop_from_peak_pct >= sl_pct:
                        risk_exit_reason = f"Trailing SL (+{change_from_entry_pct:.2f}%)"
                else:
                    pos_pnl_badge.value = "No Open Position"
                    pos_pnl_badge.color = TEXT_MUTED
                    pos_details_text.value = f"Active Mode: {active_bot}"

                if not btc_safe and state["crypto"] == 0:
                    signal_banner.value = "🛡️ BTC CRASH SHIELD ACTIVE (BUY PAUSED)"
                    signal_banner.color = BN_RED
                elif buy_sig and state["crypto"] == 0 and btc_safe:
                    signal_banner.value = f"🟢 BUY ({active_bot.split()[0]})"
                    signal_banner.color = BN_GREEN
                    execute_trade("BUY", price, symbol, order_usdt, exchange, reason=active_bot.split()[0])
                elif state["crypto"] > 0 and (risk_exit_reason or sell_sig):
                    reason_str = risk_exit_reason if risk_exit_reason else f"{active_bot.split()[0]} Exit"
                    signal_banner.value = f"🔴 SELL ({reason_str})"
                    signal_banner.color = BN_RED
                    execute_trade("SELL", price, symbol, order_usdt, exchange, reason=reason_str)
                else:
                    signal_banner.value = f"⚪ SCANNING ({active_bot.split()[0]})..."
                    signal_banner.color = BN_YELLOW

                if scan_counter % 3 == 0:
                    scan_pump_watchlist()
                scan_counter += 1

                page.update()
            except Exception as ex:
                add_log(f"Error: {str(ex)[:60]}", BN_RED)

            time.sleep(10)

    # --- BOTTOM NAVIGATION BAR ---
    body_container = ft.Container(expand=True, content=trade_tab_view)

    def on_nav_change(e):
        idx = e.control.selected_index
        if idx == 0:
            body_container.content = trade_tab_view
        elif idx == 1:
            body_container.content = radar_tab_view
            if not pump_column.controls:
                scan_pump_watchlist()
        elif idx == 2:
            update_wallet_ui()
            body_container.content = wallet_tab_view
        elif idx == 3:
            body_container.content = settings_tab_view
        page.update()

    nav_bar = ft.NavigationBar(
        bgcolor=CARD_BG,
        indicator_color=BN_YELLOW,
        selected_index=0,
        on_change=on_nav_change,
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.CANDLESTICK_CHART_OUTLINED, selected_icon=ft.Icons.CANDLESTICK_CHART, label="Trade"),
            ft.NavigationBarDestination(icon=ft.Icons.ROCKET_LAUNCH_OUTLINED, selected_icon=ft.Icons.ROCKET_LAUNCH, label="Pump Radar"),
            ft.NavigationBarDestination(icon=ft.Icons.ACCOUNT_BALANCE_WALLET_OUTLINED, selected_icon=ft.Icons.ACCOUNT_BALANCE_WALLET, label="Wallet"),
            ft.NavigationBarDestination(icon=ft.Icons.TUNE_OUTLINED, selected_icon=ft.Icons.TUNE, label="Bot Config"),
        ],
    )

    page.navigation_bar = nav_bar
    page.add(top_app_bar, body_container)


ft.app(target=main)
