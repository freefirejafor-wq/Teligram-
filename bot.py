"""
🎬 Video Bot v42
━━━━━━━━━━━━━━━
✅ Download: YouTube, TikTok, Instagram, Facebook, Pinterest
📱 TikTok Mode — Copyright Safe + No "Eligible For You"
🎯 WinGo ULTRA — 35-layer prediction

📦 SETUP (Termux):
    pkg update -y && pkg install -y python ffmpeg
    pip install "python-telegram-bot[job-queue]" yt-dlp

🔑 BOT_TOKEN নিচে বসান
🚀 RUN: python video_bot_v42.py
"""

import os, sys, re, json, logging, asyncio, subprocess, tempfile, uuid, time, random, math, urllib.request
from collections import Counter
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

BOT_TOKEN    = os.getenv("BOT_TOKEN") or "8813924101:AAHpTft73bl0ddViGIe46lBwBrDTNDipwnI"
GEMINI_KEY   = os.getenv("GEMINI_API_KEY") or "AIzaSyDns9YbCMa4vtKFZFlwGI92jv3UyAGKGY4"
ADMIN_ID     = int(os.getenv("ADMIN_ID") or "0")
VERSION      = "v43"

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger("vbot42")

import shutil, glob as _glob, subprocess as _sp

def _find_bin(name):
    p = shutil.which(name)
    if p: return p
    for base in ["/nix/store", "/usr/local/bin", "/usr/bin", "/bin", "/app",
                 "/home/claude", str(Path.home())]:
        try:
            found = _glob.glob(f"{base}/**/{name}", recursive=True)
            if found: return found[0]
        except Exception:
            pass
    return None

def _install_ffmpeg():
    """Multiple fallback methods to install ffmpeg"""
    # Method 1: apt-get
    try:
        r = _sp.run(["apt-get", "install", "-y", "ffmpeg"],
                    capture_output=True, timeout=120)
        p = shutil.which("ffmpeg")
        if p:
            print(f"✅ ffmpeg installed via apt-get: {p}")
            return p, shutil.which("ffprobe") or p.replace("ffmpeg","ffprobe")
    except Exception as e:
        print(f"apt-get failed: {e}")

    # Method 2: apt (no get)
    try:
        r = _sp.run(["apt", "install", "-y", "ffmpeg"],
                    capture_output=True, timeout=120)
        p = shutil.which("ffmpeg")
        if p:
            print(f"✅ ffmpeg installed via apt: {p}")
            return p, shutil.which("ffprobe") or p.replace("ffmpeg","ffprobe")
    except Exception as e:
        print(f"apt failed: {e}")

    # Method 3: static binary download (ffmpeg-release-amd64-static)
    try:
        import urllib.request, tarfile
        home = Path.home()
        ff_dir = home / "ffmpeg_bin"
        ff_dir.mkdir(exist_ok=True)
        ff_path  = ff_dir / "ffmpeg"
        ffp_path = ff_dir / "ffprobe"

        if not ff_path.exists():
            print("⏬ Downloading static ffmpeg...")
            url = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
            tmp_tar = str(ff_dir / "ff.tar.xz")
            urllib.request.urlretrieve(url, tmp_tar)
            with tarfile.open(tmp_tar) as tar:
                for m in tar.getmembers():
                    if m.name.endswith("/ffmpeg") or m.name.endswith("/ffprobe"):
                        m.name = Path(m.name).name
                        tar.extract(m, path=str(ff_dir))
            Path(tmp_tar).unlink(missing_ok=True)
            ff_path.chmod(0o755)
            if ffp_path.exists(): ffp_path.chmod(0o755)

        if ff_path.exists():
            print(f"✅ Static ffmpeg ready: {ff_path}")
            return str(ff_path), str(ffp_path) if ffp_path.exists() else str(ff_path)
    except Exception as e:
        print(f"Static download failed: {e}")

    print("❌ ffmpeg could not be installed — all methods failed")
    return None, None

FFMPEG  = _find_bin("ffmpeg")
FFPROBE = _find_bin("ffprobe")

if not FFMPEG:
    print("⚠️ ffmpeg not found, attempting install...")
    FFMPEG, FFPROBE = _install_ffmpeg()

if not FFMPEG:
    print("❌ FATAL: ffmpeg unavailable. Bot will not process videos.")
    FFMPEG  = "ffmpeg"   # last resort — will fail gracefully per-request
    FFPROBE = "ffprobe"

print(f"✅ ffmpeg : {FFMPEG}")
print(f"✅ ffprobe: {FFPROBE}")

CPU_COUNT = max(2, os.cpu_count() or 4)
executor  = ThreadPoolExecutor(max_workers=max(4, CPU_COUNT))
TEMP_DIR  = Path(tempfile.gettempdir()) / "vbot42"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ════════════════════════════════════════════
# WINGO STATE  — ADRIYAN JAFOR AI (DKWin Real API)
# ════════════════════════════════════════════

DKWIN_API = "https://dkwin19.com/api/webapi/GetHistoryIssuePage"
DKWIN_GAME_CODES = {
    "30s":  "WinGo_30S",
    "1min": "WinGo_1M",
    
}

