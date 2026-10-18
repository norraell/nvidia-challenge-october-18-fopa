# Set up Super VL

Each teammate uses their own Nebius Token Factory account and API key.
Do not share keys.
This takes about 5 minutes.

## 1. Get your key

1. Sign in at [Token Factory](https://tokenfactory.nebius.com/).
2. Redeem your event promo code. Check that your balance shows credit.
3. Create an API key. Copy it now. The site shows it only once.

## 2. Add the key to `.env`

Work in your WSL clone of this repository.

```sh
cd ~/nvidia-challenge-october-18-fopa
cp -n .env.example .env
nano .env
```

Set this one line and save:

```dotenv
SUPER_API_KEY=your-key-here
```

Keep `SUPER_BASE_URL` and `SUPER_MODEL` as they are.

Put the key only in `.env`. Git ignores that file.
Never put the key in `.env.example`, code, chat, or screenshots. Git tracks `.env.example`.

The Token Factory quickstart names the variable `NEBIUS_API_KEY`.
This project reads `SUPER_API_KEY` instead. Hermes reads the same variable.

## 3. Check your access

```sh
uv run python scripts/check_super.py
```

A working key prints:

```text
PASS    catalog
PASS    text  -> 'READY'
PASS    tool_call
PASS    vision  -> 'SHIP-BUILDING'
4/4 checks passed. Receipt: runs/super-check-<time>.json
```

| Check | What it proves |
| --- | --- |
| `catalog` | Your key works and your account can use Super VL. |
| `text` | The model returns a complete text answer. |
| `tool_call` | The model calls a tool. Hermes needs this. |
| `vision` | The model reads a Britannica scan. Run `uv run nemotron-challenge data fetch` first, or add `--skip-vision`. |

The receipt in `runs/` records model IDs, token use, and short answers. It never contains your key.

If a check fails, read its message:

| Message | Action |
| --- | --- |
| `SUPER_API_KEY is empty` | Add the key to `.env` in the repository root. |
| `rejected the key (HTTP 401)` | Copy the key again. Check for extra spaces or quotes. |
| `no credit (HTTP 402)` | Redeem your promo code. |
| `not in this account's model catalog` | Ask an organizer to enable Super VL. |
| `rate limit (HTTP 429)` | Wait one minute. Run the check again. |
| `reply was cut off` | Tell the team. The token budget is too small. |

## Call Super VL from your code

Use `ChatClient` from `src/nemotron_challenge/clients.py`.
It checks the model ID, the finish reason, and the tool call format for you.

```python
from nemotron_challenge.clients import ChatClient
from nemotron_challenge.config import Settings

settings = Settings.from_env()
with ChatClient(settings.super_base_url, settings.super_api_key, settings.super_model) as client:
    reply = client.complete([{"role": "user", "content": "Your question"}], max_tokens=4096)
print(reply["choices"][0]["message"]["content"])
```

Set `max_tokens` to 4096 or more.
Super VL reasons before it answers, and reasoning tokens count toward `max_tokens` and your credits.
One question about a scan used 940 to 1,391 reasoning tokens.
With a smaller budget the answer can stop early, and `ChatClient` raises `ProtocolError`.

A scan question can return a running page header, such as `SHIP-BUILDING`, instead of an entry headword.
Check answers against the scan.
