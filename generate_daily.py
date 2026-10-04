import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

JST = ZoneInfo("Asia/Tokyo")
ROOT = Path(__file__).resolve().parent
HISTORY_PATH = ROOT / "history.json"
PAYLOAD_PATH = ROOT / "daily_payload.json"
MEDIA_ROOT = ROOT / "generated_media"

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
TEXT_MODEL = os.getenv("OPENAI_TEXT_MODEL", "gpt-5.6-luna")

SLOTS = [
    ("quick_reply", "text", "07:00"),
    ("ng_ok", "image", "09:30"),
    ("question", "text", "12:00"),
    ("three_steps", "image", "15:00"),
    ("work_aruaru", "text", "18:00"),
    ("save_card", "image", "20:30"),
    ("note", "note", "22:00"),
]


def load_history():
    if not HISTORY_PATH.exists():
        return {"items": []}
    return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))


def extract_json(text: str):
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("No JSON found in model output")
    return json.loads(text[start:end + 1])


def research_and_generate(today: str, recent):
    prompt = f'''
あなたはXアカウント「あと10分で解決。」の編集長です。
今日の日付は {today}（日本時間）。

目的:
会社・仕事で「今この瞬間どう返す？どう動く？」という悩みに対し、
短く、具体的で、保存・返信したくなる投稿を毎日7本作る。

公開Webを検索し、X / Threads / Instagram / LinkedIn等で反応されやすい
投稿の型・フック・問いかけ・保存カードの見せ方を参考にしてください。
他人の文章はコピーせず、構造だけ参考にしてください。

テーマ方針:
- 会社・仕事の困りごとを中心にする
- 退職、有給、上司への相談、仕事の断り方、優先順位、残業、ミス報告、面接、希望年収、催促など
- 「今すぐ使える一言」「その場での対処」を優先
- 抽象論・精神論・一般論だけの投稿は避ける
- AIっぽい整いすぎた言い回しを避ける
- 直近投稿と同じテーマやほぼ同じ文面を避ける

直近投稿:
{json.dumps(recent[-100:], ensure_ascii=False)}

7枠を必ずこの順番で作成:
1 quick_reply: 07:00 テキスト。「今すぐ使える一言」
2 ng_ok: 09:30 画像付き。NG→OK比較
3 question: 12:00 テキスト。読者参加型。「あなたならどうする？」等
4 three_steps: 15:00 画像付き。3ステップ解決
5 work_aruaru: 18:00 テキスト。仕事あるある→対処
6 save_card: 20:30 画像付き。保存したくなる言い回し/確認項目まとめ
7 note: 22:00 note誘導。悩み→結論の一部→続きを読む理由。URL自体は書かない

本文ルール:
- 1投稿 180文字以内を目安にする。
絶対に220文字を超えない。
- ハッシュタグは0〜2個。毎投稿必須ではない
- 画像付き3枠も、画像だけでなく短い本文を付ける
- note投稿以外に外部リンクを入れない
- note投稿本文にもURLを書かない（プログラム側で必ず付ける）

画像カード用ルール:
- image_title: 画像上部の短いタイトル
- image_lines: スマホで読める短文を3〜6行
- NG→OKの場合は「NG:」「OK:」が分かるようにする
- 3ステップの場合は「1.」「2.」「3.」が分かるようにする
- save_cardは3〜5項目程度

説明なしでJSONだけ返してください:
{{
  "items": [
    {{"slot":"quick_reply","kind":"text","topic":"","post_text":"","image_title":"","image_lines":[]}},
    {{"slot":"ng_ok","kind":"image","topic":"","post_text":"","image_title":"","image_lines":[]}},
    {{"slot":"question","kind":"text","topic":"","post_text":"","image_title":"","image_lines":[]}},
    {{"slot":"three_steps","kind":"image","topic":"","post_text":"","image_title":"","image_lines":[]}},
    {{"slot":"work_aruaru","kind":"text","topic":"","post_text":"","image_title":"","image_lines":[]}},
    {{"slot":"save_card","kind":"image","topic":"","post_text":"","image_title":"","image_lines":[]}},
    {{"slot":"note","kind":"note","topic":"","post_text":"","image_title":"","image_lines":[]}}
  ]
}}
'''
    r = client.responses.create(
        model=TEXT_MODEL,
        reasoning={"effort": "low"},
        tools=[{"type": "web_search"}],
        tool_choice="required",
        input=prompt,
    )
    return extract_json(r.output_text)


