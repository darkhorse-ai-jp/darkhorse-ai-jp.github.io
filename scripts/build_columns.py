#!/usr/bin/env python3
"""
build_columns.py  ─  記事データからHTMLを一括生成 + column.html を最新順に再構築
実行: python3 scripts/build_columns.py
"""
from pathlib import Path
import re, json

SITE_DIR = Path(__file__).parent.parent

BOOKS = {
    "pandas": ("4814400535", "📊", "Pythonによるデータ分析入門 第3版", "Wes McKinney 著",
               "pandas・NumPyを使ったデータ処理の定番書。競馬データ分析の基礎固めに。"),
    "ml":     ("4295010073", "🤖", "Pythonではじめる機械学習", "Andreas C. Müller 著",
               "scikit-learnで学ぶ機械学習の定番書。決定木からアンサンブルまで丁寧に解説。"),
    "stats":  ("4621307738", "📈", "統計学が最強の学問である", "西内 啓 著",
               "データ分析の統計思考をやさしく解説。オッズと確率の関係を直感的に理解できます。"),
    "gamble": ("4478025819", "🎲", "ギャンブルで勝つ唯一の方法 数学的思考", "エドワード・O・ソープ 著",
               "ケリー基準・期待値戦略の原点。長期的に優位性を保つ賭け方の理論的根拠を学べます。"),
}

CAT = {
    "データ分析": ("#fde8e8", "var(--miss)"),
    "馬券戦略":   ("#e8f5e9", "var(--hit)"),
    "AI解説":     ("#e8eaf6", "#3949ab"),
}

COMMON_JS = """\
<script>
  (function() {
    const page = location.pathname.split('/').pop() || 'index.html';
    document.querySelectorAll('nav a, .mobile-nav a').forEach(a => {
      if (a.getAttribute('href') === page) a.setAttribute('aria-current', 'page');
    });
  })();
  (function() {
    const btn = document.getElementById('hamburger-btn');
    const nav = document.getElementById('mobile-nav');
    if (!btn || !nav) return;
    const origClick = btn.onclick;
    btn.onclick = function(e) {
      if (origClick) origClick.call(this, e);
      document.body.classList.toggle('menu-open', nav.classList.contains('open'));
    };
    nav.querySelectorAll('a').forEach(a => {
      a.addEventListener('click', () => {
        nav.classList.remove('open');
        btn.setAttribute('aria-expanded', 'false');
        document.body.classList.remove('menu-open');
      });
    });
  })();
  (function() {
    const btn = document.getElementById('back-to-top');
    if (!btn) return;
    window.addEventListener('scroll', () => {
      btn.classList.toggle('visible', window.scrollY > 300);
    }, { passive: true });
    btn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  })();
</script>"""


def book_html(keys, associate_id):
    items = ""
    for k in keys:
        asin, emoji, title, author, desc = BOOKS[k]
        url = f"https://www.amazon.co.jp/dp/{asin}?tag={associate_id}"
        items += f"""      <a class="book-card" href="{url}" target="_blank" rel="noopener sponsored">
        <div class="book-cover">{emoji}</div>
        <div class="book-info">
          <div class="book-title">{title}</div>
          <div class="book-author">{author}</div>
          <div class="book-desc">{desc}</div>
          <span class="book-btn">Amazonで見る →</span>
        </div>
      </a>\n"""
    return f"""      <div class="affiliate-books">
        <h3>📚 関連書籍 <span class="pr-badge">PR / Amazon</span></h3>
{items}        <p style="font-size:.72rem;color:var(--muted);margin-top:12px;">※Amazonアソシエイト・プログラムに基づく広告を含みます。</p>
      </div>"""


