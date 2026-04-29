#!/usr/bin/env python3
"""
DarkHorse AI コラム自動生成スクリプト

使い方:
  python3 scripts/generate_column.py           # 次のトピックを1記事生成
  python3 scripts/generate_column.py --push    # 生成後にgit pushも行う
  python3 scripts/generate_column.py --dry-run # 生成せずトピック一覧を表示

事前準備:
  1. cp config.example.json config.json
  2. config.json の anthropic_api_key と amazon_associate_id を設定
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SITE_DIR = Path(__file__).parent.parent
CONFIG_FILE = SITE_DIR / "config.json"
TOPICS_FILE = Path(__file__).parent / "column_topics.json"

CATEGORY_COLORS = {
    "データ分析": {"bg": "#fde8e8", "color": "var(--miss)"},
    "馬券戦略":   {"bg": "#e8f5e9", "color": "var(--hit)"},
    "AI解説":     {"bg": "#e8eaf6", "color": "#3949ab"},
}

MONTHS_JA = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        print("[エラー] config.json が見つかりません。")
        print("  cp config.example.json config.json  を実行して設定してください。")
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def load_topics() -> dict:
    with open(TOPICS_FILE) as f:
        return json.load(f)


def save_topics(data: dict):
    with open(TOPICS_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def next_pending_topic(topics_data: dict) -> dict | None:
    for t in topics_data["topics"]:
        if t["status"] == "pending":
            return t
    return None


def generate_article_body(topic: dict, config: dict, client) -> str:
    """Claude APIを呼び出して記事本文HTMLを生成する。"""
    category = topic["category"]
    title = topic["title"]
    description = topic["description"]

    prompt = f"""あなたは競馬データ分析サイト「DarkHorse AI」のライターです。
以下のトピックについて、**SEOを意識した読み応えのある日本語コラム記事**のHTMLを生成してください。

## 記事情報
- カテゴリ: {category}
- タイトル: {title}
- 内容の概要: {description}

## 出力形式の要件
- `<h2>` で3〜5つのセクションを作る
- 各セクションは `<p>` タグで本文（3〜5文程度）
- 必要に応じて `<ul>` や `<div class="point-box">` を使う
- `<div class="point-box">` の使い方: `<div class="point-box"><strong>見出し</strong><p>内容</p></div>`
- データ・数値を盛り込み説得力を持たせる（架空でも統計的に自然な数値でよい）
- 文体は「です・ます調」、読者はデータ分析に興味がある競馬ファン
- **<h1>や<header>/<footer>/<main>などの外枠タグは不要**
- 出力は記事本文のHTMLのみ（説明文なし、コードブロックなし）

## 禁止事項
- 「〇〇を買ってください」「〇〇が必勝法です」などの断定的推奨
- 未検証の断定（「必ず」「100%」など）
- 競馬以外の話題への脱線

最後に以下のテキストをそのまま末尾に追加してください:
<p style="font-size:.85rem;color:var(--muted);margin-top:32px;padding-top:16px;border-top:1px solid var(--border);">
  ※本記事はDarkHorse AIのデータ分析に基づく参考情報です。馬券の購入は自己責任でお願いします。<a href="disclaimer.html">免責事項</a>
