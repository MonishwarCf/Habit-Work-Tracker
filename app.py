import sqlite3
import random
from datetime import date, timedelta
from typing import List, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from contextlib import contextmanager
import math

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
templates = Jinja2Templates(directory="templates")

DB_FILE = "database.db"

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

MOCK_DATE_OFFSET = 0

def get_today() -> date:
    return date.today() + timedelta(days=MOCK_DATE_OFFSET)

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS player (
                id INTEGER PRIMARY KEY,
                name TEXT,
                level INTEGER,
                xp INTEGER,
                rank TEXT,
                intel INTEGER,
                agi INTEGER,
                wil INTEGER,
                gold INTEGER,
                streak_count INTEGER,
                streak_multiplier REAL,
                last_completed_date TEXT,
                missed_yesterday INTEGER,
                last_reset_date TEXT DEFAULT ''
            )
        """)
        try:
            conn.execute("ALTER TABLE player ADD COLUMN last_reset_date TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                xp_reward INTEGER,
                gold_reward INTEGER,
                attribute TEXT,
                is_completed INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS red_gates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                reward_multiplier INTEGER,
                penalty_amount INTEGER,
                deadline TEXT,
                status TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                description TEXT,
                status TEXT,
                reward_xp INTEGER,
                reward_gold INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS crystals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                type TEXT,
                effect TEXT,
                is_used INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                cost INTEGER
            )
        """)
        
        cursor = conn.execute("SELECT COUNT(*) FROM player")
        if cursor.fetchone()[0] == 0:
            conn.execute("""
                INSERT INTO player (name, level, xp, rank, intel, agi, wil, gold, streak_count, streak_multiplier, last_completed_date, missed_yesterday)
                VALUES ('Player', 1, 0, 'E-Rank', 10, 10, 10, 0, 0, 1.0, '', 0)
            """)
            conn.execute("INSERT INTO quests (title, xp_reward, gold_reward, attribute, is_completed) VALUES ('1 DSA Problem', 20, 10, 'agi', 0)")
            conn.execute("INSERT INTO quests (title, xp_reward, gold_reward, attribute, is_completed) VALUES ('30 Min ML Study', 30, 15, 'intel', 0)")
            conn.execute("INSERT INTO quests (title, xp_reward, gold_reward, attribute, is_completed) VALUES ('Maintain Streak', 10, 5, 'wil', 0)")
            conn.execute("INSERT INTO shop_items (name, cost) VALUES ('1 Hour Gaming', 50)")
            conn.execute("INSERT INTO shop_items (name, cost) VALUES ('Buy Coffee', 30)")
            
            for i in range(1, 76):
                c_type = "rune" if i % 2 == 0 else "essence"
                effect = random.choice(["streak_shield", "double_xp_24h", "none"]) if c_type == "rune" else "none"
                c_name = f"Crystal of {'Power' if c_type == 'rune' else 'Aesthetics'} {i}"
                conn.execute("INSERT INTO crystals (name, type, effect, is_used) VALUES (?, ?, ?, 1)", (c_name, c_type, effect))
        conn.commit()

init_db()

def calculate_xp_required(level: int) -> int:
    # Linear scale: Starts at 100 XP, grows by 60 XP per level.
    # Total cumulative XP to reach level 100 is ~300,960 XP.
    # At ~750 XP/day average, this takes ~400 days (~1.1 years).
    return 100 + 60 * (level - 1)

def get_rank(level: int) -> str:
    if level < 10: return "E-Rank"
    if level < 25: return "D-Rank"
    if level < 45: return "C-Rank"
    if level < 70: return "B-Rank"
    if level < 90: return "A-Rank"
    return "S-Rank"