def render(art, associate_id, all_articles):
    col_id = art["id"]
    title  = art["title"]
    cat    = art["cat"]
    date   = art["date"]
    bg, col = CAT.get(cat, ("#f0f4f8", "var(--muted)"))
    base_url = "https://mspj0123.github.io/darkhorse-site"

    # ── 本文 ──
    body = f'      <p>\n        {art["intro"]}\n      </p>\n'
    for sec in art["secs"]:
        h2 = sec[0]
        body += f'\n      <h2>{h2}</h2>\n'
        for para in sec[1]:
            body += f'      <p>\n        {para}\n      </p>\n'
        if len(sec) > 2 and sec[2]:
            body += '      <ul>\n'
            for li in sec[2]:
                body += f'        <li>{li}</li>\n'
            body += '      </ul>\n'

    # ── まとめボックス ──
    box_title, box_items = art["box"]
    items_html = ''.join(f'          <li>{i}</li>\n' for i in box_items)
    body += f"""
      <div class="point-box">
        <strong>{box_title}</strong>
        <ul style="margin:8px 0 0 0;">
{items_html}        </ul>
      </div>
"""
    body += """
      <p style="font-size:.85rem;color:var(--muted);margin-top:32px;padding-top:16px;border-top:1px solid var(--border);">
        ※本記事はDarkHorse AIのデータ分析に基づく参考情報です。馬券の購入は自己責任でお願いします。
        詳細は<a href="disclaimer.html">免責事項</a>をご確認ください。
      </p>
"""

    # ── アフィリエイト ──
    body += "\n" + book_html(art["books"], associate_id) + "\n"

    # ── SNSシェア ──
    enc = title.replace(" ", "%20")
    page_url = f"{base_url}/column-{col_id}.html"
    body += f"""
      <div class="share-buttons">
        <span class="share-label">この記事をシェア：</span>
        <a class="share-btn share-btn-x" href="https://x.com/intent/tweet?text={enc}%20%7C%20DarkHorse%20AI&url={page_url}" target="_blank" rel="noopener">𝕏 でシェア</a>
        <a class="share-btn share-btn-line" href="https://social-plugins.line.me/lineit/share?url={page_url}" target="_blank" rel="noopener">LINE でシェア</a>
        <button class="share-btn share-btn-copy" onclick="navigator.clipboard.writeText(location.href).then(()=>{{this.textContent='コピーしました！';setTimeout(()=>{{this.textContent='URLをコピー'}},2000)}})">URLをコピー</button>
      </div>
"""

    # ── 関連記事（異なるカテゴリ優先で3件） ──
    others = [a for a in all_articles if a["id"] != col_id]
    others.sort(key=lambda a: (a["cat"] == cat, -int(a["id"])))
    related = others[:3]
    if related:
        rel_items = ""
        for r in related:
            rel_items += f'          <li><span class="rel-tag">{r["cat"]}</span><a href="column-{r["id"]}.html">{r["title"]}</a></li>\n'
        body += f"""
      <div class="related-articles">
        <div class="rel-title">関連記事</div>
        <ul>
{rel_items}        </ul>
      </div>
"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} | DarkHorse AI コラム</title>
  <meta name="description" content="{art['desc'][:120]}">
  <meta property="og:title" content="{title} | DarkHorse AI">
  <meta property="og:type" content="article">
  <link rel="stylesheet" href="css/style.css">
  <style>
    .article-body {{ max-width: 720px; }}
    .article-body h2 {{ font-size: 1.2rem; color: var(--primary); border-bottom: 2px solid var(--accent); padding-bottom: 6px; margin: 32px 0 14px; }}
    .article-body p {{ margin-bottom: 14px; line-height: 1.8; }}
    .article-body ul, .article-body ol {{ margin: 10px 0 16px 20px; line-height: 2; }}
    .point-box {{ background: #f0f4f8; border-left: 4px solid var(--accent); padding: 16px 20px; border-radius: 4px; margin: 20px 0; }}
    .point-box strong {{ display: block; margin-bottom: 6px; }}
    .data-highlight {{ background: var(--primary); color: #fff; display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: .9rem; font-weight: bold; }}
  </style>
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-4265350416312017" crossorigin="anonymous"></script>
</head>
<body>
<header>
  <div class="header-inner">
    <a class="logo" href="index.html">🐴 DarkHorse <span>AI</span></a>
    <nav>
      <a href="prediction.html">今週の予測</a>
      <a href="results.html">過去の成績</a>
      <a href="about.html">予測ロジック</a>
      <a href="column.html">コラム</a>
      <a href="faq.html">FAQ</a>
    </nav>
    <button class="hamburger" id="hamburger-btn" onclick="document.getElementById('mobile-nav').classList.toggle('open')" aria-label="メニュー">
      <span></span><span></span><span></span>
    </button>
  </div>
  <div class="mobile-nav" id="mobile-nav">
    <a href="index.html">トップ</a>
    <a href="prediction.html">今週の予測</a>
    <a href="results.html">過去の成績</a>
    <a href="about.html">予測ロジック</a>
    <a href="column.html">コラム</a>
    <a href="faq.html">FAQ</a>
    <a href="contact.html">お問い合わせ</a>
  </div>
</header>
<main>
  <div class="container">
    <div class="article-body" style="padding:32px 0;">
      <p style="font-size:.85rem;color:var(--muted);margin-bottom:8px;"><a href="column.html">コラム</a> &gt; {cat}</p>
      <div style="display:inline-block;background:{bg};color:{col};font-size:.8rem;padding:2px 10px;border-radius:10px;margin-bottom:12px;">{cat}</div>
      <h1 style="font-size:1.6rem;color:var(--primary);margin-bottom:8px;line-height:1.4;">{title}</h1>
      <p style="color:var(--muted);font-size:.85rem;margin-bottom:24px;">{date} | DarkHorse AI編集部</p>
{body}
    </div>
  </div>
</main>
<footer>
  <div class="footer-links">
    <a href="disclaimer.html">免責事項</a>
    <a href="privacy.html">プライバシーポリシー</a>
    <a href="contact.html">お問い合わせ</a>
  </div>
  <p>&copy; 2024 DarkHorse AI. All rights reserved.</p>
</footer>
<button id="back-to-top" aria-label="ページトップへ">&#8679;</button>
{COMMON_JS}
</body>
</html>"""