</p>"""

    message = client.messages.create(
        model=config["column_generation"]["model"],
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()


def build_book_html(books: list, associate_id: str) -> str:
    """アフィリエイト書籍セクションのHTMLを生成する。"""
    items = ""
    for book in books:
        url = f"https://www.amazon.co.jp/dp/{book['asin']}?tag={associate_id}"
        items += f"""      <a class="book-card" href="{url}" target="_blank" rel="noopener sponsored">
        <div class="book-cover">{book['emoji']}</div>
        <div class="book-info">
          <div class="book-title">{book['title']}</div>
          <div class="book-author">{book['author']}</div>
          <div class="book-desc">{book['desc']}</div>
          <span class="book-btn">Amazonで見る →</span>
        </div>
      </a>\n"""
    return f"""      <!-- 関連書籍（Amazonアフィリエイト） -->
      <div class="affiliate-books">
        <h3>📚 関連書籍 <span class="pr-badge">PR / Amazon</span></h3>
{items}        <p style="font-size:.72rem;color:var(--muted);margin-top:12px;">※Amazonアソシエイト・プログラムに基づく広告を含みます。</p>
      </div>\n"""


def build_share_buttons(col_id: str, title: str, base_url: str) -> str:
    encoded_title = title.replace(" ", "%20").replace("？", "%EF%BC%9F").replace("：", "%EF%BC%9A")
    file_name = f"column-{col_id}.html"
    page_url = f"{base_url}/{file_name}"
    return f"""      <div class="share-buttons">
        <span class="share-label">この記事をシェア：</span>
        <a class="share-btn share-btn-x" href="https://x.com/intent/tweet?text={encoded_title}%20%7C%20DarkHorse%20AI&url={page_url}" target="_blank" rel="noopener">𝕏 でシェア</a>
        <a class="share-btn share-btn-line" href="https://social-plugins.line.me/lineit/share?url={page_url}" target="_blank" rel="noopener">LINE でシェア</a>
        <button class="share-btn share-btn-copy" onclick="navigator.clipboard.writeText(location.href).then(()=>{{this.textContent='コピーしました！';setTimeout(()=>{{this.textContent='URLをコピー'}},2000)}})">URLをコピー</button>
      </div>\n"""


def build_related_articles(all_topics: list, current_id: str, current_category: str) -> str:
    """現在記事と異なるカテゴリを優先して関連記事3件を選ぶ。"""
    done = [t for t in all_topics if t["status"] == "done" and t["id"] != current_id]
    # 異なるカテゴリ優先でソート
    done.sort(key=lambda t: (t["category"] == current_category, t["id"]))
    selected = done[:3]
    if not selected:
        return ""

    cat_colors = CATEGORY_COLORS
    items = ""
    for t in selected:
        col = cat_colors.get(t["category"], {"color": "var(--muted)"})["color"]
        items += f"""          <li>
            <span class="rel-tag">{t['category']}</span>
            <a href="column-{t['id']}.html">{t['title']}</a>
          </li>\n"""
    return f"""      <div class="related-articles">
        <div class="rel-title">関連記事</div>
        <ul>
{items}        </ul>
      </div>\n"""


COMMON_JS = """<script>
  // ① 現在ページのナビリンクをアクティブ表示
  (function() {
    const page = location.pathname.split('/').pop() || 'index.html';
    document.querySelectorAll('nav a, .mobile-nav a').forEach(a => {
      if (a.getAttribute('href') === page) a.setAttribute('aria-current', 'page');
    });
  })();

  // ② ハンバーガーメニュー開放時に背景スクロールを無効化
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

  // ③ ページトップへ戻るボタン
  (function() {
    const btn = document.getElementById('back-to-top');
    if (!btn) return;
    window.addEventListener('scroll', () => {
      btn.classList.toggle('visible', window.scrollY > 300);
    }, { passive: true });
    btn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  })();
</script>"""


def build_full_html(topic: dict, article_body: str, col_id: str, config: dict) -> str:
    """完全なHTMLページを組み立てる。"""
    title = topic["title"]
    category = topic["category"]
    associate_id = config["amazon_associate_id"]
    base_url = config["site_base_url"]

    now = datetime.now()
    date_str = f"{now.year}年{MONTHS_JA[now.month - 1]}"

    cat_style = CATEGORY_COLORS.get(category, {"bg": "#f0f4f8", "color": "var(--muted)"})
    cat_bg = cat_style["bg"]
    cat_color = cat_style["color"]

    book_html = build_book_html(topic["books"], associate_id)
    share_html = build_share_buttons(col_id, title, base_url)
    # 関連記事は生成後にstatus=doneにしてから呼ぶので、ここでは空にしておく
    related_html = ""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} | DarkHorse AI コラム</title>
  <meta name="description" content="{topic['description'][:120]}">
  <meta property="og:title" content="{title} | DarkHorse AI">
  <meta property="og:type" content="article">
  <link rel="stylesheet" href="css/style.css">
  <style>
    .article-body {{ max-width: 720px; }}
    .article-body h2 {{ font-size: 1.2rem; color: var(--primary); border-bottom: 2px solid var(--accent); padding-bottom: 6px; margin: 32px 0 14px; }}
    .article-body p {{ margin-bottom: 14px; line-height: 1.8; }}
    .article-body ul, .article-body ol {{ margin: 10px 0 16px 20px; line-height: 2; }}
    .point-box {{ background: #f0f4f8; border-left: 4px solid var(--accent); padding: 16px 20px; border-radius: 4px; margin: 20px 0; }}
    .point-box strong {{ display: block; margin-bottom: 6px; font-size: 1rem; }}
    .data-highlight {{ background: var(--primary); color: #fff; display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: .9rem; font-weight: bold; }}
  </style>
  <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-4265350416312017"
     crossorigin="anonymous">
  </script>
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

      <p style="font-size:.85rem;color:var(--muted);margin-bottom:8px;"><a href="column.html">コラム</a> &gt; {category}</p>
      <div style="display:inline-block;background:{cat_bg};color:{cat_color};font-size:.8rem;padding:2px 10px;border-radius:10px;margin-bottom:12px;">{category}</div>
      <h1 style="font-size:1.6rem;color:var(--primary);margin-bottom:8px;line-height:1.4;">
        {title}
      </h1>
      <p style="color:var(--muted);font-size:.85rem;margin-bottom:24px;">{date_str} | DarkHorse AI編集部</p>

{article_body}

{book_html}
{share_html}
{related_html}
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
</html>
"""