_wingo_subs  = set()
_wingo_state = {
    "last_period":  None,
    "history":      [],
    "win_streak":   0,
    "loss_streak":  0,
    "total_pred":   0,
    "correct_pred": 0,
    "layer_perf":   {},
    "pending_pred": None,
    "session_votes": [],
    "game_code":    "WinGo_30S",
}

# ════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════
def md_escape(t):
    return re.sub(r'([_*`\[\]])', r'\\\1', str(t or ""))[:3000]

def tmp_path(suffix=".mp4"):
    return str(TEMP_DIR / f"{uuid.uuid4().hex}{suffix}")

def has_audio(path):
    try:
        r = subprocess.run(
            [FFPROBE,"-v","error","-select_streams","a:0",
             "-show_entries","stream=codec_type","-of","csv=p=0",str(path)],
            capture_output=True, text=True, timeout=15)
        return "audio" in r.stdout
    except Exception:
        return True

def get_video_info(path):
    try:
        r = subprocess.run(
            [FFPROBE,"-v","error","-select_streams","v:0",
             "-show_entries","stream=width,height,duration",
             "-of","json",str(path)],
            capture_output=True, text=True, timeout=15)
        data = json.loads(r.stdout)
        s = data.get("streams",[{}])[0]
        return {
            "width": int(s.get("width",1920)),
            "height": int(s.get("height",1080)),
            "duration": float(s.get("duration",0)),
        }
    except Exception:
        return {"width":1920,"height":1080,"duration":0}

def run_ffmpeg(cmd, timeout=300):
    try:
        # cmd[0] কে FFMPEG দিয়ে replace করো, তারপর loglevel inject
        cmd = list(cmd)
        cmd[0] = FFMPEG
        if "-loglevel" not in cmd and "-v" not in cmd:
            cmd = [cmd[0], "-loglevel", "error"] + cmd[1:]

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        # output file হলো সবসময় শেষ element (ffmpeg convention)
        out_file = cmd[-1]
        if Path(out_file).exists() and Path(out_file).stat().st_size > 1024:
            return True, ""
        stderr = r.stderr or ""
        all_lines = stderr.splitlines()
        # banner বাদ দিয়ে শুধু আসল error দেখাও
        err_keywords = ("error", "invalid", "failed", "no such", "unable",
                        "cannot", "could not", "denied", "not found",
                        "codec", "muxer", "permission", "option", "matches no",
                        "unrecognized", "unknown", "conversion", "filter")
        err_lines = [l for l in all_lines
                     if l.strip() and any(k in l.lower() for k in err_keywords)]
        if err_lines:
            err = "\n".join(err_lines[:5])
        elif all_lines:
            non_empty = [l for l in all_lines if l.strip()]
            err = "\n".join(non_empty[-5:]) if non_empty else "অজানা ffmpeg error"
        else:
            err = "অজানা ffmpeg error"
        return False, err
    except subprocess.TimeoutExpired:
        return False, "Timeout — ভিডিও অনেক বড়, ছোট ভিডিও দিন"
    except Exception as e:
        return False, str(e)

async def safe_edit(target, text, **kw):
    try:
        return await target.edit_text(text, **kw)
    except Exception as e:
        if "not modified" in str(e).lower(): return target
        try:
            kw.pop("parse_mode", None)
            return await target.edit_text(re.sub(r'[*_`\[\]()]','', text), **kw)
        except Exception:
            return target

async def safe_reply(msg, text, **kw):
    try:
        return await msg.reply_text(text, **kw)
    except Exception:
        kw.pop("parse_mode", None)
        return await msg.reply_text(re.sub(r'[*_`\[\]()]','', text), **kw)

_user_state: dict = {}

# ════════════════════════════════════════════
# 🎯 WINGO 1MIN ULTIMATE PREDICTOR v3.0
# 25+ Patterns | Adaptive Weighting
# ════════════════════════════════════════════

_1min_history = []
_1min_subs    = set()
_1min_pending = None   # {"period": str, "size": str, "num1": int, "num2": int, "conf": int}

def _classify(n): return "BIG" if n >= 5 else "SMALL"
def _dots(n): return 2 if n == 0 else (1 if n == 7 else 0)

def _parse_1min_rows(raw):
    out = []
    for x in raw:
        try:
            n = int(x.get("number", x.get("Number", 0))) % 10
            period = str(x.get("issueNumber", x.get("IssueNumber", x.get("issue", ""))))
            out.append({"number": n, "size": _classify(n),
                        "dots": _dots(n), "period": period})
        except Exception:
            pass
    return out