def check_daily_reset():
    with get_db() as conn:
        player = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()
        today_str = get_today().isoformat()
        yesterday_str = (get_today() - timedelta(days=1)).isoformat()

        if 'last_reset_date' not in player.keys():
            conn.execute("ALTER TABLE player ADD COLUMN last_reset_date TEXT DEFAULT ''")
            conn.commit()
            player = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()

        if player['last_reset_date'] == today_str:
            expired_gates = conn.execute("SELECT id, penalty_amount FROM red_gates WHERE status = 'active' AND deadline < ?", (today_str,)).fetchall()
            for gate in expired_gates:
                conn.execute("UPDATE red_gates SET status = 'failed' WHERE id = ?", (gate['id'],))
                current_xp = player['xp']
                new_xp = max(0, current_xp - gate['penalty_amount'])
                conn.execute("UPDATE player SET xp = ? WHERE id = 1", (new_xp,))
            conn.commit()
            return

        if player['last_completed_date'] == today_str:
            conn.execute("UPDATE player SET last_reset_date = ? WHERE id = 1", (today_str,))
            conn.commit()
            return

        completed_before = bool(player['last_completed_date'])
        if player['last_completed_date'] == yesterday_str:
            conn.execute("UPDATE player SET missed_yesterday = 0 WHERE id = 1")
        elif completed_before:
            if player['missed_yesterday'] == 1:
                shield = conn.execute("SELECT id FROM crystals WHERE type = 'rune' AND effect = 'streak_shield' AND is_used = 0 LIMIT 1").fetchone()
                if shield:
                    conn.execute("UPDATE crystals SET is_used = 1 WHERE id = ?", (shield['id'],))
                    conn.execute("UPDATE player SET missed_yesterday = 0 WHERE id = 1")
                else:
                    conn.execute("UPDATE player SET streak_count = 0, streak_multiplier = 1.0, missed_yesterday = 0 WHERE id = 1")
            else:
                conn.execute("UPDATE player SET missed_yesterday = 1 WHERE id = 1")
        else:
            conn.execute("UPDATE player SET missed_yesterday = 0 WHERE id = 1")

        conn.execute("UPDATE quests SET is_completed = 0")
        conn.execute("UPDATE player SET last_reset_date = ? WHERE id = 1", (today_str,))

        expired_gates = conn.execute("SELECT id, penalty_amount FROM red_gates WHERE status = 'active' AND deadline < ?", (today_str,)).fetchall()
        for gate in expired_gates:
            conn.execute("UPDATE red_gates SET status = 'failed' WHERE id = ?", (gate['id'],))
            current_xp = player['xp']
            new_xp = max(0, current_xp - gate['penalty_amount'])
            conn.execute("UPDATE player SET xp = ? WHERE id = 1", (new_xp,))
        conn.commit()

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    check_daily_reset()
    return templates.TemplateResponse(request, "index.html", {"request": request})

@app.get("/avatar.jpg")
def get_avatar():
    return FileResponse("avatar.jpg")

class PlayerUpdate(BaseModel):
    name: str

@app.get("/api/player")
def get_player():
    check_daily_reset()
    with get_db() as conn:
        player = dict(conn.execute("SELECT * FROM player WHERE id = 1").fetchone())
        player['xp_required'] = calculate_xp_required(player['level'])
        player['system_date'] = get_today().isoformat()
        return player

@app.put("/api/player")
def update_player(data: PlayerUpdate):
    with get_db() as conn:
        conn.execute("UPDATE player SET name = ? WHERE id = 1", (data.name,))
        conn.commit()
    return {"status": "success"}

class QuestCreate(BaseModel):
    title: str
    xp_reward: int
    gold_reward: int
    attribute: str

@app.get("/api/quests")
def list_quests():
    check_daily_reset()
    with get_db() as conn:
        return [dict(q) for q in conn.execute("SELECT * FROM quests").fetchall()]

@app.post("/api/quests")
def create_quest(data: QuestCreate):
    with get_db() as conn:
        conn.execute("INSERT INTO quests (title, xp_reward, gold_reward, attribute, is_completed) VALUES (?, ?, ?, ?, 0)",
                     (data.title, data.xp_reward, data.gold_reward, data.attribute))
        conn.commit()
    return {"status": "success"}

