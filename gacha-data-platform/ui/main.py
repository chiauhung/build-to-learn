"""NiceGUI demo UI for Husbando Chronicles.

One hardcoded player ("DemoPlayer") — no login/auth.
Purpose: drive live data into Postgres to demo the end-to-end CDC pipeline.

Run with:
    make ui
    # or: uv run python -m ui.main
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import psycopg
from nicegui import app, ui

from generator.db import (
    get_connection,
    insert_player_inventory,
    insert_player_pity,
    insert_pulls,
    insert_transactions,
)
from generator.economy import PACKAGES, create_transaction
from generator.gacha import load_banners, load_characters, load_gacha_config
from generator.models import InventoryEntry, Player, PlayerPity

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEMO_PLAYER_ID = UUID("00000000-0000-0000-0000-000000000001")
DEMO_PLAYER_USERNAME = "DemoPlayer"
DEMO_PLAYER_REGION = "APAC"

RARITY_COLOR = {
    "SSR": "#f4b548",
    "SR": "#a855f7",
    "R": "#6b7280",
}

RARITY_LABEL_COLOR = {
    "SSR": "text-yellow-400",
    "SR": "text-purple-400",
    "R": "text-gray-400",
}

# ---------------------------------------------------------------------------
# Seed data (loaded once at startup)
# ---------------------------------------------------------------------------

ALL_CHARACTERS: list[dict] = load_characters()
ALL_BANNERS: list[dict] = load_banners()
GACHA_CONFIG: dict = load_gacha_config()

# Character lookup by id
CHAR_BY_ID: dict[str, dict] = {c["id"]: c for c in ALL_CHARACTERS}

# ---------------------------------------------------------------------------
# App state (in-memory, one session)
# ---------------------------------------------------------------------------

state: dict = {
    "crystal_balance": 0,
    "pity": {},        # banner_type -> PlayerPity
    "inventory": {},   # character_id -> constellation count
    "first_buys": {},  # package_id -> bool (has bought before)
    "selected_banner": None,
}


# ---------------------------------------------------------------------------
# Postgres helpers
# ---------------------------------------------------------------------------

def _ensure_demo_player(conn: psycopg.Connection) -> None:
    """Create DemoPlayer if not exists, load their balance."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO players (id, username, region, crystal_balance, registered_at)
            VALUES (%s, %s, %s, 0, NOW())
            ON CONFLICT (username) DO NOTHING
            """,
            (str(DEMO_PLAYER_ID), DEMO_PLAYER_USERNAME, DEMO_PLAYER_REGION),
        )
        cur.execute(
            "SELECT crystal_balance FROM players WHERE id = %s",
            (str(DEMO_PLAYER_ID),),
        )
        row = cur.fetchone()
        state["crystal_balance"] = row[0] if row else 0


def _load_pity(conn: psycopg.Connection) -> None:
    """Load pity state from Postgres into memory."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT banner_type, pity_count, guaranteed_next FROM player_pity WHERE player_id = %s",
            (str(DEMO_PLAYER_ID),),
        )
        for banner_type, pity_count, guaranteed_next in cur.fetchall():
            state["pity"][banner_type] = PlayerPity(
                player_id=DEMO_PLAYER_ID,
                banner_type=banner_type,
                pity_count=pity_count,
                guaranteed_next=guaranteed_next,
            )


def _load_inventory(conn: psycopg.Connection) -> None:
    """Load inventory from Postgres into memory."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT character_id, constellation FROM player_inventory WHERE player_id = %s",
            (str(DEMO_PLAYER_ID),),
        )
        for char_id, constellation in cur.fetchall():
            state["inventory"][char_id] = constellation


def _load_first_buys(conn: psycopg.Connection) -> None:
    """Check which packages DemoPlayer has already bought."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT package_id FROM transactions WHERE player_id = %s AND payment_status = 'success'",
            (str(DEMO_PLAYER_ID),),
        )
        for (pkg_id,) in cur.fetchall():
            state["first_buys"][pkg_id] = True