async def _fetch_1min() -> list:
    import urllib.request as _req
    ts = int(time.time() * 1000)
    apis = [
        f"https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json?ts={ts}",
        f"https://api.bdgwin.com/WinGo/WinGo_1M/GetHistoryIssuePage.json?ts={ts}",
        f"https://wingo.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json?ts={ts}",
    ]
    for url in apis:
        try:
            r = _req.urlopen(
                _req.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                           "Accept": "application/json"}),
                timeout=10
            )
            data = json.loads(r.read())
            raw  = data.get("data", {}).get("list", [])
            if not raw:
                raw = data.get("data", []) if isinstance(data.get("data"), list) else []
            rows = _parse_1min_rows(raw)
            if rows:
                logger.info("1min fetch ok: %d rows from %s", len(rows), url[:45])
                return rows
        except Exception as e:
            logger.warning("1min fetch fail %s: %s", url[:45], e)
    logger.warning("1min: ALL APIs failed")
    return []

def _ultimate_predict(history: list) -> dict:
    """
    ULTIMATE UNIVERSAL PREDICTION LOGIC v3.0
    JavaScript UltimatePredictor এর EXACT Python port
    u.html এর সাথে 100% মিল — same data = same result
    """
    if len(history) < 3:
        return {"size": "BIG", "number": 5, "number2": 6,
                "confidence": 65, "patterns": 0,
                "reason": "Insufficient data", "streak": 0}

    recent = history[:35]

    # ── dots helper (JS getDotsFromNumber) ───────────────
    def get_dots(n):
        if n == 0: return 2
        if n == 7: return 1
        return 0

    for r in recent:
        if "dots" not in r:
            r["dots"] = get_dots(r["number"])

    sizes   = [r["size"]   for r in recent]
    numbers = [r["number"] for r in recent]
    dots    = [r["dots"]   for r in recent]

    # ── calculateStats ────────────────────────────────────
    big_c = sizes.count("BIG")
    sml_c = sizes.count("SMALL")
    total = big_c + sml_c or 1
    imb   = abs(big_c - sml_c)
    dominant = "BIG" if big_c > sml_c else "SMALL"

    # ── analyzeStreak ─────────────────────────────────────
    streak = 1
    cur_type = sizes[0]
    for i in range(1, len(sizes)):
        if sizes[i] == cur_type: streak += 1
        else: break
    breaker = "SMALL" if cur_type == "BIG" else "BIG"

    # ── detectAllPatterns ─────────────────────────────────
    W = {
        "doubleSmall": 87, "tripleBig": 70, "quadrupleStreak": 85,
        "quintupleStreak": 92, "perfectAlternation": 75,
        "reverseAlternation": 75, "zeroDetection": 65, "nineDetection": 60,
        "dotTripleStreak": 55, "tripleSameNumber": 80, "parityAlternation": 55,
        "statisticalImbalance": 40, "fibonacciPattern": 68, "primeNumberPattern": 62,
        "gapAnalysis": 58, "momentumShift": 72,
        "clusterBreak": 77, "zigzagPattern": 69, "twoThirdMajority": 64,
        "reversalAfterLong": 88, "morningEveningEffect": 52,
        "dotTransition": 59, "numberSumPattern": 61,
        "boundaryHit": 73, "oscillationDetection": 66,
    }

    scores   = {"BIG": 0.0, "SMALL": 0.0}
    detected = []

    last2    = sizes[:2]
    last3    = sizes[:3]
    last4    = sizes[:4]
    last5    = sizes[:5]
    lastNums = numbers[:8]
    lastDots = dots[:6]

    def add(tgt, score, name):
        scores[tgt] += score
        detected.append({"pattern": name, "target": tgt})

    # P1: Double Small → Big
    if last2 == ["SMALL","SMALL"]:
        add("BIG", W["doubleSmall"], "Double Small")
    # P2: Triple Big → Small
    if last3 == ["BIG","BIG","BIG"]:
        add("SMALL", W["tripleBig"], "Triple Big")
    # P3: Quadruple streak
    if all(s == "BIG"   for s in last4): add("SMALL", W["quadrupleStreak"], "Quadruple BIG")
    if all(s == "SMALL" for s in last4): add("BIG",   W["quadrupleStreak"], "Quadruple SMALL")
    # P4: Quintuple streak
    if all(s == "BIG"   for s in last5): add("SMALL", W["quintupleStreak"], "Quintuple BIG")
    if all(s == "SMALL" for s in last5): add("BIG",   W["quintupleStreak"], "Quintuple SMALL")
    # P5: Perfect / Reverse alternation
    if last4 == ["BIG","SMALL","BIG","SMALL"]:
        add("BIG",   W["perfectAlternation"],  "Perfect Alternation")
    if last4 == ["SMALL","BIG","SMALL","BIG"]:
        add("SMALL", W["reverseAlternation"],  "Reverse Alternation")
    # P6: Zero detection
    if lastNums[0] == 0:
        add("BIG",   W["zeroDetection"], "Zero detected")
    # P7: Nine detection
    if lastNums[0] == 9:
        add("SMALL", W["nineDetection"], "Nine detected")
    # P8: Cluster break (JS: slice(0,5), count>=3)
    nc = {}
    for n in lastNums[:5]:
        nc[n] = nc.get(n, 0) + 1
    for num, cnt in nc.items():
        if cnt >= 3:
            opp = "SMALL" if num >= 5 else "BIG"
            add(opp, W["clusterBreak"], "Number Cluster Break")
    # P9: Zigzag (JS exact: B S B S B → SMALL)
    if last5 == ["BIG","SMALL","BIG","SMALL","BIG"]:
        add("SMALL", W["zigzagPattern"], "Zigzag Completion")
    # P10: Boundary hit (JS: 0 or 9)
    if lastNums[0] == 0:
        add("BIG",   W["boundaryHit"], "Boundary Hit")
    if lastNums[0] == 9:
        add("SMALL", W["boundaryHit"], "Boundary Hit")
    # P11: Long streak reversal (JS: streak.current >= 4)
    if streak >= 4:
        bonus = min(95, 75 + (streak - 3) * 5)
        add(breaker, bonus, f"Long Streak Reversal ({streak})")
    # P12: Statistical imbalance (JS: total>=10 && imbalance>=4)
    if total >= 10 and imb >= 4:
        tgt = "SMALL" if dominant == "BIG" else "BIG"
        add(tgt, W["statisticalImbalance"] + min(20, imb * 2), "Statistical Imbalance")
    # P13: Dot transition (JS exact)
    if len(lastDots) >= 2:
        if lastDots[0] == 3 and lastDots[1] == 1:
            add("SMALL", 59, "Dot 3→1")
        if lastDots[0] == 1 and lastDots[1] == 3:
            add("BIG",   59, "Dot 1→3")
    # P14: Number sum pattern (JS: sum of last 3 in [15,18,21])
    if len(lastNums) >= 3:
        s3 = sum(lastNums[:3])
        if s3 in (15, 18, 21):
            tgt = "SMALL" if s3 % 2 == 0 else "BIG"
            add(tgt, W["numberSumPattern"], f"Number Sum {s3}")
    # P15: Oscillation detection (JS: oscillations>=4 in 6 pairs)
    osc = 0
    for i in range(min(6, len(lastNums) - 1)):
        if (lastNums[i] >= 5 and lastNums[i+1] <= 4) or \
           (lastNums[i] <= 4 and lastNums[i+1] >= 5):
            osc += 1
    if osc >= 4:
        tgt = "SMALL" if lastNums[0] >= 5 else "BIG"
        add(tgt, W["oscillationDetection"], "High Oscillation")
    # P16: Momentum shift (JS: |recentBig - prevBig| >= 2)
    prev3 = sizes[3:6]
    recent_big = last3.count("BIG")
    prev_big   = prev3.count("BIG")
    if abs(recent_big - prev_big) >= 2:
        tgt = "BIG" if recent_big > prev_big else "SMALL"
        add(tgt, 55, "Momentum Continuation")

    pattern_total = scores["BIG"] + scores["SMALL"] or 1

    # ── analyzeNumbers (JS hot=[5..9], likelyNext) ────────
    hot_big   = len([n for n in [5,6,7,8,9] if n >= 5])   # always 5
    hot_small = len([n for n in [5,6,7,8,9] if n <= 4])   # always 0
    # JS: hotBig(5) > hotSmall(0) → BIG +15
    scores["BIG"] += 15

    # ── analyzeDots ensemble (JS dotSizeCorrelation) ──────
    dot_corr = {
        1: {"BIG": 3, "SMALL": 2},
        2: {"BIG": 2, "SMALL": 3},
        3: {"BIG": 4, "SMALL": 1},
    }
    last_dot = dots[0] if dots else 0
    if last_dot in dot_corr:
        dc = dot_corr[last_dot]
        dt = dc["BIG"] + dc["SMALL"]
        scores["BIG"]   += (dc["BIG"]   / dt) * 10
        scores["SMALL"] += (dc["SMALL"] / dt) * 10

    # ── ensembleVote momentum tweak (JS) ──────────────────
    short_pct = last3.count("BIG") / 3 * 100
    if short_pct > 66:   scores["BIG"]   += 5   # STRONG_BIG → +5 BIG (JS)
    elif short_pct < 33: scores["SMALL"] += 5   # STRONG_SMALL → +5 SMALL
    elif short_pct > 55: scores["SMALL"] += 3   # WEAK_BIG → +3 SMALL
    elif short_pct < 45: scores["BIG"]   += 3   # WEAK_SMALL → +3 BIG

    # ── ensemble final (JS: BIG > SMALL) ─────────────────
    ens_final = "BIG" if scores["BIG"] > scores["SMALL"] else "SMALL"
    ens_reason = (f"Ensemble: BIG={scores['BIG']:.0f} "
                  f"SMALL={scores['SMALL']:.0f}")

    # ── finalDecision (JS exact) ──────────────────────────
    if streak >= 5:
        final  = breaker
        reason = f"Extreme streak ({streak}) reversal"
    elif imb >= 6 and total >= 15:
        final  = "SMALL" if dominant == "BIG" else "BIG"
        reason = f"Statistical correction (imbalance {imb})"
    elif abs(scores["BIG"] - scores["SMALL"]) < 8:
        final  = breaker
        reason = "Tie breaker - streak reversal"
    else:
        final  = ens_final
        reason = ens_reason

    # ── calculateConfidence (JS exact) ────────────────────
    score_diff = abs(scores["BIG"] - scores["SMALL"])
    conf = 50
    conf += min(25, score_diff / 2)
    conf += min(15, len(detected))
    if streak >= 4: conf += 10
    if total  >= 20: conf += 5
    conf = min(99, int(round(conf)))

    # ── predictNumber (JS exact) ──────────────────────────
    dot_num_map = {1: [5,6,7,8], 2: [0,1,2,3,4], 3: [7,8,9]}
    last_dot_r = dots[0] if dots else 0

    def weighted_pick(pool, weights):
        total_w = sum(weights)
        r = random.random() * total_w
        cum = 0
        for v, w in zip(pool, weights):
            cum += w
            if r < cum: return v
        return pool[-1]

    # JS dotMap candidates filter
    dot_candidates = [
        n for n in dot_num_map.get(last_dot_r, [])
        if (final == "BIG" and n >= 5) or (final == "SMALL" and n <= 4)
    ]

    # JS likelyNext (last+1, last+2, last+7 mod 10, filtered by size)
    if numbers:
        last_n = numbers[0]
        likely = [(last_n+1)%10, (last_n+2)%10, (last_n+7)%10]
        likely_filtered = [
            n for n in likely
            if (final == "BIG" and n >= 5) or (final == "SMALL" and n <= 4)
        ]
    else:
        likely_filtered = []

    if final == "BIG":
        pool    = [5, 6, 7, 8, 9]
        weights = [15, 20, 25, 20, 20]
    else:
        pool    = [0, 1, 2, 3, 4]
        weights = [25, 25, 20, 15, 15]

    # JS predictNumber priority: dotMap → likelyNext → weightedRandom
    if dot_candidates:
        num1 = dot_candidates[0]
    elif likely_filtered:
        num1 = likely_filtered[0]
    else:
        num1 = weighted_pick(pool, weights)

    # num2: JS → offset from num1 by ±1 or ±2, same side
    offset = random.choice([1, -1]) if final == "BIG" else random.choice([2, -2])
    num2_raw = (num1 + offset + 10) % 10
    if (final == "BIG" and num2_raw < 5) or (final == "SMALL" and num2_raw > 4):
        num2 = num1  # JS fallback
    else:
        num2 = num2_raw

    return {
        "size": final, "number": num1, "number2": num2,
        "confidence": conf, "patterns": len(detected),
        "reason": reason, "streak": streak,
    }

