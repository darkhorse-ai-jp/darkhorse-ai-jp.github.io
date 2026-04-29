#!/usr/bin/env python3
"""
月次コラム自動生成スクリプト（Claude API 不要）

DBの実績データから月次振り返りコラム記事を生成する。
既存の column-XX.html と同じテイスト・構成で HTML を生成し、
column.html インデックスも更新する。

使い方:
  python3 scripts/generate_monthly_column.py              # 先月分を生成
  python3 scripts/generate_monthly_column.py --month 2026-04  # 月を指定
  python3 scripts/generate_monthly_column.py --push       # 生成後に git push

毎月1日の cron 実行を想定:
  0 8 1 * * cd /path/to/DarkHorseAI && python3 darkhorse-site/scripts/generate_monthly_column.py --push
"""

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

SITE_DIR   = Path(__file__).parent.parent
SCRIPTS_DIR = Path(__file__).parent
DB_PATH    = Path(__file__).parent.parent.parent / "data" / "darkhorse.db"

VENUE_MAP = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}


# ─────────────────────────────────────────
# DB からデータ抽出
# ─────────────────────────────────────────

def fetch_monthly_stats(conn: sqlite3.Connection, year: int, month: int) -> dict:
    """指定月の万馬券統計を取得する。"""
    ym = f"{year:04d}-{month:02d}"
    cur = conn.cursor()

    # 万馬券レース一覧（10,000円以上、現実的な上限 50万円）
    cur.execute("""
        SELECT r.race_date, r.venue, r.race_number, r.race_name,
               r.head_count, r.surface, r.distance, r.track_cond,
               p.payout
        FROM payouts p
        JOIN races r ON p.race_id = r.race_id
        WHERE p.bet_type = 'sanrenpuku'
          AND p.payout BETWEEN 10000 AND 500000
          AND r.race_date LIKE ?
        ORDER BY p.payout DESC
    """, (f"{ym}%",))
    upsets = [
        {
            "date":      row[0],
            "venue":     VENUE_MAP.get(row[1], row[1]),
            "race_no":   row[2],
            "race_name": row[3] or f"{row[2]}R",
            "heads":     row[4],
            "surface":   "芝" if row[5] == "turf" else "ダート",
            "distance":  row[6],
            "track":     row[7] or "",
            "payout":    row[8],
        }
        for row in cur.fetchall()
    ]

    # 総レース数
    cur.execute("SELECT COUNT(DISTINCT race_id) FROM races WHERE race_date LIKE ?", (f"{ym}%",))
    total_races = cur.fetchone()[0] or 0

    # 万馬券発生率
    upset_count = len(upsets)
    upset_rate  = round(upset_count / total_races * 100, 1) if total_races else 0

    # 配当帯別分布
    cur.execute("""
        SELECT
          SUM(CASE WHEN payout BETWEEN 10000  AND 29999  THEN 1 ELSE 0 END) as w1,
          SUM(CASE WHEN payout BETWEEN 30000  AND 99999  THEN 1 ELSE 0 END) as w2,
          SUM(CASE WHEN payout BETWEEN 100000 AND 500000 THEN 1 ELSE 0 END) as w3
        FROM payouts p JOIN races r ON p.race_id=r.race_id
        WHERE p.bet_type='sanrenpuku' AND p.payout BETWEEN 10000 AND 500000
          AND r.race_date LIKE ?
    """, (f"{ym}%",))
    row = cur.fetchone()
    dist = {"1万〜3万": row[0] or 0, "3万〜10万": row[1] or 0, "10万以上": row[2] or 0}

    # 会場別万馬券数
    cur.execute("""
        SELECT r.venue, COUNT(*) as cnt
        FROM payouts p JOIN races r ON p.race_id=r.race_id
        WHERE p.bet_type='sanrenpuku' AND p.payout BETWEEN 10000 AND 500000
          AND r.race_date LIKE ?
        GROUP BY r.venue ORDER BY cnt DESC LIMIT 3
    """, (f"{ym}%",))
    top_venues = [(VENUE_MAP.get(r[0], r[0]), r[1]) for r in cur.fetchall()]

    # 頭数別万馬券率（16頭 vs それ未満）
    cur.execute("""
        SELECT
          SUM(CASE WHEN r.head_count >= 16 THEN 1 ELSE 0 END) as full,
          SUM(CASE WHEN r.head_count  < 16 THEN 1 ELSE 0 END) as small
        FROM payouts p JOIN races r ON p.race_id=r.race_id
        WHERE p.bet_type='sanrenpuku' AND p.payout >= 10000
          AND r.race_date LIKE ?
    """, (f"{ym}%",))
    row = cur.fetchone()
    full_gate_upsets  = row[0] or 0
    small_gate_upsets = row[1] or 0

    # 芝 vs ダート
    cur.execute("""
        SELECT r.surface, COUNT(*) as cnt
        FROM payouts p JOIN races r ON p.race_id=r.race_id
        WHERE p.bet_type='sanrenpuku' AND p.payout >= 10000
          AND r.race_date LIKE ?
        GROUP BY r.surface
    """, (f"{ym}%",))
    surface_dist = {r[0]: r[1] for r in cur.fetchall()}
    turf_upsets  = surface_dist.get("turf",  0)
    dirt_upsets  = surface_dist.get("dirt",  0)

    return {
        "year":              year,
        "month":             month,
        "total_races":       total_races,
        "upset_count":       upset_count,
        "upset_rate":        upset_rate,
        "upsets":            upsets,
        "dist":              dist,
        "top_venues":        top_venues,
        "full_gate_upsets":  full_gate_upsets,
        "small_gate_upsets": small_gate_upsets,
        "turf_upsets":       turf_upsets,
        "dirt_upsets":       dirt_upsets,
    }


