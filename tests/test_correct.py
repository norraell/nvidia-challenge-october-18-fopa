"""Read, correct, modernize: guardrails, meaning check, caching and outputs, with fake Super VL and Embed VL."""
import json
import math

import httpx
from PIL import Image

from nemotron_challenge.clients import ChatClient, RetrievalClient
from nemotron_challenge.config import EMBED_DIMENSIONS, EMBED_MODEL, EMBED_REVISION, RERANK_MODEL, RERANK_REVISION, SUPER_MODEL
from nemotron_challenge.contracts import EntryRecord
from nemotron_challenge.stages.correct import (
    decide, load_existing, overcorrections, parse_reply, run_corrections, trim_to_span, word_drift_ok,
)
from nemotron_challenge.stages.latex import diff_tex

PAGE_ID = "britannica:x:train:251"


def test_reply_parsing_accepts_plain_and_fenced_json_only():
    assert parse_reply('{"faithful": "a b", "modern": "a b"}') == {"faithful": "a b", "modern": "a b"}
    assert parse_reply('```json\n{"faithful": " x ", "modern": "y"}\n```') == {"faithful": "x", "modern": "y"}
    assert parse_reply("Sure, here it is: faithful text") is None
    assert parse_reply('{"faithful": "only one field"}') is None


def test_guardrails_keep_parse_text_when_a_version_drifts():
    text = "one two three four five six seven eight nine ten"
    assert word_drift_ok(text, text.replace("three", "3"))
    assert not word_drift_ok(text, text + " and four extra words added")
    assert decide(text, {"error": "ServiceError: HTTP 429"})["fallback"].startswith("call failed")
    assert decide(text, {"parsed": None})["fallback"] == "reply was not the expected JSON"
    inserted = "one two three four five plus a whole new invented sentence six seven eight nine ten"
    long = decide(text, {"parsed": {"faithful": inserted, "modern": inserted}})
    assert long["faithful"] == text and long["fallback"] == "faithful version changed the word count too much"
    neighbours = "the line above. " + text.replace("two", "too") + " and the next paragraph starts here"
    trimmed = decide(text, {"parsed": {"faithful": neighbours, "modern": neighbours}})
    assert trimmed["faithful"] == text.replace("two", "too") and trimmed["fallback"] is None
    ok = decide(text, {"parsed": {"faithful": text.replace("two", "too"), "modern": text.replace("two", "2")}})
    assert ok == {"faithful": text.replace("two", "too"), "modern": text.replace("two", "2"), "fallback": None}


def test_trim_keeps_only_the_span_that_matches_parse():
    assert trim_to_span("b c d", "a b c d e") == "b c d"
    assert trim_to_span("x b c d", "a y b c d e") == "y b c d"  # one unmatched leading word on each side is kept
    assert trim_to_span("b c", "q r s") == "q r s"  # nothing matches: leave it to the word-count guardrail


def test_overcorrection_counts_only_words_parse_already_had_right():
    assert overcorrections("Calvinia and Sprayer were", "Calvinifm and Popery were", "Calvinifm and Popery were") == 0
    assert overcorrections("the house was big", "the horse was big", "the house was big") == 1


def test_latex_marks_parse_words_and_corrections():
    tex = diff_tex("Calvinia and Sprayer. Of 50%", "Calvinifm and Popery. Of 50%")
    assert tex == r"\sout{Calvinia} \textbf{Calvinifm} and \sout{Sprayer.} \textbf{Popery.} Of 50\%"


def unit(index):
    vector = [0.0] * EMBED_DIMENSIONS
    vector[index] = 1.0
    return vector