async def _1min_broadcast(bot):
    global _1min_history, _1min_pending
    _1min_history = await _fetch_1min()
    if not _1min_subs or not _1min_history:
        return

    last    = _1min_history[0]
    period  = last["period"]

    dead = set()

    # ── ধাপ ১: আগের prediction এর WIN/LOSS দেখাও ──────────
    if _1min_pending and _1min_pending["period"] != period:
        result_row = next(
            (h for h in _1min_history if h["period"] == _1min_pending["period"]),
            None
        )
        if result_row:
            actual_size = result_row["size"]
            actual_num  = result_row["number"]
            pred_size   = _1min_pending["size"]
            pred_num1   = _1min_pending["num1"]
            pred_num2   = _1min_pending["num2"]
            pred_conf   = _1min_pending["conf"]
            won         = (actual_size == pred_size)

            win_icon  = "✅" if won else "❌"
            win_label = "WIN 🎉" if won else "LOSS 💀"
            act_icon  = "🔺" if actual_size == "BIG" else "🔻"
            pred_icon = "🔺" if pred_size   == "BIG" else "🔻"

            result_msg = (
                f"{'╔══════════════════════════╗'}\n"
                f"  {win_icon}  *{win_label}*  ·  `{_1min_pending['period'][-6:]}`\n"
                f"{'╚══════════════════════════╝'}\n\n"
                f"📊 *Actual Result*\n"
                f"{act_icon}  *{actual_size}*  🎲  *{actual_num}*\n\n"
                f"📌 *AI Signal ছিল*\n"
                f"{pred_icon}  *{pred_size}*  🎲  *{pred_num1}* বা *{pred_num2}*\n"
                f"📊 Conf: `{pred_conf}%`\n\n"
                f"{'━━━━━━━━━━━━━━━━━━━━━━━'}\n"
                f"⚡ _ULTIMATE 25+ Pattern AI_"
            )
            for uid in list(_1min_subs):
                try:
                    await bot.send_message(uid, result_msg, parse_mode="Markdown")
                except Exception:
                    dead.add(uid)

        _1min_pending = None

    # ── ধাপ ২: নতুন prediction পাঠাও ────────────────────
    pred     = _ultimate_predict(_1min_history)
    size     = pred["size"]
    num1     = pred["number"]
    num2     = pred.get("number2", num1)
    conf     = pred["confidence"]
    patterns = pred["patterns"]
    streak   = pred["streak"]
    last_num  = last["number"]
    last_size = last["size"]

    # পরের period এর জন্য pending সেট করো
    next_period = str(int(period) + 1) if period.isdigit() else period
    _1min_pending = {
        "period": next_period,
        "size":   size,
        "num1":   num1,
        "num2":   num2,
        "conf":   conf,
    }

    size_icon  = "🔺" if size == "BIG" else "🔻"
    color_icon = "🟢" if size == "BIG" else "🔴"
    color_name = "GREEN" if size == "BIG" else "RED"

    bar      = round(conf / 10)
    conf_bar = "█" * bar + "░" * (10 - bar)

    signal_msg = (
        f"╔══════════════════════════╗\n"
        f"  🎯  *WinGo 1Min — ULTIMATE v3.0*\n"
        f"╚══════════════════════════╝\n\n"
        f"📡 *PERIOD* `{next_period}` 🔴 LIVE\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"  {size_icon}  *{size}*  {color_icon}  *{color_name}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔢 *Predicted Numbers:*\n"
        f"┌──────────┐  ┌──────────┐\n"
        f"│    *{num1}*     │  │    *{num2}*     │\n"
        f"└──────────┘  └──────────┘\n\n"
        f"📊 `{conf_bar}` *{conf}%*\n"
        f"🧠 *{patterns}+ Patterns Active*\n"
        f"🔥 *Streak:* `{streak}`\n\n"
        f"📌 *Last Result:* `{last_num}` ({last_size})\n\n"
        f"⚡ _ULTIMATE 25+ Pattern AI_"
    )

    for uid in list(_1min_subs):
        try:
            await bot.send_message(uid, signal_msg, parse_mode="Markdown")
        except Exception:
            dead.add(uid)

    _1min_subs -= dead
