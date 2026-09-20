```
    ███╗   ██╗██╗ ██████╗ ██╗  ██╗████████╗ █████╗ ██╗     ██╗
    ████╗  ██║██║██╔════╝ ██║  ██║╚══██╔══╝██╔══██╗██║     ██║
    ██╔██╗ ██║██║██║  ███╗███████║   ██║   ███████║██║     ██║
    ██║╚██╗██║██║██║   ██║██╔══██║   ██║   ██╔══██║██║     ██║
    ██║ ╚████║██║╚██████╔╝██║  ██║   ██║   ██║  ██║███████╗██║
    ╚═╝  ╚═══╝╚═╝ ╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝
                         LOAD TESTER
```

# NIGHTFALL // LOAD TESTER

A polished, terminal-based **HTTP load / stress testing console** with a
cybersecurity aesthetic, built on `asyncio` + `aiohttp` + `Rich`.

NIGHTFALL simulates many concurrent website visitors so you can observe how a
target you own behaves under increasing traffic — with a live dashboard,
ramp-up, a global rate limiter, latency percentiles, status-code and error
breakdowns, and JSON / CSV / TXT export.

---

## ⚠️ AUTHORIZATION WARNING — READ FIRST

> **This tool is intended ONLY for websites that you own or have explicit,
> written authorization to test.**
>
> Unauthorized load or stress testing of systems you do not control may be
> **illegal** and can cause real service disruption. You are solely responsible
> for how you use this tool. NIGHTFALL displays an authorization confirmation
> before **every** test and requires you to explicitly confirm.

NIGHTFALL is a **legitimate performance-testing tool**. It deliberately does
**NOT** implement, and will not be extended to implement:

- IP spoofing • proxy rotation • botnet / distributed-attack functionality
- credential attacks (brute force / spraying / login testing)
- CAPTCHA bypass • WAF bypass • rate-limit evasion
- stealth / evasion / anti-detection techniques

Its only purpose is measuring the performance of an authorized target.

---

## Features

- Hacker-style Rich terminal UI with an interactive control menu
- Authorization confirmation before every test
- Target URL validation (scheme, host, port, path; localhost & IPs allowed)
- Configurable concurrent users, duration, ramp-up, RPS limit, timeouts
- Conservative safe defaults; hard safety ceiling of **5,000** concurrent users
- `GET`, `HEAD`, `POST` (with manual JSON body) + custom headers
- `asyncio` worker pool with a bounded task set and an `asyncio.Semaphore`
- Gradual ramp-up so traffic is introduced smoothly
- Global token-bucket **rate limiter** to cap aggregate requests/sec
- Live dashboard: RPS graph, rolling latency graph, status breakdown, error
  monitor, and a rolling recent-activity feed (refreshes ~8×/sec)
- Pause **[P]** / Resume **[R]** / Stop **[S]** controls; graceful shutdown
- Latency stats: min, avg, P50, P90, P95, P99, max (bounded memory)
- Neutral, factual observations (no "your site can handle N users" claims)
- Export to JSON / CSV / TXT (sensitive data never written to disk)
- Interactive **and** command-line modes

---

## Installation

Requires **Python 3.13+** (works on 3.11+).