def fake_services(replies, *, same_meaning=True):
    chat_calls, embed_calls = [], []

    def handle(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [
                {"id": SUPER_MODEL}, {"id": EMBED_MODEL, "revision": EMBED_REVISION, "dimensions": EMBED_DIMENSIONS},
                {"id": RERANK_MODEL, "revision": RERANK_REVISION}]})
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            embed_calls.append(body["input"])
            vectors = [unit(0) if same_meaning or i % 2 == 0 else unit(1) for i in range(len(body["input"]))]
            return httpx.Response(200, json={"model": EMBED_MODEL, "model_revision": EMBED_REVISION,
                                             "data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]})
        chat_calls.append(body)
        assert body["chat_template_kwargs"] == {"enable_thinking": False}
        assert body["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
        text = body["messages"][0]["content"][0]["text"].rsplit("TEXT:\n", 1)[1]
        return httpx.Response(200, json={"model": SUPER_MODEL, "choices": [
            {"finish_reason": "stop", "message": {"content": replies[text]}}]})

    return httpx.Client(transport=httpx.MockTransport(handle)), chat_calls, embed_calls


def page_setup(tmp_path):
    scan_dir = tmp_path / "scans"
    scan_dir.mkdir()
    image = Image.new("L", (600, 826), 230)
    image.paste(20, (60, 100, 280, 300))
    image.save(scan_dir / "page-0251-a.jpg", format="JPEG")
    page = {"page_id": PAGE_ID, "row_index": 251, "status": "ok", "width": 600, "height": 826,
            "filename": "page-0251-a.jpg", "entry_ids": ["e0251-01"]}
    parse_text = "The two religions are Calvinia and Sprayer of the cantons"
    entry = {"entry_id": "e0251-01", "kind": "continuation", "headword": None, "text": parse_text + " Fig. 2",
             "text_raw": "Practical\n\n" + parse_text + "\n\nFig. 2", "crop_path": "artifacts/extract/crops/e0251-01.png",
             "continues_from": None, "continues_to": None, "quality": {"ocr_suspect_ratio": 0.0, "low_quality": False},
             "blocks": [
                 {"page_id": PAGE_ID, "bbox": [36.0, 50.0, 75.0, 90.0], "cls": "Section-header", "text": "Practical"},
                 {"page_id": PAGE_ID, "bbox": [60.0, 100.0, 280.0, 300.0], "cls": "Text", "text": parse_text},
                 {"page_id": PAGE_ID, "bbox": [60.0, 310.0, 280.0, 330.0], "cls": "Text", "text": "Fig. 2"},
             ]}
    replies = {parse_text: json.dumps({"faithful": "The two religions are Calvinifm and Popery of the cantons",
                                       "modern": "The two religions are Calvinism and Popery of the cantons"})}
    gold_dir = tmp_path / "out" / "gold"
    gold_dir.mkdir(parents=True)
    (gold_dir / "0251.txt").write_text("The two religions are Calvinifm and Popery of the cantons", encoding="utf-8")
    return scan_dir, page, entry, replies


def test_run_writes_three_layers_scores_gold_and_reuses_cache(tmp_path):
    scan_dir, page, entry, replies = page_setup(tmp_path)
    out = tmp_path / "out"
    http, chat_calls, embed_calls = fake_services(replies)
    with http:
        chat = ChatClient("https://chat.example/v1", "key", client=http)
        retrieval = RetrievalClient("https://retrieval.example/v1", "key", client=http)
        report = run_corrections([page], [entry], scan_dir, out, chat, retrieval)
        run_corrections([page], [entry], scan_dir, out, chat, retrieval)  # second run: cached replies

    assert len(chat_calls) == 1  # margin note and the 2-word block are not sent; the rerun is cached
    row = load_existing(out)["e0251-01"]
    assert row["faithful"] == "The two religions are Calvinifm and Popery of the cantons Fig. 2"
    assert row["modern"] == "The two religions are Calvinism and Popery of the cantons Fig. 2"
    assert ["Calvinia", "Calvinifm"] in row["faithful_changes"] and ["Sprayer", "Popery"] in row["faithful_changes"]
    modern = EntryRecord.model_validate_json((out / "entries.modern.jsonl").read_text(encoding="utf-8").strip())
    assert modern.text == row["modern"] and modern.text_raw == entry["text_raw"]
    assert report["gold"][0]["cer_faithful"] == 0.0 and report["gold"][0]["cer_parse"] > 0
    assert report["gold"][0]["overcorrected_words"] == 0
    assert report["meaning_check"]["pairs"] == 1 and report["meaning_check"]["below_threshold"] == 0
    assert embed_calls  # the meaning check ran on the faithful/modern pair


def test_failed_meaning_check_keeps_the_faithful_text(tmp_path):
    scan_dir, page, entry, replies = page_setup(tmp_path)
    http, _, _ = fake_services(replies, same_meaning=False)
    with http:
        report = run_corrections([page], [entry], scan_dir, tmp_path / "out",
                                 ChatClient("https://chat.example/v1", "key", client=http),
                                 RetrievalClient("https://retrieval.example/v1", "key", client=http))
    row = load_existing(tmp_path / "out")["e0251-01"]
    assert row["modern"] == row["faithful"] and report["meaning_check"]["below_threshold"] == 1
    assert report["fallback_reasons"] == {"meaning check failed": 1}
    assert math.isclose(report["meaning_check"]["min"], 0.0)


def test_without_embed_vl_the_modern_layer_is_not_trusted(tmp_path):
    scan_dir, page, entry, replies = page_setup(tmp_path)
    http, _, _ = fake_services(replies)
    with http:
        report = run_corrections([page], [entry], scan_dir, tmp_path / "out",
                                 ChatClient("https://chat.example/v1", "key", client=http), None)
    row = load_existing(tmp_path / "out")["e0251-01"]
    assert row["modern"] == row["faithful"] and report["fallback_reasons"] == {"no meaning check": 1}