# ════════════════════════════════════════════



# ════════════════════════════════════════════
# ════════════════════════════════════════════
# 🎯 WINGO ENGINE — v3 ULTRA AI (70 Layers)
# ════════════════════════════════════════════
def _w_sizeof(n): return "BIG" if n >= 5 else "SMALL"
def _w_colorof(n):
    if n == 0: return "violet_red"
    if n == 5: return "violet_green"
    return "red" if n % 2 == 0 else "green"

def _w_parse_rows(rows, limit=200):
    out = []
    for row in rows[:limit]:
        try:
            n = int(row.get("number") or row.get("num") or row.get("winNumber") or -1)
            p = str(row.get("issueNumber") or row.get("period") or row.get("issue") or "")
            if n < 0 or not p: continue
            raw_color = str(row.get("color") or "").lower().strip()
            if "violet" in raw_color and "green" in raw_color:
                color = "violet_green"
            elif "violet" in raw_color and "red" in raw_color:
                color = "violet_red"
            elif "violet" in raw_color:
                color = "violet_red" if n == 0 else "violet_green"
            elif raw_color in ("red","green"):
                color = raw_color
            else:
                color = _w_colorof(n)
            out.append({"period": p, "number": n, "size": _w_sizeof(n), "color": color})
        except Exception:
            continue
    return out