def font_path():
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    raise RuntimeError("No usable font found")


def wrap_japanese(draw, text, font, max_width):
    lines = []
    current = ""
    for ch in str(text):
        test = current + ch
        if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def generate_card(item, outpath):
    width, height = 1200, 675
    img = Image.new("RGB", (width, height), "#F8F6F1")
    draw = ImageDraw.Draw(img)
    fp = font_path()
    title_font = ImageFont.truetype(fp, 58)
    body_font = ImageFont.truetype(fp, 38)
    brand_font = ImageFont.truetype(fp, 24)

    draw.rounded_rectangle(
        (55, 45, 1145, 630),
        radius=34,
        fill="#FFFFFF",
        outline="#D9D5CC",
        width=3,
    )
    draw.text((85, 72), "あと10分で解決。", font=brand_font, fill="#5D5A53")

    title = item.get("image_title") or item.get("topic") or "今すぐ使える"
    title_lines = wrap_japanese(draw, title, title_font, 1000)[:2]

    y = 125
    for line in title_lines:
        draw.text((85, y), line, font=title_font, fill="#222222")
        y += 72

    y += 20

    body_lines = []
    for raw in item.get("image_lines") or []:
        wrapped = wrap_japanese(draw, raw, body_font, 1000)
        body_lines.extend(wrapped)

    body_lines = body_lines[:8]

    for line in body_lines:
        draw.text((95, y), line, font=body_font, fill="#343434")
        y += 55

    draw.text(
        (85, 590),
        "10分で、次の一手を決める。",
        font=brand_font,
        fill="#77736B",
    )

    outpath.parent.mkdir(parents=True, exist_ok=True)
    img.save(outpath, "PNG", optimize=True)


def validate(items):
    expected = [x[0] for x in SLOTS]
    actual = [x.get("slot") for x in items]

    if actual != expected:
        raise ValueError(f"Unexpected slots: {actual}")

    for item in items:
        text = str(item.get("post_text", "")).strip()

        if not text:
            raise ValueError(f"Blank post_text: {item.get('slot')}")

        if item.get("kind") == "image" and not item.get("image_lines"):
            raise ValueError(f"Missing image_lines: {item.get('slot')}")


def main():
    today = datetime.now(JST).date().isoformat()

    history = load_history()

    recent = [
        f'{x.get("date")} | {x.get("slot")} | {x.get("topic")} | {x.get("post_text", "")[:120]}'
        for x in history.get("items", [])
    ]

    data = research_and_generate(today, recent)
    items = data.get("items", [])

    validate(items)

    by_slot = {
        slot: (kind, hhmm)
        for slot, kind, hhmm in SLOTS
    }

    result = []

    for item in items:
        item = dict(item)

        expected_kind, hhmm = by_slot[item["slot"]]

        item["kind"] = expected_kind
        item["time"] = hhmm
        item["generated_date"] = today
        item["image_path"] = ""

        if expected_kind == "image":
            outpath = MEDIA_ROOT / today / f'{item["slot"]}.png'

            generate_card(item, outpath)

            item["image_path"] = str(
                outpath.relative_to(ROOT)
            ).replace("\\", "/")

        result.append(item)

    PAYLOAD_PATH.write_text(
        json.dumps(
            {
                "date": today,
                "items": result,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    hist = history.get("items", [])

    for item in result:
        hist.append(
            {
                "date": today,
                "slot": item["slot"],
                "topic": item.get("topic", ""),
                "post_text": item.get("post_text", ""),
            }
        )

    history["items"] = hist[-210:]

    HISTORY_PATH.write_text(
        json.dumps(
            history,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "date": today,
                "items": result,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