# ─────────────────────────────────────────
# 記事データ dict を生成（build_columns.py の render() に渡す形式）
# ─────────────────────────────────────────

def make_article_dict(stats: dict, col_id: str) -> dict:
    """DBの月次統計から記事データdictを組み立てる。"""
    y, m = stats["year"], stats["month"]
    month_ja = f"{y}年{m}月"

    upset_count    = stats["upset_count"]
    total_races    = stats["total_races"]
    upset_rate     = stats["upset_rate"]
    top3           = stats["upsets"][:3]
    dist           = stats["dist"]
    top_venues     = stats["top_venues"]
    full_g         = stats["full_gate_upsets"]
    small_g        = stats["small_gate_upsets"]
    turf_u         = stats["turf_upsets"]
    dirt_u         = stats["dirt_upsets"]

    # 最高配当レース
    top1 = top3[0] if top3 else None
    top1_str = (
        f"{top1['venue']}{top1['race_no']}R「{top1['race_name']}」"
        f"（{top1['payout']:,}円）"
        if top1 else "データなし"
    )

    # 会場傾向
    venue_str = "・".join(f"{v}（{c}件）" for v, c in top_venues) if top_venues else "集計中"

    # 芝ダート比率コメント
    if turf_u + dirt_u > 0:
        turf_pct = round(turf_u / (turf_u + dirt_u) * 100)
        surface_comment = (
            f"コース別では芝{turf_pct}%・ダート{100-turf_pct}%という内訳でした。"
            f"{'芝レースでの波乱が目立ちました。' if turf_pct >= 60 else 'ダートレースでの波乱が多い月でした。'}"
        )
    else:
        surface_comment = "芝・ダートともに万馬券が出ました。"

    # フルゲートコメント
    if full_g + small_g > 0:
        full_pct = round(full_g / (full_g + small_g) * 100)
        fullgate_comment = (
            f"出走頭数別では16頭フルゲートのレースが{full_pct}%を占めており、"
            f"{'多頭数での波乱が目立つ月となりました。' if full_pct >= 60 else '少頭数でも波乱が起きており、頭数だけで判断できない月でした。'}"
        )
    else:
        fullgate_comment = "出走頭数によらず万馬券が出ました。"

    # 配当帯コメント
    heavy_count = dist.get("10万以上", 0)
    heavy_comment = (
        f"なかでも三連複100,000円を超える「超万馬券」が{heavy_count}件発生しており、"
        "改めて波乱の大きさを示す結果となりました。"
        if heavy_count > 0
        else "大きな配当への偏りは少なく、万馬券がバランスよく分散した月でした。"
    )

    # TOP3 レース詳細テキスト
    top3_paras = []
    for i, r in enumerate(top3, 1):
        track_note = f"（馬場：{r['track']}）" if r["track"] else ""
        top3_paras.append(
            f"<strong>第{i}位：{r['venue']}{r['race_no']}R「{r['race_name']}」"
            f"　{r['payout']:,}円</strong>{track_note}　"
            f"{r['date']}開催・{r['surface']}{r['distance']}m・{r['heads']}頭立て。"
            f"三連複配当{r['payout']:,}円の波乱でした。"
        )

    if not top3_paras:
        top3_paras = ["今月はデータが集計中です。来月以降の記事もお楽しみください。"]

    # ── 記事 dict 組み立て ──
    return {
        "id":    col_id,
        "date":  month_ja,
        "cat":   "データ分析",
        "title": f"{month_ja}の万馬券振り返り：波乱{upset_count}件、発生率{upset_rate}%の分析",
        "desc":  (
            f"DarkHorse AIが{month_ja}の全競馬データを分析。"
            f"三連複万馬券は{upset_count}件発生（発生率{upset_rate}%）。"
            f"最高配当は{top1_str}。波乱が起きた共通条件を徹底解説。"
        ),
        "intro": (
            f"{month_ja}のJRAレースを振り返ります。"
            f"今月は全{total_races}レース中、三連複万馬券（10,000円以上）が{upset_count}件発生しました。"
            f"発生率{upset_rate}%という数字は、競馬における波乱の頻度を改めて示しています。"
            f"データから見えてきた傾向を解説します。"
        ),
        "secs": [
            (
                "今月の万馬券サマリー",
                [
                    f"今月の万馬券は合計<strong>{upset_count}件</strong>発生しました。"
                    f"全{total_races}レースに占める割合は<strong>{upset_rate}%</strong>です。",

                    f"配当帯の内訳は、1万〜3万円が{dist['1万〜3万']}件、"
                    f"3万〜10万円が{dist['3万〜10万']}件、"
                    f"10万円以上が{dist['10万以上']}件でした。"
                    f"{heavy_comment}",

                    f"開催会場別では{venue_str}が万馬券の多かった会場です。"
                    f"{surface_comment}",
                ],
                None,
            ),
            (
                "今月の万馬券TOP3",
                top3_paras,
                None,
            ),
            (
                "波乱が起きた共通条件",
                [
                    f"{fullgate_comment}フルゲート（16頭以上）では"
                    f"{full_g}件、それ未満では{small_g}件の万馬券が出ています。",

                    "DarkHorse AIが重視する条件（1番人気オッズ3倍以上・出走16頭・"
                    "1番人気が前走と大きく条件変化）と照らし合わせると、"
                    "今月の万馬券も同様のパターンが多く見られました。",

                    "波乱を事前に察知するには、単勝オッズの分布と頭数の組み合わせが"
                    "最も有効な手がかりになります。次月もこの視点でレースを観察してみてください。",
                ],
                None,
            ),
            (
                "AIモデルの視点から",
                [
                    "DarkHorse AIは「三連複万馬券が出る確率」を0〜100%で出力します。"
                    "今月の結果と照らし合わせると、確率の高いレースほど実際に波乱が起きやすい"
                    "傾向が確認できます。",

                    "モデルの学習データには過去5年以上の実績が含まれており、"
                    "毎週金曜夜に翌週末のレース予測を自動更新しています。"
                    "今週の予測は「今週の予測」ページからご確認ください。",
                ],
                None,
            ),
        ],
        "box": (
            f"{month_ja}データまとめ",
            [
                f"万馬券発生件数：{upset_count}件（発生率{upset_rate}%）",
                f"最高配当：{top1_str}",
                f"配当帯：1万〜3万円 {dist['1万〜3万']}件 ／ 3万〜10万円 {dist['3万〜10万']}件 ／ 10万円以上 {dist['10万以上']}件",
                f"フルゲートでの万馬券：{full_g}件 ／ 少頭数：{small_g}件",
            ],
        ),
        "books": ["stats", "gamble"],
    }