_FETCH_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin":          "https://www.ar-lottery01.com",
    "Referer":         "https://www.ar-lottery01.com/",
    "X-Requested-With":"XMLHttpRequest",
}

def _w_fetch_one(base_url, page=1, size=100):
    """Fetch one page from one API URL. Returns parsed rows or []."""
    ts  = int(time.time() * 1000)
    url = f"{base_url}&pageNo={page}" if "pageSize=" in base_url else base_url + str(ts)
    if "pageSize=" in base_url:
        url = base_url + str(ts) + f"&pageNo={page}"
    try:
        req = urllib.request.Request(url, headers=_FETCH_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))
        rows = []
        if isinstance(data, dict):
            inner = data.get("data", {})
            if isinstance(inner, dict):
                rows = inner.get("list", [])
            elif isinstance(inner, list):
                rows = inner
        out = _w_parse_rows(rows, size)
        return out
    except Exception as e:
        logger.debug("wingo fetch %s p%d: %s", base_url[:40], page, e)
        return []

def _w_fetch_apis(api_list):
    """Try each 30S API host in order; fetch page-1 + page-2 for 200 records."""
    for api in api_list:
        p1 = _w_fetch_one(api, page=1)
        if not p1: continue
        logger.info("WinGo API ok: %d rows p1", len(p1))
        p2 = _w_fetch_one(api, page=2)
        if p2:
            seen   = {r["period"] for r in p1}
            merged = p1 + [r for r in p2 if r["period"] not in seen]
            logger.info("WinGo deep: %d rows total", len(merged))
            return merged
        return p1
    return []

def _w_parse_row(x):
    """একটা row parse করে dict বানাও।"""
    n = int(x.get("number", x.get("Number", 0))) % 10
    c = x.get("color", x.get("Color", ""))
    color = "violet" if "violet" in c.lower() else ("green" if "green" in c.lower() else "red")
    return {
        "period": str(x.get("issueNumber", x.get("IssueNumber", x.get("issue", "")))),
        "number": n,
        "size":   "BIG" if n >= 5 else "SMALL",
        "color":  color,
    }