```bash
git clone https://github.com/G33l0/nightfall.git
cd nightfall

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### Termux (Android)

No root required.

```bash
pkg update
pkg install python
pip install -r requirements.txt
python nightfall.py
```

Works in Windows Terminal, PowerShell, Linux, macOS Terminal and Termux.

---

## Usage

### Interactive mode (default)

```bash
python nightfall.py
```

You are greeted by the NIGHTFALL banner and the control menu:

```
┌─────────────────────────────────────────────┐
│             NIGHTFALL CONTROL               │
├─────────────────────────────────────────────┤
│ [1] Configure Target                        │
│ [2] Configure Load                          │
│ [3] Configure Test Duration                 │
│ [4] Configure Ramp-Up                       │
│ [5] Configure Request Method                │
│ [6] Configure Headers                       │
│ [7] Run Load Test                           │
│ [8] Live Traffic Monitor                    │
│ [9] View Last Test Results                  │
│ [10] Export Results                         │
│ [0] Exit                                    │
└─────────────────────────────────────────────┘
```

Nothing runs automatically — you configure, then choose **[7]** or **[8]**,
confirm authorization, and watch the live dashboard.

### Command-line mode

```bash
python nightfall.py --url https://you.example.com
```

Optional arguments:

| Flag | Meaning |
|------|---------|
| `--users N` | Concurrent simulated users (max 5,000) |
| `--duration S` | Test duration in seconds |
| `--ramp-up S` | Ramp-up period in seconds |
| `--rps N` | Aggregate requests/sec limit (`0` = unlimited) |
| `--method {GET,HEAD,POST}` | HTTP method |
| `--body '{"k":"v"}'` | JSON body for POST |
| `--header 'Name: Value'` | Custom header (repeatable) |
| `--timeout S` | Request timeout |
| `--connect-timeout S` | Connection timeout |
| `--proxy URL` | Route through a single explicit proxy you supply (e.g. `http://user:pass@host:port`) |
| `--requests-per-user N` | Requests per user (`0` = unlimited) |
| `--export [all\|json\|csv\|txt]` | Export after the run |
| `--yes`, `-y` | Affirm authorization non-interactively |
| `--no-live` | Disable the live dashboard (for logs / CI) |

Example:

```bash
python nightfall.py --url https://you.example.com \
    --users 50 --duration 120 --ramp-up 20 --rps 50 \
    --method GET --export all
```

Interactive mode remains the default whenever `--url` is omitted.

---

## Test Profiles

Presets are available under **[2] Configure Load**. They are fully
configurable starting points and must only be run against authorized systems.

| Profile | Users | Duration | RPS |
|---------|------:|---------:|----:|
| Smoke Test | 5 | 30 s | 5 |
| Light Load | 25 | 60 s | 25 |
| Moderate Load | 50 | 120 s | 50 |
| Heavy Load | 100 | 120 s | 100 |
| Custom | — | — | — |

### Safe defaults

Concurrent users **10**, duration **30 s**, ramp-up **10 s**, RPS **10**.
NIGHTFALL never defaults to high traffic. The application enforces a hard
maximum of **5,000** concurrent users.

---

## Metrics

Each request records: timestamp, HTTP status, response time, bytes received,
success/failure and (on failure) a normalised error category.

The dashboard and final report show:

- **Throughput** — total requests, current/average/peak requests-per-second
- **Outcomes** — success / failure counts and success rate
- **Latency** — min, average, P50, P90, P95, P99, max
- **HTTP status buckets** — 2xx / 3xx / 4xx / 5xx (and exact codes)
- **Errors** — timeout, DNS failure, connection refused/reset, SSL error,
  server disconnected, plus 4xx / 5xx counts

Latency percentiles use a fixed-size **reservoir sample** and rolling windows,
so memory stays flat during long tests.

---

## How concurrency works

NIGHTFALL creates a **bounded** pool of exactly *N* worker coroutines (one per
simulated user) — never an unlimited number of tasks. An `asyncio.Semaphore`
bounds simultaneous in-flight requests. Each worker waits for its ramp-up slot,
then loops: acquire a rate-limiter token → send a request → record the result →
repeat until the duration expires or you stop the test.

## How rate limiting works