def update_column_index(topic: dict, col_id: str):
    """column.html の記事一覧に新しいカードを追加する。"""
    col_html = SITE_DIR / "column.html"
    content = col_html.read_text()

    category = topic["category"]
    title = topic["title"]
    description = topic["description"]

    now = datetime.now()
    date_str = f"{now.year}年{MONTHS_JA[now.month - 1]}"

    cat_style = CATEGORY_COLORS.get(category, {"bg": "#f0f4f8", "color": "var(--muted)"})
    cat_bg = cat_style["bg"]
    cat_color = cat_style["color"]

    new_card = f"""
    <a href="column-{col_id}.html" data-category="{category}" class="col-card-wrap" style="display:block;text-decoration:none;color:inherit;">
      <div class="column-card">
        <div style="display:flex;align-items:flex-start;gap:16px;">
          <div style="flex:1;">
            <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;">
              <span style="display:inline-block;background:{cat_bg};color:{cat_color};font-size:.75rem;padding:2px 8px;border-radius:10px;">{category}</span>
              <span style="font-size:.78rem;color:var(--muted);">{date_str}</span>
            </div>
            <h3 style="font-size:1.05rem;color:var(--primary);margin-bottom:6px;line-height:1.5;">{title}</h3>
            <p style="font-size:.85rem;color:var(--muted);line-height:1.6;">{description[:80]}{"..." if len(description) > 80 else ""}</p>
          </div>
        </div>
      </div>
    </a>
"""
    # 最後の </a> タグ（記事カード）の後に追加
    insert_marker = "  </div>\n</main>"
    new_content = content.replace(insert_marker, new_card + insert_marker, 1)
    col_html.write_text(new_content)
    print(f"column.html に記事カードを追加しました: column-{col_id}.html")


def apply_associate_id(config: dict):
    """全HTMLファイルのアフィリエイトIDプレースホルダーを config の値に置き換える。"""
    associate_id = config["amazon_associate_id"]
    if associate_id == "your-associate-id-22":
        print("[警告] config.json の amazon_associate_id がデフォルト値のままです。")
        return

    pattern = re.compile(r'\?tag=([a-zA-Z0-9\-]+)-22')
    updated = 0
    for html_file in SITE_DIR.glob("*.html"):
        text = html_file.read_text()
        new_text = pattern.sub(f"?tag={associate_id}-22", text)
        if new_text != text:
            html_file.write_text(new_text)
            updated += 1
    if updated:
        print(f"アフィリエイトID適用: {updated}ファイルを更新しました (ID: {associate_id})")


def git_push(message: str):
    try:
        subprocess.run(["git", "-C", str(SITE_DIR), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(SITE_DIR), "commit", "-m", message], check=True)
        subprocess.run(["git", "-C", str(SITE_DIR), "push", "origin", "main"], check=True)
        print("GitHub にプッシュしました。")
    except subprocess.CalledProcessError as e:
        print(f"[エラー] git操作に失敗しました: {e}")


def main():
    parser = argparse.ArgumentParser(description="DarkHorse AI コラム自動生成")
    parser.add_argument("--push", action="store_true", help="生成後にgit pushする")
    parser.add_argument("--dry-run", action="store_true", help="トピック一覧を表示してAPIは呼ばない")
    parser.add_argument("--apply-id", action="store_true", help="全HTMLのアフィリエイトIDを更新するだけ")
    args = parser.parse_args()

    config = load_config()
    topics_data = load_topics()

    # アフィリエイトID更新のみモード
    if args.apply_id:
        apply_associate_id(config)
        if args.push:
            git_push("fix: Amazonアソシエイト ID を適用")
        return

    # dry-run: トピック一覧表示
    if args.dry_run:
        print("=== トピック一覧 ===")
        for t in topics_data["topics"]:
            mark = "[完了]" if t["status"] == "done" else "[待機]"
            print(f"  {mark} {t['id']}: {t['title']}")
        return

    # Claude API チェック
    api_key = config.get("anthropic_api_key", "")
    if not api_key or api_key.startswith("sk-ant-ここに"):
        print("[エラー] config.json の anthropic_api_key が設定されていません。")
        print("  config.json を開いて anthropic_api_key に実際のキーを入力してください。")
        sys.exit(1)

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    topic = next_pending_topic(topics_data)
    if not topic:
        print("生成できるトピックがありません。column_topics.json に新しいトピックを追加してください。")
        sys.exit(0)

    col_id = topic["id"]
    output_file = SITE_DIR / f"column-{col_id}.html"

    print(f"記事を生成します: [{topic['category']}] {topic['title']}")
    print("Claude API を呼び出し中...")

    article_body = generate_article_body(topic, config, client)

    # HTMLを組み立て
    html = build_full_html(topic, article_body, col_id, config)
    output_file.write_text(html)
    print(f"生成完了: {output_file.name}")

    # トピックステータスを done に更新
    for t in topics_data["topics"]:
        if t["id"] == col_id:
            t["status"] = "done"
            break
    save_topics(topics_data)

    # column.html の一覧に追加
    update_column_index(topic, col_id)

    # アフィリエイトID適用
    apply_associate_id(config)

    # git push
    if args.push or config.get("auto_push_after_generate"):
        git_push(f"feat: コラム記事追加 column-{col_id} [{topic['category']}] {topic['title']}")

    print("\n完了しました。")
    print(f"  ファイル: column-{col_id}.html")
    print(f"  次回: python3 scripts/generate_column.py --push")


if __name__ == "__main__":
    main()