def _date_sort_key(art):
    """'YYYY年MM月' 形式の date フィールドを (year, month) タプルに変換してソートキーにする。"""
    import re as _re
    m = _re.search(r'(\d{4})年(\d{1,2})月', art.get("date", ""))
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return (0, 0)


def rebuild_column_index(all_articles):
    """column.html のカード一覧を記事の日付降順で再構築する。"""
    col_html = SITE_DIR / "column.html"
    content = col_html.read_text()

    cards = ""
    for art in sorted(all_articles, key=_date_sort_key, reverse=True):
        col_id = art["id"]
        cat = art["cat"]
        bg, col = CAT.get(cat, ("#f0f4f8", "var(--muted)"))
        desc_short = art["desc"][:85] + ("…" if len(art["desc"]) > 85 else "")
        cards += f"""
    <a href="column-{col_id}.html" data-category="{cat}" class="col-card-wrap" style="display:block;text-decoration:none;color:inherit;">
      <div class="column-card">
        <div style="display:flex;align-items:flex-start;gap:16px;">
          <div style="flex:1;">
            <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;">
              <span style="display:inline-block;background:{bg};color:{col};font-size:.75rem;padding:2px 8px;border-radius:10px;">{cat}</span>
              <span style="font-size:.78rem;color:var(--muted);">{art['date']}</span>
            </div>
            <h3 style="font-size:1.05rem;color:var(--primary);margin-bottom:6px;line-height:1.5;">{art['title']}</h3>
            <p style="font-size:.85rem;color:var(--muted);line-height:1.6;">{desc_short}</p>
          </div>
        </div>
      </div>
    </a>"""

    new_content = re.sub(
        r'(<!-- 公開済み記事 -->.*?)(\s*</div>\s*</main>)',
        f'<!-- 公開済み記事 -->\n{cards}\n\n  </div>\n</main>',
        content, flags=re.DOTALL
    )
    if new_content == content:
        # フォールバック: 既存カードを全置換
        new_content = re.sub(
            r'(<a href="column-.*?</a>\s*)+',
            cards + "\n\n",
            content, flags=re.DOTALL
        )
    col_html.write_text(new_content)
    print(f"column.html を最新順で再構築しました（{len(all_articles)}件）")


def main():
    from article_data import ARTICLES  # 記事データは別ファイルに分離

    config_file = SITE_DIR / "config.json"
    if config_file.exists():
        with open(config_file) as f:
            cfg = json.load(f)
        associate_id = cfg.get("amazon_associate_id", "your-associate-id-22")
    else:
        associate_id = "your-associate-id-22"

    generated = 0
    for art in ARTICLES:
        if "intro" not in art:  # 既存記事（01-05）はスキップ
            continue
        html = render(art, associate_id, ARTICLES)
        out = SITE_DIR / f"column-{art['id']}.html"
        out.write_text(html)
        print(f"  生成: column-{art['id']}.html  [{art['cat']}] {art['title'][:30]}…")
        generated += 1

    rebuild_column_index(ARTICLES)
    print(f"\n完了: {generated}件のHTMLを生成しました。")


if __name__ == "__main__":
    main()
