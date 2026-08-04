#!/usr/bin/env python3
"""日次求人レポートの要点を Discord Webhook に投稿する。

notify-discord.yml から呼ばれる。標準ライブラリのみで動く。

Discord の embed description は 4096 文字上限だが、実際に読みやすいのは
それよりずっと短いので、本文は要約＋「要検討」の見出しだけに絞り、
詳細はリポジトリ上のファイルへのリンクで飛ばす。
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

# Discord の embed description 上限は 4096。余裕を持たせる。
MAX_DESCRIPTION = 3500
# 「要検討」から拾う求人の最大件数。これ以上はリンクで見てもらう。
MAX_JOBS_IN_EMBED = 5

COLOR_HAS_JOBS = 0x2ECC71   # 緑: 要検討あり
COLOR_NO_JOBS = 0x95A5A6    # 灰: 新着なし


def read_report(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def extract_section(text, heading):
    """`## {heading}` から次の `## ` までを返す。見つからなければ空文字。

    セクション末尾の `---`（見出し前の区切り線）は Discord では
    ただのノイズなので落とす。
    """
    pattern = rf"^##\s+{re.escape(heading)}\s*$(.*?)(?=^##\s|\Z)"
    m = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if not m:
        return ""
    return re.sub(r"\n-{3,}\s*$", "", m.group(1).strip()).strip()


def extract_job_titles(section):
    """「要検討」セクションから `### N. [タイトル](URL)` を拾う。"""
    jobs = []
    for m in re.finditer(r"^###\s+\d+\.\s+\[([^\]]+)\]\(([^)]+)\)", section, re.MULTILINE):
        jobs.append((m.group(1).strip(), m.group(2).strip()))
    return jobs


def extract_score(section, title):
    """該当求人ブロックから総合点を拾う。見つからなければ None。"""
    idx = section.find(title)
    if idx == -1:
        return None
    block = section[idx: idx + 1500]
    m = re.search(r"\*\*総合\*\*\s*\|\s*\*\*([\d.]+)\*\*", block)
    return m.group(1) if m else None


def truncate(text, limit):
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n…（以下略）"


def build_payload(report_path, text, repo, sha):
    date = os.path.basename(report_path).removesuffix(".md")
    file_url = f"https://github.com/{repo}/blob/{sha}/{report_path}"

    summary = extract_section(text, "サマリー")
    considering = extract_section(text, "要検討")
    jobs = extract_job_titles(considering)

    parts = []
    if summary:
        parts.append(truncate(summary, 1200))

    if jobs:
        parts.append("\n**要検討**")
        for i, (title, url) in enumerate(jobs[:MAX_JOBS_IN_EMBED], 1):
            score = extract_score(considering, title)
            suffix = f"（総合 {score}）" if score else ""
            parts.append(f"{i}. [{title}]({url}) {suffix}".rstrip())
        if len(jobs) > MAX_JOBS_IN_EMBED:
            parts.append(f"…ほか {len(jobs) - MAX_JOBS_IN_EMBED} 件")
    else:
        parts.append("\n新着の「要検討」求人はありません。")

    description = truncate("\n".join(parts), MAX_DESCRIPTION)

    return {
        "username": "転職リサーチ",
        "embeds": [
            {
                "title": f"求人レポート {date}",
                "url": file_url,
                "description": description,
                "color": COLOR_HAS_JOBS if jobs else COLOR_NO_JOBS,
                "footer": {"text": "詳細はレポート本文（タイトルをクリック）"},
            }
        ],
    }


def post(webhook_url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "changing-jobs-notifier"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status


def main():
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    report_path = os.environ.get("REPORT_PATH")
    repo = os.environ.get("REPO", "")
    sha = os.environ.get("SHA", "main")

    if not webhook_url:
        print("DISCORD_WEBHOOK_URL が未設定のためスキップします。", file=sys.stderr)
        return 0
    if not report_path or not os.path.isfile(report_path):
        print(f"レポートが見つかりません: {report_path}", file=sys.stderr)
        return 1

    payload = build_payload(report_path, read_report(report_path), repo, sha)

    try:
        status = post(webhook_url, payload)
    except urllib.error.HTTPError as e:
        # Webhook URL 自体は秘匿情報なので、本文だけ出してURLは出さない。
        print(f"Discord への投稿に失敗しました: HTTP {e.code} {e.read().decode(errors='replace')}",
              file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"Discord への接続に失敗しました: {e.reason}", file=sys.stderr)
        return 1

    print(f"Discord に投稿しました (HTTP {status})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