def _update_crystal_balance(conn: psycopg.Connection, delta: int) -> int:
    """Atomically adjust crystal balance, return new balance."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE players SET crystal_balance = crystal_balance + %s WHERE id = %s RETURNING crystal_balance",
            (delta, str(DEMO_PLAYER_ID)),
        )
        row = cur.fetchone()
        return row[0] if row else state["crystal_balance"]


def _get_or_init_pity(banner_type: str) -> PlayerPity:
    if banner_type not in state["pity"]:
        state["pity"][banner_type] = PlayerPity(
            player_id=DEMO_PLAYER_ID,
            banner_type=banner_type,
        )
    return state["pity"][banner_type]


# ---------------------------------------------------------------------------
# Startup: initialise DB state
# ---------------------------------------------------------------------------

def startup() -> None:
    try:
        conn = get_connection()
        with conn:
            _ensure_demo_player(conn)
            _load_pity(conn)
            _load_inventory(conn)
            _load_first_buys(conn)
        conn.close()
        print(f"[UI] DemoPlayer ready — balance: {state['crystal_balance']} crystals")
    except Exception as exc:
        print(f"[UI] WARNING: Could not connect to Postgres: {exc}")
        print("[UI] Running in no-DB mode — pulls won't persist.")


# ---------------------------------------------------------------------------
# Pull actions
# ---------------------------------------------------------------------------

def do_pull(count: int, banner: dict) -> list[dict]:
    """Execute pull(s), persist to DB, return list of result dicts."""
    from generator.gacha import perform_multi_pull, perform_pull

    banner_type = banner["type"]
    pity = _get_or_init_pity(banner_type)
    cost = GACHA_CONFIG["crystals_per_pull"] * count

    if state["crystal_balance"] < cost:
        ui.notify(f"Not enough crystals! Need {cost}, have {state['crystal_balance']}.", color="negative")
        return []

    if count == 1:
        pull, new_pity = perform_pull(pity, banner, ALL_CHARACTERS, GACHA_CONFIG)
        pulls = [pull]
    else:
        pulls, new_pity = perform_multi_pull(pity, banner, ALL_CHARACTERS, count, GACHA_CONFIG)

    state["pity"][banner_type] = new_pity

    # Build inventory entries
    inventory_entries = [
        InventoryEntry(player_id=DEMO_PLAYER_ID, character_id=p.character_id)
        for p in pulls
    ]

    try:
        conn = get_connection()
        with conn:
            insert_pulls(conn, pulls)
            insert_player_pity(conn, [new_pity])
            insert_player_inventory(conn, inventory_entries)
            new_balance = _update_crystal_balance(conn, -cost)
        conn.close()
        state["crystal_balance"] = new_balance
    except Exception as exc:
        print(f"[UI] DB write failed: {exc}")
        state["crystal_balance"] -= cost

    # Update local inventory
    for entry in inventory_entries:
        cid = entry.character_id
        if cid in state["inventory"]:
            state["inventory"][cid] = min(state["inventory"][cid] + 1, 6)
        else:
            state["inventory"][cid] = 0

    return [
        {
            "character_id": p.character_id,
            "name": CHAR_BY_ID[p.character_id]["name"],
            "rarity": p.rarity,
        }
        for p in pulls
    ]


def do_topup(package: dict) -> None:
    """Execute a top-up purchase, persist to DB, update balance."""
    is_first = package["id"] not in state["first_buys"]
    txn = create_transaction(
        DEMO_PLAYER_ID,
        package,
        is_first_buy=is_first,
        region=DEMO_PLAYER_REGION,
    )

    try:
        conn = get_connection()
        with conn:
            insert_transactions(conn, [txn])
            if txn.crystals_added > 0:
                new_balance = _update_crystal_balance(conn, txn.crystals_added)
                state["crystal_balance"] = new_balance
        conn.close()
    except Exception as exc:
        print(f"[UI] DB write failed: {exc}")
        if txn.crystals_added > 0:
            state["crystal_balance"] += txn.crystals_added

    if txn.payment_status == "success":
        if is_first:
            state["first_buys"][package["id"]] = True
        ui.notify(
            f"Purchased {package['name']}! +{txn.crystals_added} crystals"
            + (" (First-time bonus included!)" if is_first and txn.crystals_added > package["crystals"] else ""),
            color="positive",
        )
    elif txn.payment_status == "failed":
        ui.notify("Payment failed. Try again.", color="negative")
    else:
        ui.notify("Payment refunded.", color="warning")


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _rarity_border_style(rarity: str) -> str:
    color = RARITY_COLOR.get(rarity, "#6b7280")
    glow = f"0 0 12px {color}88"
    return f"border: 2px solid {color}; box-shadow: {glow};"


def _card_css(rarity: str, greyed: bool = False) -> str:
    base = "border-radius: 8px; overflow: hidden; position: relative;"
    if greyed:
        return base + "filter: grayscale(100%) brightness(0.4);"
    return base + _rarity_border_style(rarity)


# ---------------------------------------------------------------------------
# UI build
# ---------------------------------------------------------------------------

def build_ui() -> None:
    app.add_static_files("/portraits", "seed/portraits")

    ui.add_head_html("""
    <style>
      body { background: #0f0a1e; }

      .gacha-bg {
        background: linear-gradient(135deg, #0f0a1e 0%, #1a0f3a 50%, #0d1a2e 100%);
        min-height: 100vh;
      }

      .gold-text { color: #f4b548; }
      .purple-text { color: #a855f7; }
      .grey-text { color: #6b7280; }

      /* Card flip */
      .card-scene {
        perspective: 600px;
        width: 120px;
        height: 160px;
      }
      .card-flipper {
        width: 100%;
        height: 100%;
        position: relative;
        transform-style: preserve-3d;
        transition: transform 0.6s ease;
      }
      .card-flipper.flipped {
        transform: rotateY(180deg);
      }
      .card-front, .card-back {
        position: absolute;
        width: 100%;
        height: 100%;
        backface-visibility: hidden;
        border-radius: 8px;
        overflow: hidden;
        display: flex;
        align-items: center;
        justify-content: center;
      }
      .card-back {
        background: linear-gradient(135deg, #2d1b69, #1a0f3a);
        border: 2px solid #4c1d95;
      }
      .card-back::before {
        content: "✦";
        font-size: 48px;
        color: #7c3aed44;
      }
      .card-front {
        transform: rotateY(180deg);
        background: #1a0f3a;
      }
      .card-front img {
        width: 100%;
        height: 100%;
        object-fit: cover;
      }
      .card-label {
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        background: linear-gradient(transparent, rgba(0,0,0,0.85));
        padding: 4px 4px 6px;
        text-align: center;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.5px;
      }

      .section-card {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        padding: 20px;
      }

      .balance-pill {
        background: rgba(244, 181, 72, 0.15);
        border: 1px solid rgba(244, 181, 72, 0.4);
        border-radius: 20px;
        padding: 6px 16px;
        color: #f4b548;
        font-weight: 700;
        font-size: 16px;
      }

      .pkg-card {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 10px;
        padding: 16px;
        transition: border-color 0.2s;
      }
      .pkg-card:hover {
        border-color: rgba(244, 181, 72, 0.5);
      }

      .char-card {
        border-radius: 8px;
        overflow: hidden;
        width: 100px;
        text-align: center;
      }
      .char-card img {
        width: 100px;
        height: 134px;
        object-fit: cover;
        display: block;
      }
    </style>
    """)

    with ui.column().classes("gacha-bg w-full items-center"):
        # ── Header ───────────────────────────────────────────────────────
        with ui.row().classes("w-full items-center justify-between q-pa-md").style("max-width: 1400px;"):
            ui.label("Husbando Chronicles").style(
                "font-size: 24px; font-weight: 900; "
                "background: linear-gradient(90deg, #f4b548, #a855f7); "
                "-webkit-background-clip: text; -webkit-text-fill-color: transparent;"
            )
            balance_label = ui.label(f"💎 {state['crystal_balance']}").classes("balance-pill")

        with ui.column().classes("w-full q-px-md gap-6").style("max-width: 1400px;"):

            # ── Banner + Pull section ─────────────────────────────────────
            with ui.element("div").classes("section-card"):
                ui.label("Banner Pull").style(
                    "font-size: 18px; font-weight: 700; color: #e2d5ff; margin-bottom: 12px; display: block;"
                )

                banner_options = {b["name"]: b for b in ALL_BANNERS}
                banner_names = list(banner_options.keys())

                with ui.row().classes("items-center gap-4 flex-wrap"):
                    banner_select = ui.select(
                        options=banner_names,
                        value=banner_names[0],
                        label="Select Banner",
                    ).style("min-width: 240px; background: rgba(255,255,255,0.06); color: white;")

                    pity_label = ui.label("").style("color: #a78bfa; font-size: 13px;")
                    cost_label = ui.label("").style("color: #94a3b8; font-size: 13px;")

                def _refresh_banner_info(banner_name: str) -> None:
                    banner = banner_options[banner_name]
                    banner_type = banner["type"]
                    pity = _get_or_init_pity(banner_type)
                    pity_label.set_text(f"Pity: {pity.pity_count}/90 | {'Guaranteed ✓' if pity.guaranteed_next else '50/50'}")
                    cost_label.set_text(f"Single: 160💎 | 10-Pull: 1600💎")

                banner_select.on_value_change(lambda e: _refresh_banner_info(e.value))
                _refresh_banner_info(banner_names[0])

                # Pull result area
                pull_area = ui.row().classes("flex-wrap gap-3 mt-4 min-h-[180px] items-start")

                def _render_pull_results(results: list[dict]) -> None:
                    pull_area.clear()
                    with pull_area:
                        for i, r in enumerate(results):
                            char_id = r["character_id"]
                            rarity = r["rarity"]
                            name = r["name"]
                            color = RARITY_COLOR[rarity]

                            scene = ui.element("div").classes("card-scene")
                            with scene:
                                flipper = ui.element("div").classes("card-flipper")
                                with flipper:
                                    # Back face
                                    ui.element("div").classes("card-back")
                                    # Front face
                                    front = ui.element("div").classes("card-front").style(
                                        _rarity_border_style(rarity)
                                    )
                                    with front:
                                        ui.image(f"/portraits/{char_id}.webp").style(
                                            "width: 100%; height: 100%; object-fit: cover;"
                                        )
                                        ui.element("div").classes("card-label").style(
                                            f"color: {color};"
                                        ).text = name

                            # Stagger flip animation
                            delay_ms = 200 + i * 150
                            ui.timer(
                                delay_ms / 1000,
                                lambda f=flipper: f.classes(add="flipped"),
                                once=True,
                            )

                def on_single_pull() -> None:
                    banner = banner_options[banner_select.value]
                    results = do_pull(1, banner)
                    if results:
                        _render_pull_results(results)
                        balance_label.set_text(f"💎 {state['crystal_balance']}")
                        _refresh_banner_info(banner_select.value)

                def on_multi_pull() -> None:
                    banner = banner_options[banner_select.value]
                    results = do_pull(10, banner)
                    if results:
                        _render_pull_results(results)
                        balance_label.set_text(f"💎 {state['crystal_balance']}")
                        _refresh_banner_info(banner_select.value)

                with ui.row().classes("gap-3 mt-2"):
                    ui.button("Single Pull  (160💎)", on_click=on_single_pull).style(
                        "background: linear-gradient(90deg, #4c1d95, #7c3aed); color: white; "
                        "font-weight: 700; border-radius: 8px; padding: 10px 20px;"
                    )
                    ui.button("10-Pull  (1600💎)", on_click=on_multi_pull).style(
                        "background: linear-gradient(90deg, #92400e, #d97706); color: white; "
                        "font-weight: 700; border-radius: 8px; padding: 10px 20px;"
                    )

            # ── Top-up section ───────────────────────────────────────────
            with ui.element("div").classes("section-card"):
                ui.label("Top-Up Crystals").style(
                    "font-size: 18px; font-weight: 700; color: #e2d5ff; margin-bottom: 12px; display: block;"
                )

                pkg_balance_label = ui.label(f"Current balance: 💎 {state['crystal_balance']}").style(
                    "color: #f4b548; font-size: 14px; margin-bottom: 12px; display: block;"
                )

                with ui.grid(columns=6).classes("w-full gap-3"):
                    for pkg in PACKAGES:
                        with ui.element("div").classes("pkg-card"):
                            first_bonus = pkg.get("first_time_bonus", 0)
                            ui.label(pkg["name"]).style(
                                "font-size: 15px; font-weight: 700; color: #e2d5ff;"
                            )
                            ui.label(f"💎 {pkg['crystals']} crystals").style("color: #a78bfa; font-size: 13px;")
                            if first_bonus > 0:
                                ui.label(f"First-time: +{first_bonus} bonus").style(
                                    "color: #f4b548; font-size: 11px;"
                                )
                            if pkg.get("daily_crystals"):
                                ui.label(
                                    f"Daily: +{pkg['daily_crystals']}💎 for {pkg['duration_days']}d"
                                ).style("color: #94a3b8; font-size: 11px;")
                            ui.label(f"${pkg['price_usd']:.2f}").style(
                                "color: #34d399; font-size: 13px; font-weight: 600;"
                            )

                            def make_buy_handler(p: dict):
                                def handler():
                                    do_topup(p)
                                    balance_label.set_text(f"💎 {state['crystal_balance']}")
                                    pkg_balance_label.set_text(
                                        f"Current balance: 💎 {state['crystal_balance']}"
                                    )
                                return handler

                            ui.button("Buy", on_click=make_buy_handler(pkg)).style(
                                "background: linear-gradient(90deg, #065f46, #059669); color: white; "
                                "font-weight: 700; border-radius: 6px; margin-top: 8px; width: 100%;"
                            )

            # ── Collection section ───────────────────────────────────────
            with ui.element("div").classes("section-card"):
                with ui.row().classes("items-center justify-between"):
                    ui.label("Collection").style(
                        "font-size: 18px; font-weight: 700; color: #e2d5ff;"
                    )
                    collection_count = ui.label("").style("color: #94a3b8; font-size: 13px;")

                collection_grid = ui.row().classes("flex-wrap gap-3 mt-3")

                def _render_collection() -> None:
                    collection_grid.clear()
                    owned_count = sum(1 for c in ALL_CHARACTERS if c["id"] in state["inventory"])
                    collection_count.set_text(f"{owned_count}/{len(ALL_CHARACTERS)} owned")

                    with collection_grid:
                        # SSR first, then SR, then R
                        for char in sorted(
                            ALL_CHARACTERS,
                            key=lambda c: {"SSR": 0, "SR": 1, "R": 2}[c["rarity"]],
                        ):
                            char_id = char["id"]
                            rarity = char["rarity"]
                            owned = char_id in state["inventory"]
                            constellation = state["inventory"].get(char_id, 0)
                            color = RARITY_COLOR[rarity]

                            with ui.element("div").classes("char-card").style(
                                _rarity_border_style(rarity)
                                if owned
                                else "border: 2px solid #374151; border-radius: 8px; overflow: hidden;"
                            ):
                                img = ui.image(f"/portraits/{char_id}.webp").style(
                                    "width: 100px; height: 134px; object-fit: cover; display: block;"
                                    + ("" if owned else " filter: grayscale(100%) brightness(0.35);")
                                )
                                with ui.element("div").style(
                                    "background: rgba(0,0,0,0.7); padding: 4px; text-align: center;"
                                ):
                                    ui.label(char["name"]).style(
                                        f"font-size: 9px; font-weight: 700; color: {color if owned else '#4b5563'};"
                                        "display: block; line-height: 1.2;"
                                    )
                                    if owned:
                                        ui.label(f"C{constellation}").style(
                                            f"font-size: 9px; color: {color}; font-weight: 600;"
                                        )
                                    else:
                                        ui.label("???").style("font-size: 9px; color: #374151;")

                _render_collection()

                # Refresh collection after pulls via refresh button
                def refresh_collection() -> None:
                    _render_collection()

                ui.button("Refresh Collection", on_click=refresh_collection).style(
                    "margin-top: 12px; background: rgba(255,255,255,0.06); color: #a78bfa; "
                    "border: 1px solid #4c1d95; border-radius: 6px; padding: 6px 16px; font-size: 13px;"
                )

        # Footer spacer
        ui.element("div").style("height: 40px;")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

startup()
build_ui()

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="Husbando Chronicles",
        favicon="🎴",
        dark=True,
        port=8899,
    )