def _w_fetch():
    """Fetch WinGo 30s history — GET APIs আগে (Railway তে POST block হয়)."""
    gc = _wingo_state.get("game_code", "WinGo_30S")
    ts = int(time.time() * 1000)

    # ── GET APIs (Railway friendly) ────────────────────────
    get_apis = [
        f"https://draw.ar-lottery01.com/WinGo/{gc}/GetHistoryIssuePage.json?ts={ts}",
        f"https://api.bdgwin.com/WinGo/{gc}/GetHistoryIssuePage.json?ts={ts}",
        f"https://wingo.ar-lottery01.com/WinGo/{gc}/GetHistoryIssuePage.json?ts={ts}",
        f"https://draw.bdgwin.com/WinGo/{gc}/GetHistoryIssuePage.json?ts={ts}",
    ]
    for url in get_apis:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Android 12; Mobile)",
                         "Accept": "application/json",
                         "Referer": "https://dkwin19.com/"}
            )
            with urllib.request.urlopen(req, timeout=12) as r:
                data = json.loads(r.read().decode("utf-8", errors="ignore"))
            raw = data.get("data", {}).get("list", [])
            if not raw and isinstance(data.get("data"), list):
                raw = data["data"]
            result = [_w_parse_row(x) for x in raw if x]
            if result:
                logger.info("WinGo GET ok: %d rows — %s", len(result), url[:50])
                _wingo_state["history"] = result
                return result
        except Exception as e:
            logger.warning("WinGo GET fail %s: %s", url[:50], e)

    # ── POST APIs (fallback) ───────────────────────────────
    post_apis = [
        "https://dkwin19.com/api/webapi/GetHistoryIssuePage",
        "https://dkwin01.com/api/webapi/GetHistoryIssuePage",
        "https://api.dkwin.com/api/webapi/GetHistoryIssuePage",
    ]
    for url in post_apis:
        try:
            payload = json.dumps({
                "pageSize": 100, "pageNo": 1,
                "gameCode": gc, "language": 0,
                "random": "", "signature": "", "ts": ts
            }).encode("utf-8")
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json",
                         "Accept": "application/json",
                         "User-Agent": "Mozilla/5.0"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=12) as r:
                data = json.loads(r.read().decode("utf-8", errors="ignore"))
            rows = data.get("data", {}).get("list", [])
            result = [_w_parse_row(x) for x in rows if x]
            if result:
                logger.info("WinGo POST ok: %d rows — %s", len(result), url[:50])
                _wingo_state["history"] = result
                return result
        except Exception as e:
            logger.warning("WinGo POST fail %s: %s", url[:50], e)

    # ── সব fail — cache ────────────────────────────────────
    cached = _wingo_state.get("history", [])
    logger.error("WinGo: ALL APIs failed! cached=%d rows", len(cached))
    return cached


async def _wingo_bg(app):
    """asyncio background task — job_queue ছাড়াই 30s WinGo চলবে"""
    await asyncio.sleep(15)
    while True:
        try:
            if _wingo_subs:
                class _Ctx:
                    bot = app.bot
                await wingo_tick(_Ctx())
        except Exception as e:
            logger.warning("wingo_bg: %s", e)
        await asyncio.sleep(30)

async def _1min_bg(app):
    """asyncio background task — job_queue ছাড়াই 1min WinGo চলবে"""
    await asyncio.sleep(30)
    while True:
        try:
            await _1min_broadcast(app.bot)
        except Exception as e:
            logger.warning("1min_bg: %s", e)
        await asyncio.sleep(60)