A single, shared **token-bucket** limiter caps the *aggregate* request rate
across all workers. It refills at `--rps` tokens per second and starts empty so
the first second cannot spike above the configured rate. Set `--rps 0` for no
limit (bounded only by concurrency and the target's responses).

## Concurrent users vs. requests/sec

These are **not** the same thing, and neither equals real human visitors:

- **Concurrent users** = how many workers can have a request in flight at once.
- **Requests/sec (RPS)** = how many requests complete per second in aggregate.

A slow endpoint yields low RPS even with many concurrent users; a fast one
yields high RPS from few users. NIGHTFALL reports synthetic HTTP behaviour
only — it never claims a site "can handle X users."

## How to interpret latency

- **P50 (median)** — a typical response time.
- **P95 / P99** — the slow tail; watch these rise as concurrency increases.
- **Max** — the single worst response; often an outlier.

Rising P95/P99 while P50 stays flat usually means the target is starting to
queue or contend under load. Compare runs at different concurrency levels
rather than reading a single number in isolation.

---

## Using a proxy

NIGHTFALL can route all requests through **one explicit forward proxy** that
you supply and are authorized to use — for example your organisation's egress
proxy or your own load generator:

```bash
python nightfall.py --url https://you.example.com --proxy http://user:pass@proxy.internal:3128
```

or set it interactively in **[1] Configure Target**. `http://` and `https://`
proxies are supported (with optional `user:pass@`). Any credentials in the
proxy URL are redacted in the UI and are **never** written to exported reports.

By design, NIGHTFALL uses only the single proxy you provide. It does **not**
fetch, scrape, harvest or rotate proxies, and it does not rotate request
identities/fingerprints. Rotating traffic across many proxies to spread it
past rate limits or IP blocks, and randomising fingerprints to evade bot/WAF
detection, are anonymisation/evasion techniques used to defeat a target's
defences — this tool is for measuring the performance of a target you are
authorised to test, not for evading one, so those capabilities are
deliberately excluded.

## High concurrency and OS limits

The safety ceiling is **5,000** concurrent users. High concurrency opens many
sockets at once, so on Linux/macOS you may need to raise the open-file-descriptor
limit before large runs:

```bash
ulimit -n 65535        # for the current shell, before launching NIGHTFALL
```

Concurrency is bounded by your machine's CPU, memory, file descriptors and
network — a single host cannot honestly sustain arbitrarily large numbers. For
genuinely large-scale or geographically distributed load, run NIGHTFALL (or a
dedicated tool such as k6, Locust or JMeter) from multiple load generators you
own, rather than increasing the count on one machine.

---

## Running an authorized load test safely

1. Confirm in writing that you own or are authorized to test the target.
2. Start small — use the **Smoke Test** profile first.
3. Prefer a **staging** environment; coordinate with whoever operates the target.
4. Increase load gradually and watch error rates and P95/P99 latency.
5. Stop (**[S]**) at the first sign of instability.
6. Keep RPS limits conservative; you control the traffic you generate.

---

## Exported results

Exports are written to `results/`:

```
results/
    test_2026-09-19_131500.json
    test_2026-09-19_131500.csv
    test_2026-09-19_131500.txt
```

Each report includes timestamp, target, duration, configured/peak users,
request totals, success/failure counts, average & peak RPS, full latency
statistics, status-code counts, and error counts.

**Sensitive data is never exported** — Authorization headers, cookies,
credentials and request/response bodies are excluded by design.

---

## Project structure

```
nightfall/
├── nightfall.py          # entrypoint (argparse, interactive + CLI modes)
├── requirements.txt
├── README.md
├── core/
│   ├── engine.py         # orchestrates the worker pool & test lifecycle
│   ├── worker.py         # a single simulated user
│   ├── limiter.py        # global token-bucket rate limiter
│   ├── metrics.py        # bounded-memory metric collection
│   └── models.py         # dataclasses, config, URL validation, safety limits
├── ui/
│   ├── menu.py           # interactive menu & configuration screens
│   ├── dashboard.py      # live dashboard, graphs, breakdowns
│   ├── runner.py         # engine + dashboard + keyboard controls
│   ├── keyboard.py       # cross-platform non-blocking key reader
│   └── theme.py          # banner, colours, styling
├── export/
│   ├── json_export.py
│   ├── csv_export.py
│   └── text_export.py
└── results/              # exported reports (git-ignored)
```

---

## License / responsible use

Use NIGHTFALL only against systems you own or are explicitly authorized to
test. The authors accept no liability for misuse.