# ─────────────────────────────────────────
# HTML 生成・ファイル書き出し
# ─────────────────────────────────────────

def get_next_col_id(site_dir: Path) -> str:
    """既存の column-XX.html を調べて次の ID を返す（2桁ゼロ埋め）。"""
    existing = [p.stem for p in site_dir.glob("column-[0-9]*.html")]
    ids = []
    for stem in existing:
        try:
            ids.append(int(stem.split("-")[1]))
        except (IndexError, ValueError):
            pass
    next_id = max(ids, default=31) + 1
    return f"{next_id:02d}"


def load_config(site_dir: Path) -> dict:
    cfg_path = site_dir / "config.json"
    if cfg_path.exists():
        with open(cfg_path) as f:
            return json.load(f)
    return {}


def generate(month_str: str, push: bool = False, dry_run: bool = False) -> None:
    """メイン生成処理。month_str は 'YYYY-MM' 形式。"""
    year, month = map(int, month_str.split("-"))

    if not DB_PATH.exists():
        print(f"[エラー] DBが見つかりません: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    stats = fetch_monthly_stats(conn, year, month)
    conn.close()

    if stats["total_races"] == 0:
        print(f"[警告] {month_str} のレースデータがDBに存在しません。スキップします。")
        sys.exit(0)

    col_id = get_next_col_id(SITE_DIR)
    print(f"[INFO] 生成する記事ID: column-{col_id}.html")
    print(f"[INFO] 対象月: {year}年{month}月  総レース数: {stats['total_races']}  万馬券: {stats['upset_count']}件")

    if dry_run:
        print("[DRY-RUN] 実際には生成しません。")
        return

    art = make_article_dict(stats, col_id)

    # build_columns.py の render() を再利用
    sys.path.insert(0, str(SCRIPTS_DIR))
    from build_columns import render, rebuild_column_index
    from article_data  import ARTICLES

    cfg = load_config(SITE_DIR)
    associate_id = cfg.get("amazon_associate_id", "your-associate-id-22")

    all_articles = ARTICLES + [art]
    html = render(art, associate_id, all_articles)

    out_path = SITE_DIR / f"column-{col_id}.html"
    out_path.write_text(html)
    print(f"[OK] 生成: {out_path.name}  「{art['title']}」")

    # article_data.py に追記（メタデータのみ、次回 get_next_col_id のため）
    _append_metadata(art)

    # column.html 再構築
    rebuild_column_index(all_articles)
    print("[OK] column.html を更新しました")

    if push:
        _git_push(SITE_DIR, col_id)


def _append_metadata(art: dict) -> None:
    """article_data.py の ARTICLES リストに新記事のメタデータ行を追記する。"""
    data_file = SCRIPTS_DIR / "article_data.py"
    entry = (
        f'    {{"id": "{art["id"]}", "date": "{art["date"]}", "cat": "{art["cat"]}", '
        f'"title": "{art["title"]}", "desc": "{art["desc"]}"}},\n'
    )
    content = data_file.read_text()
    # ARTICLES リストの末尾（]の直前）に挿入
    insert_pos = content.rfind("]")
    if insert_pos == -1:
        print("[警告] article_data.py の末尾が見つかりません。手動で追加してください。")
        return
    content = content[:insert_pos] + entry + content[insert_pos:]
    data_file.write_text(content)
    print(f"[OK] article_data.py にメタデータを追記しました")


def _git_push(site_dir: Path, col_id: str) -> None:
    files = [
        f"column-{col_id}.html",
        "column.html",
        "scripts/article_data.py",
    ]
    subprocess.run(["git", "-C", str(site_dir), "add"] + files, check=True)
    msg = f"feat: 月次コラム自動生成 column-{col_id}.html"
    subprocess.run(["git", "-C", str(site_dir), "commit", "-m", msg], check=True)
    subprocess.run(["git", "-C", str(site_dir), "push", "origin", "main"], check=True)
    print("[OK] git push 完了")


# ─────────────────────────────────────────
# CLI
# ─────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="月次コラム自動生成（API不要）")
    parser.add_argument(
        "--month", default=None,
        help="対象月 YYYY-MM（省略時は先月）",
    )
    parser.add_argument("--push",    action="store_true", help="生成後に git push")
    parser.add_argument("--dry-run", action="store_true", help="生成せず統計だけ表示")
    args = parser.parse_args()

    if args.month:
        month_str = args.month
    else:
        today = date.today()
        first_of_this_month = today.replace(day=1)
        last_month = first_of_this_month - timedelta(days=1)
        month_str = last_month.strftime("%Y-%m")

    generate(month_str, push=args.push, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