@app.delete("/api/quests/{quest_id}")
def delete_quest(quest_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM quests WHERE id = ?", (quest_id,))
        conn.commit()
    return {"status": "success"}

@app.post("/api/quests/{quest_id}/complete")
def complete_quest(quest_id: int):
    with get_db() as conn:
        quest = conn.execute("SELECT * FROM quests WHERE id = ? AND is_completed = 0", (quest_id,)).fetchone()
        if not quest:
            raise HTTPException(status_code=400)
            
        conn.execute("UPDATE quests SET is_completed = 1 WHERE id = ?", (quest_id,))
        player = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()
        
        gained_xp = math.floor(quest['xp_reward'] * player['streak_multiplier'])
        new_xp = player['xp'] + gained_xp
        new_level = player['level']
        
        while new_xp >= calculate_xp_required(new_level):
            new_xp -= calculate_xp_required(new_level)
            new_level += 1
            
        new_rank = get_rank(new_level)
        new_gold = player['gold'] + quest['gold_reward']
        
        attr_updates = {"intel": player['intel'], "agi": player['agi'], "wil": player['wil']}
        if quest['attribute'] in attr_updates:
            attr_updates[quest['attribute']] += 1
            
        conn.execute("""
            UPDATE player SET level = ?, xp = ?, rank = ?, gold = ?, intel = ?, agi = ?, wil = ?
            WHERE id = 1
        """, (new_level, new_xp, new_rank, new_gold, attr_updates['intel'], attr_updates['agi'], attr_updates['wil']))
        
        all_completed = conn.execute("SELECT COUNT(*) FROM quests WHERE is_completed = 0").fetchone()[0] == 0
        if all_completed and player['last_completed_date'] != get_today().isoformat():
            new_streak = player['streak_count'] + 1
            new_mult = min(3.0, 1.0 + (new_streak * 0.01))
            conn.execute("UPDATE player SET streak_count = ?, streak_multiplier = ?, last_completed_date = ?, missed_yesterday = 0 WHERE id = 1",
                         (new_streak, new_mult, get_today().isoformat()))
                         
        crystal_drop = None
        if random.random() < 0.20:
            unowned = conn.execute("SELECT id, name, type, effect FROM crystals WHERE is_used = 1 LIMIT 1").fetchone()
            if unowned:
                conn.execute("UPDATE crystals SET is_used = 0 WHERE id = ?", (unowned['id'],))
                crystal_drop = dict(unowned)
                
        conn.commit()
        return {"status": "success", "level_up": new_level > player['level'], "rank_up": new_rank != player['rank'], "crystal": crystal_drop}

@app.get("/api/inventory")
def get_inventory():
    with get_db() as conn:
        return [dict(c) for c in conn.execute("SELECT * FROM crystals WHERE is_used = 0").fetchall()]

@app.get("/api/shop")
def list_shop():
    with get_db() as conn:
        return [dict(i) for i in conn.execute("SELECT * FROM shop_items").fetchall()]

class ShopItemCreate(BaseModel):
    name: str
    cost: int

@app.post("/api/shop")
def create_shop_item(data: ShopItemCreate):
    with get_db() as conn:
        conn.execute("INSERT INTO shop_items (name, cost) VALUES (?, ?)", (data.name, data.cost))
        conn.commit()
    return {"status": "success"}

@app.delete("/api/shop/{item_id}")
def delete_shop_item(item_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM shop_items WHERE id = ?", (item_id,))
        conn.commit()
    return {"status": "success"}

@app.post("/api/shop/{item_id}/buy")
def buy_item(item_id: int):
    with get_db() as conn:
        item = conn.execute("SELECT cost FROM shop_items WHERE id = ?", (item_id,)).fetchone()
        player = conn.execute("SELECT gold FROM player WHERE id = 1").fetchone()
        if not item or player['gold'] < item['cost']:
            raise HTTPException(status_code=400)
        conn.execute("UPDATE player SET gold = gold - ? WHERE id = 1", (item['cost'],))
        conn.commit()
    return {"status": "success"}

class RedGateCreate(BaseModel):
    title: str
    reward_multiplier: int
    penalty_amount: int
    deadline: str

@app.get("/api/red_gates")
def list_red_gates():
    with get_db() as conn:
        return [dict(g) for g in conn.execute("SELECT * FROM red_gates WHERE status = 'active'").fetchall()]

@app.post("/api/red_gates")
def create_red_gate(data: RedGateCreate):
    with get_db() as conn:
        conn.execute("INSERT INTO red_gates (title, reward_multiplier, penalty_amount, deadline, status) VALUES (?, ?, ?, ?, 'active')",
                     (data.title, data.reward_multiplier, data.penalty_amount, data.deadline))
        conn.commit()
    return {"status": "success"}

@app.post("/api/red_gates/{gate_id}/complete")
def complete_red_gate(gate_id: int):
    with get_db() as conn:
        gate = conn.execute("SELECT * FROM red_gates WHERE id = ? AND status = 'active'", (gate_id,)).fetchone()
        if not gate: raise HTTPException(status_code=400)
        
        player = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()
        gained_xp = 100 * gate['reward_multiplier']
        new_xp = player['xp'] + gained_xp
        new_level = player['level']
        while new_xp >= calculate_xp_required(new_level):
            new_xp -= calculate_xp_required(new_level)
            new_level += 1
        new_rank = get_rank(new_level)
        new_gold = player['gold'] + (50 * gate['reward_multiplier'])
        
        conn.execute("UPDATE player SET level = ?, xp = ?, rank = ?, gold = ? WHERE id = 1",
                     (new_level, new_xp, new_rank, new_gold))
        conn.execute("UPDATE red_gates SET status = 'completed' WHERE id = ?", (gate_id,))
        
        crystal_drop = None
        unowned = conn.execute("SELECT id, name, type, effect FROM crystals WHERE is_used = 1 LIMIT 1").fetchone()
        if unowned:
            conn.execute("UPDATE crystals SET is_used = 0 WHERE id = ?", (unowned['id'],))
            crystal_drop = dict(unowned)
            
        conn.commit()
        return {"status": "success", "level_up": new_level > player['level'], "rank_up": new_rank != player['rank'], "crystal": crystal_drop}

class ProjectCreate(BaseModel):
    title: str
    description: str
    reward_xp: int
    reward_gold: int

@app.get("/api/projects")
def list_projects():
    with get_db() as conn:
        return [dict(p) for p in conn.execute("SELECT * FROM projects WHERE status = 'active'").fetchall()]

@app.post("/api/projects")
def create_project(data: ProjectCreate):
    with get_db() as conn:
        conn.execute("INSERT INTO projects (title, description, status, reward_xp, reward_gold) VALUES (?, ?, 'active', ?, ?)",
                     (data.title, data.description, data.reward_xp, data.reward_gold))
        conn.commit()
    return {"status": "success"}

@app.post("/api/projects/{proj_id}/complete")
def complete_project(proj_id: int):
    with get_db() as conn:
        proj = conn.execute("SELECT * FROM projects WHERE id = ? AND status = 'active'", (proj_id,)).fetchone()
        if not proj: raise HTTPException(status_code=400)
        
        player = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()
        new_xp = player['xp'] + proj['reward_xp']
        new_level = player['level']
        while new_xp >= calculate_xp_required(new_level):
            new_xp -= calculate_xp_required(new_level)
            new_level += 1
        new_rank = get_rank(new_level)
        new_gold = player['gold'] + proj['reward_gold']
        
        conn.execute("UPDATE player SET level = ?, xp = ?, rank = ?, gold = ? WHERE id = 1",
                     (new_level, new_xp, new_rank, new_gold))
        conn.execute("UPDATE projects SET status = 'completed' WHERE id = ?", (proj_id,))
        crystal_drop = None
        unowned = conn.execute("SELECT id, name, type, effect FROM crystals WHERE is_used = 1 LIMIT 1").fetchone()
        if unowned:
            conn.execute("UPDATE crystals SET is_used = 0 WHERE id = ?", (unowned['id'],))
            crystal_drop = dict(unowned)
        conn.commit()
        return {"status": "success", "level_up": new_level > player['level'], "rank_up": new_rank != player['rank'], "crystal": crystal_drop}

class AdminCommand(BaseModel):
    command: str

@app.post("/admin/exec")
def admin_exec(data: AdminCommand):
    global MOCK_DATE_OFFSET
    parts = data.command.strip().split(" ")
    if not parts: raise HTTPException(status_code=400, detail="Empty command")
    cmd = parts[0]
    args = parts[1:]
    result = {"status": "success", "output": ""}

    with get_db() as conn:
        player = conn.execute("SELECT * FROM player WHERE id = 1").fetchone()

        if cmd == "/set_level":
            if not args: return {"status": "error", "output": "Usage: /set_level <N>"}
            lvl = max(1, int(args[0]))
            conn.execute("UPDATE player SET level = ?, xp = 0, rank = ? WHERE id = 1", (lvl, get_rank(lvl)))
            result["output"] = f"Level set to {lvl} ({get_rank(lvl)})"

        elif cmd == "/add_gold":
            if not args: return {"status": "error", "output": "Usage: /add_gold <N>"}
            amt = int(args[0])
            conn.execute("UPDATE player SET gold = gold + ? WHERE id = 1", (amt,))
            result["output"] = f"Gold += {amt} (total: {player['gold'] + amt})"

        elif cmd == "/set_gold":
            if not args: return {"status": "error", "output": "Usage: /set_gold <N>"}
            amt = int(args[0])
            conn.execute("UPDATE player SET gold = ? WHERE id = 1", (amt,))
            result["output"] = f"Gold set to {amt}"

        elif cmd == "/add_xp":
            if not args: return {"status": "error", "output": "Usage: /add_xp <N>"}
            xp_gain = int(args[0])
            new_xp = player['xp'] + xp_gain
            new_level = player['level']
            while new_xp >= calculate_xp_required(new_level):
                new_xp -= calculate_xp_required(new_level)
                new_level += 1
            conn.execute("UPDATE player SET xp = ?, level = ?, rank = ? WHERE id = 1", (new_xp, new_level, get_rank(new_level)))
            result["output"] = f"XP += {xp_gain} | Level: {new_level} | Rank: {get_rank(new_level)}"

        elif cmd == "/set_streak":
            if not args: return {"status": "error", "output": "Usage: /set_streak <N>"}
            s = max(0, int(args[0]))
            mult = min(3.0, 1.0 + s * 0.01)
            conn.execute("UPDATE player SET streak_count = ?, streak_multiplier = ? WHERE id = 1", (s, mult))
            result["output"] = f"Streak set to {s} days | Multiplier: {mult:.2f}x"

        elif cmd == "/reset_streak":
            conn.execute("UPDATE player SET streak_count = 0, streak_multiplier = 1.0, missed_yesterday = 0 WHERE id = 1")
            result["output"] = "Streak reset to 0"

        elif cmd == "/set_name":
            if not args: return {"status": "error", "output": "Usage: /set_name <name>"}
            name = " ".join(args)
            conn.execute("UPDATE player SET name = ? WHERE id = 1", (name,))
            result["output"] = f"Player name set to '{name}'"

        elif cmd == "/set_attr":
            if len(args) < 2: return {"status": "error", "output": "Usage: /set_attr <intel|agi|wil> <N>"}
            attr, val = args[0].lower(), int(args[1])
            if attr not in ("intel", "agi", "wil"): return {"status": "error", "output": "Invalid attribute"}
            conn.execute(f"UPDATE player SET {attr} = ? WHERE id = 1", (val,))
            result["output"] = f"{attr.upper()} set to {val}"

        elif cmd == "/complete_all_quests":
            conn.execute("UPDATE quests SET is_completed = 1")
            result["output"] = "All quests marked complete"

        elif cmd == "/reset_quests":
            conn.execute("UPDATE quests SET is_completed = 0")
            result["output"] = "All quests reset to incomplete"

        elif cmd == "/drop_crystal":
            unowned = conn.execute("SELECT id, name, type, effect FROM crystals WHERE is_used = 1 LIMIT 1").fetchone()
            if unowned:
                conn.execute("UPDATE crystals SET is_used = 0 WHERE id = ?", (unowned['id'],))
                result["output"] = f"Dropped: {unowned['name']} [{unowned['type']}] — {unowned['effect']}"
                result["crystal"] = dict(unowned)
            else:
                result["output"] = "No more crystals to drop"

        elif cmd == "/clear_inventory":
            conn.execute("UPDATE crystals SET is_used = 1")
            result["output"] = "Inventory cleared"

        elif cmd == "/wipe_gates":
            conn.execute("UPDATE red_gates SET status = 'failed' WHERE status = 'active'")
            result["output"] = "All active gates wiped"

        elif cmd == "/fail_gates":
            gates = conn.execute("SELECT id, penalty_amount FROM red_gates WHERE status = 'active'").fetchall()
            total_pen = sum(g['penalty_amount'] for g in gates)
            conn.execute("UPDATE red_gates SET status = 'failed' WHERE status = 'active'")
            new_xp = max(0, player['xp'] - total_pen)
            conn.execute("UPDATE player SET xp = ? WHERE id = 1", (new_xp,))
            result["output"] = f"All gates failed. Penalty: -{total_pen} XP applied"

        elif cmd == "/reset_all":
            conn.execute("UPDATE player SET level=1, xp=0, rank='E-Rank', intel=10, agi=10, wil=10, gold=0, streak_count=0, streak_multiplier=1.0, last_completed_date='', missed_yesterday=0 WHERE id=1")
            conn.execute("UPDATE quests SET is_completed = 0")
            conn.execute("UPDATE crystals SET is_used = 1")
            result["output"] = "Full state reset. Starting from E-Rank Level 1."

        elif cmd == "/offset_date":
            if not args: return {"status": "error", "output": "Usage: /offset_date <days>"}
            MOCK_DATE_OFFSET += int(args[0])
            result["output"] = f"Date offset: {MOCK_DATE_OFFSET} days. System Date: {get_today().isoformat()}"

        elif cmd == "/reset_date":
            MOCK_DATE_OFFSET = 0
            result["output"] = f"Date offset reset. System Date: {get_today().isoformat()}"

        elif cmd == "/player_info":
            p = dict(player)
            p['xp_required'] = calculate_xp_required(p['level'])
            result["output"] = (
                f"Name: {p['name']} | Level: {p['level']} | Rank: {p['rank']}\n"
                f"XP: {p['xp']}/{p['xp_required']} | Gold: {p['gold']}\n"
                f"INT: {p['intel']} | AGI: {p['agi']} | WIL: {p['wil']}\n"
                f"Streak: {p['streak_count']} days ({p['streak_multiplier']:.2f}x) | Missed: {p['missed_yesterday']}"
            )

        elif cmd == "/list_quests":
            quests = conn.execute("SELECT id, title, is_completed FROM quests").fetchall()
            lines = [f"[{'✓' if q['is_completed'] else ' '}] #{q['id']} {q['title']}" for q in quests]
            result["output"] = "\n".join(lines) if lines else "No quests"

        elif cmd == "/db_stats":
            qcount = conn.execute("SELECT COUNT(*) FROM quests").fetchone()[0]
            gcount = conn.execute("SELECT COUNT(*) FROM red_gates WHERE status='active'").fetchone()[0]
            pcount = conn.execute("SELECT COUNT(*) FROM projects WHERE status='active'").fetchone()[0]
            ccount = conn.execute("SELECT COUNT(*) FROM crystals WHERE is_used=0").fetchone()[0]
            result["output"] = f"DB Stats | Quests: {qcount} | Gates: {gcount} | Projects: {pcount} | Crystals: {ccount}"

        elif cmd == "/help":
            result["output"] = (
                "Available commands:\n"
                "/player_info              — Full player snapshot\n"
                "/set_level <N>            — Override level\n"
                "/add_xp <N>               — Add XP (triggers level-ups)\n"
                "/add_gold <N>             — Add gold\n"
                "/set_gold <N>             — Set gold exactly\n"
                "/set_streak <N>           — Set streak day count\n"
                "/reset_streak             — Reset streak to 0\n"
                "/set_name <name>          — Rename player\n"
                "/set_attr <attr> <N>      — Set intel/agi/wil\n"
                "/complete_all_quests      — Mark all quests done\n"
                "/reset_quests             — Reset all quests\n"
                "/drop_crystal             — Force a crystal drop\n"
                "/clear_inventory          — Wipe all crystals\n"
                "/wipe_gates               — Remove all active gates\n"
                "/fail_gates               — Fail all gates + apply penalties\n"
                "/offset_date <days>       — Shift system mock date\n"
                "/reset_date               — Reset system mock date to 0\n"
                "/list_quests              — List all quests with status\n"
                "/db_stats                 — Database row counts\n"
                "/reset_all                — FULL RESET to E-Rank Lv1"
            )
        else:
            result["status"] = "error"
            result["output"] = f"Unknown command: {cmd}. Type /help for a list."

        conn.commit()
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=10000)