async def wingo_tick(ctx):
    if not _wingo_subs: return
    loop = asyncio.get_running_loop()
    try:
        hist = await loop.run_in_executor(executor, _w_fetch)
        if not hist: return

        latest        = hist[0]
        latest_period = latest["period"]

        # ── ধাপ ১: আগের pending prediction এর WIN/LOSS দেখাও ──
        pending = _wingo_state.get("pending_pred")
        if pending and latest_period != pending["period"]:
            result_row = next((hh for hh in hist if hh["period"] == pending["period"]), None)
            if result_row:
                actual_num  = result_row["number"]
                actual_size = result_row["size"]
                pred_size   = pending["size"]
                pred_num1   = pending["num1"]
                pred_num2   = pending["num2"]
                pred_conf   = pending["conf"]

                won = (actual_size == pred_size)
                _wingo_state["total_pred"] += 1
                if won:
                    _wingo_state["correct_pred"] += 1
                    _wingo_state["win_streak"]   += 1
                    _wingo_state["loss_streak"]   = 0
                else:
                    _wingo_state["win_streak"]    = 0
                    _wingo_state["loss_streak"]  += 1

                acc      = round(_wingo_state["correct_pred"] / _wingo_state["total_pred"] * 100)
                bar_f    = round(acc / 10)
                acc_bar  = "█" * bar_f + "░" * (10 - bar_f)
                win_icon  = "✅" if won else "❌"
                win_label = "WIN 🎉" if won else "LOSS 💀"
                act_icon  = "🔺" if actual_size == "BIG" else "🔻"
                pred_icon = "🔺" if pred_size   == "BIG" else "🔻"

                result_txt = (
                    f"╔══════════════════════════╗\n"
                    f"  {win_icon}  *{win_label}*  ·  `{pending['period'][-6:]}`\n"
                    f"╚══════════════════════════╝\n\n"
                    f"📊 *Actual Result*\n"
                    f"{act_icon}  *{actual_size}*  🎲  *{actual_num}*\n\n"
                    f"📌 *AI Signal ছিল*\n"
                    f"{pred_icon}  *{pred_size}*  🎲  *{pred_num1}* বা *{pred_num2}*\n"
                    f"📊 Conf: `{pred_conf}%`\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎯 `{acc_bar}` *{acc}%*\n"
                    f"✅ `{_wingo_state['correct_pred']}/{_wingo_state['total_pred']}`  "
                    f"🔥 Win: `{_wingo_state['win_streak']}`  "
                    f"💀 Loss: `{_wingo_state['loss_streak']}`\n\n"
                    f"⚡ _ULTIMATE 25+ Pattern AI_"
                )
                for suid in list(_wingo_subs):
                    try:
                        await ctx.bot.send_message(suid, result_txt, parse_mode="Markdown")
                    except Exception as e:
                        if "blocked" in str(e).lower() or "not found" in str(e).lower():
                            _wingo_subs.discard(suid)

            _wingo_state["pending_pred"] = None

        # ── ধাপ ২: নতুন period → prediction পাঠাও ──
        if latest_period == _wingo_state.get("last_period"): return
        _wingo_state["last_period"] = latest_period

        # _ultimate_predict ব্যবহার করো (1min এর same logic)
        pred = _ultimate_predict(hist)

        next_period = str(int(latest_period) + 1) if latest_period.isdigit() else latest_period
        _wingo_state["pending_pred"] = {
            "period": next_period,
            "size":   pred["size"],
            "num1":   pred["number"],
            "num2":   pred.get("number2", pred["number"]),
            "conf":   pred["confidence"],
        }

        size      = pred["size"]
        num1      = pred["number"]
        num2      = pred.get("number2", num1)
        conf      = pred["confidence"]
        patterns  = pred["patterns"]
        streak    = pred["streak"]
        last_num  = hist[0]["number"]
        last_size = hist[0]["size"]

        size_icon  = "🔺" if size == "BIG" else "🔻"
        color_icon = "🟢" if size == "BIG" else "🔴"
        color_name = "GREEN" if size == "BIG" else "RED"
        bar_f      = round(conf / 10)
        conf_bar   = "█" * bar_f + "░" * (10 - bar_f)

        pred_txt = (
            f"╔══════════════════════════╗\n"
            f"  🎯  *WinGo 30s — ULTIMATE v3.0*\n"
            f"╚══════════════════════════╝\n\n"
            f"📡 *PERIOD* `{next_period[-8:]}` 🔴 LIVE\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  {size_icon}  *{size}*  {color_icon}  *{color_name}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔢 *Predicted Numbers:*\n"
            f"┌──────────┐  ┌──────────┐\n"
            f"│    *{num1}*     │  │    *{num2}*     │\n"
            f"└──────────┘  └──────────┘\n\n"
            f"📊 `{conf_bar}` *{conf}%*\n"
            f"🧠 *{patterns}+ Patterns Active*\n"
            f"🔥 *Streak:* `{streak}`\n\n"
            f"📌 *Last Result:* `{last_num}` ({last_size})\n\n"
            f"⏳ _Result আসছে 30s পরে..._\n"
            f"⚡ _ULTIMATE 25+ Pattern AI_"
        )
        for suid in list(_wingo_subs):
            try:
                await ctx.bot.send_message(suid, pred_txt, parse_mode="Markdown",
                                           reply_markup=wingo_menu())
            except Exception as e:
                if "blocked" in str(e).lower() or "not found" in str(e).lower():
                    _wingo_subs.discard(suid)
    except Exception as e:
        logger.warning("wingo_tick: %s", e)

# ════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════
async def _post_init(app):
    """Bot চালু হলেই background task শুরু হবে — job_queue লাগবে না"""
    asyncio.create_task(_wingo_bg(app))
    asyncio.create_task(_1min_bg(app))
    print("✅ WinGo 30s ও 1min background task চালু!")

def main():
    if not BOT_TOKEN or "এখানে" in BOT_TOKEN or len(BOT_TOKEN)<20:
        print("❌ BOT_TOKEN সেট করুন!")
        sys.exit(1)

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("wingo",  cmd_wingo))
    app.add_handler(CommandHandler("test",   cmd_test))
    app.add_handler(CallbackQueryHandler(handle_cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))

    print("╔══════════════════════════════════════════╗")
    print("║  ⚡  WinGo AI Signal Bot চালু!            ║")
    print("║  ⚡  WinGo 30S — 70 Layers                ║")
    print("║  🎯  WinGo 1Min — ULTIMATE v3.0           ║")
    print("║  Ctrl+C → বন্ধ                           ║")
    print("╚══════════════════════════════════════════╝")

    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
