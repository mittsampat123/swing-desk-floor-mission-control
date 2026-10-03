# Swing Desk — Guide

How to run this desk with your Claude and your Robinhood account. Read
it top to bottom once. It explains what the desk is, shows you every
screen, and walks you through standing it up, including the setup
interview where you tell your Claude which options strategy to execute.
Every `{{PLACEHOLDER}}` in the repo is something only you can fill.

---

## 1. What this is, in one paragraph

A rules-based options desk that runs inside Claude. Six times every
weekday a scheduled Claude routine wakes up, reads a "constitution"
(the rules you wrote), looks at the market through the Robinhood
connector, and runs one stage of a fixed workflow: scan, enter, monitor,
enter again, review, and on Fridays learn. It trades one strategy that
you define in plain English during setup, sized so that one position
can lose at most a fixed dollar amount you choose. A built-in risk
officer with hard caps can veto any trade, and a five-seat "council" has
to approve each ticket with evidence it gathers during the run.
Everything the desk thinks and does is written to a shared database and
shown live on two web pages: Mission Control (the numbers) and The Floor
(an animated dealing room that replays the day). Nobody has to be
watching for it to run, and you can halt it from your phone.

It is not a get-rich machine. Section 8 says plainly what to expect.

---

## 2. The workflow

```
                         weekdays, America/New_York
   08:30        10:30        12:30        13:30        15:30      Fri 16:30
 ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
 │ Morning │  │  Entry  │  │ Midday  │  │  Entry  │  │  Close  │  │ Weekly  │
 │  Scan   │─>│ Window  │─>│ Monitor │─>│ Window  │─>│ Review  │─>│  Retro  │
 └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘
      │            │            │            │            │            │
      │  ┌─────────┴────────────┴────────────┴────────────┘            │
      │  │          every order passes the DESK OFFICER                │
      │  │   (hard caps: size, slots, breakers, blackout, liquidity)   │
      │  └──────────────────────────────────────────────────────────── │
      │                                                                │
      ▼                                                                ▼
 your universe ──> your signal ──> candidates ──> COUNCIL            lessons,
 (saved scans,     (indicator or   (usually        (5 seats           parameter
  ETF list)         rule you set)   0 to 4/day)     vote)              nudges

 All stages read and write DESK MEMORY (the dashboard's database)
 and the two pages redraw live from it.
```

What each stage does, whatever the strategy:

| Stage | ET | What happens |
|---|---|---|
| Morning Scan | 08:30 | Runs every name in your universe through your signal. Names that qualify are candidates. Officer hard filters first, then the Council votes on each. Approved tickets are written as `theses` with status candidate. |
| Entry Window | 10:30 and 13:30 | For each approved candidate: build the contract the way your strategy says (expiry, strikes, legs), check the market is real (bids on every leg, price inside your limits), size to the risk cap, review the order, place it, then place the resting exit order your strategy calls for. |
| Midday Monitor | 12:30 | Re-mark every open position. Apply your stop rule. Confirm resting exit orders are still there. Handle expiry day. |
| Close Review | 15:30 | Monitor again, reconcile the broker's positions against desk memory, record fills and P&L, update stats. Anything in the account the desk did not open is reported, never touched. |
| Weekly Retro | Fri 16:30 | Grade every closed trade on Process (rules followed?) and Outcome (return on risk) separately. Write at most three lessons, each backed by at least five trades. May move one tunable parameter inside bounds you set. Officer caps never move. |

Each stage starts by writing `runs/<stage>` with status running and ends
by writing it ok, skipped or error. If a stage dies mid-way, the next
one sees it.

---

## 3. The screens

### 3a. Mission Control (the dashboard)

Source: `swing-desk.html`. A private web page you publish from your own
Claude. It reads desk memory live and polls your Robinhood account about
once a minute with your own login, so it never stores an account number.

Top row, left to right:

- **Equity vs base**: the trading base plus realized plus unrealized P&L.
- **Week P&L / Month P&L**: with your breaker levels underneath.
- **Account cash** and buying power from the broker.
- Three status pills: Officer (clear / restricted / action required),
  Broker (live / needs reconnect), Desk memory (live).
- **Halt desk** button: the kill switch. Sets `halted=true` in desk
  memory. No new entries until someone presses Resume. Open positions
  keep their resting exit orders and are still managed to exit.

Panels:

- **Workflow**: the six stages drawn as a pipeline. Each node is colored
  by its last run (green ok, amber skipped, red error, pulsing teal while
  running) and shows the time. Under it, one card per stage with the
  run's one-line summary.
- **Desk Officer**: gauges for open positions vs cap, max loss at risk
  vs cap, deployed capital, largest position vs cap, loss streak. The
  caps come from your `config/caps`. Red notes appear when a rule is
  breached (a position with no resting exit, too many positions,
  halted).
- **Candidates and open theses**: every ticket the desk is considering
  or holding, with legs, price, quantity, risk, indicator readings, and
  the Officer and Council verdicts.
- **Broker positions / Broker orders**: what Robinhood actually holds
  and has resting, straight from the connector. If this disagrees with
  the theses table, the Close Review will flag it.
- **Learning**: trades, win rate, average return on risk, average days
  held; every tunable in `config/params`; the lessons list.

### 3b. The Floor

Source: `swing-desk-floor.html`. The same data drawn as a dealing room.
It is the page you open on your phone to watch the desk work.

- **Launch sequence**: the stage timeline for today.
- **Scanner**: universe size, how many names were scanned, how many
  qualified, near misses.
- **The floor**: pixel-art characters. Each Council seat has a desk;
  when a stage runs they walk to their desks, a ticket appears, and the
  votes stamp onto it (approved / rejected). The dealer sits at the
  order desk.
- **Book**: open positions as a tape.
- **On screen**: a live chart for the name in play with indicator panes
  computed in the page.
- **Desk chatter**: the Council's evidence lines, per seat, per ticket.
- **Indicator wall**: readings for the names closest to a signal.
- **HALT DESK**: the same kill switch as Mission Control.

### 3c. Desk memory

The dashboard's built-in database. Every stage reads and writes it with
the Artifact tool. The two pages subscribe to it, so a write shows up on
screen within a second.

| Collection / doc | What lives there |
|---|---|
| `config/caps` | The Officer's hard rules. Read-only. Includes `base_usd`, the caps, the holiday and blackout lists, and `strategy_code`. |
| `config/params` | Your strategy's tunable parameters with their `bounds`. The retro may move one per week. |
| `config/state` | halted flag, breaker flags, loss streak, week and month start equity, saved scan ids, ETF list, last heartbeat. |
| `runs/<stage>` | Last run of each stage: status, times, summary, details. The scan run also carries the scan summary the floor draws. |
| `council/<SYMBOL>-<date>` | One document per Council sitting: five votes with confidence and evidence, the verdict, the macro, range, liquidity and events facts. |
| `theses/<SYMBOL>-<date>-<n>` | One document per position: legs, expiry, price, quantity, max loss, order ids, exit, P&L, return on risk, Officer and Council results. |
| `lessons/<date>-<n>` | Weekly retro output with evidence and any applied parameter change. |
| `stats/summary` | Realized P&L, trades, wins, losses, average return on risk, breakdowns. |

---

## 4. The parts in the repo

| File | Role |
|---|---|
| `swing-desk-prompts.md` | The prompt pack. PROMPT 0 is the constitution: account, STRATEGY (yours), indicators, Council, calendar, Officer, order protocol, authorization, database layout. PROMPTS 1 to 6 are setup and the stages. PROMPT 7 is a read-only status you can paste any time. |
| `swing-desk-routine-prompt.md` | The stage prompts plus a dispatch block plus the indicator engine, composed into one prompt for one scheduled routine. Generated, do not edit by hand. |
| `swing-desk-routine.json` | The same thing as an API body for the claude.ai routines endpoint. Generated. |
| `build_routine.py` | Regenerates the two files above from the prompt pack and the engine. Run it after any edit to either. It prints any placeholder still unfilled. |
| `desk_indicators.py` | An indicator engine in standard-library Python: moving averages, RSI, ADX, ATR, Williams %R variants including a smoothed fast/slow pair, and market-structure tools (structure breaks, order blocks, fair value gaps, premium/discount zone). It also contains a few example rule checks that show how a rule is encoded; they gate nothing unless your strategy names them. The routine writes this file into its sandbox every run. |
| `swing-desk.html`, `swing-desk-floor.html` | Sources of the two pages. |

---

## 5. The rules the desk cannot break

These live in `config/caps` and in PROMPT 0 OFFICER RULES. The Weekly
Retro may never change them. Only you, editing the constitution, can.
You set the numbers in Step 3.

| Rule | You set |
|---|---|
| One account | The single Robinhood account enabled for agentic trading. Never any other. |
| Trading base | A fixed dollar amount. Cash above it is reserve and is never deployed. |
| Risk per position | A fixed dollar cap on the max loss of one position. Quantity is derived from it. If one unit risks more than the cap, skip. Never scaled up after wins. |
| Slots | Max open positions, max per underlying, max new per day. |
| Defined risk only | Every position has a known max loss at entry. No naked short options. |
| Resting exit | Every open position has a resting GTC exit order at the broker, placed right after the fill, so the exit survives even if a run fails. |
| Breakers | Week-to-date worse than your percent of base: no new entries until Monday. Month-to-date worse than your percent: close everything, set halted, stop. Only a human writing halted=false restarts. |
| Loss streak | After N straight losers, half size for the next N. |
| Blackouts | FOMC days, market holidays, earnings inside the position's life for single stocks. The lists live in `config/caps`; refresh them each January. |
| Liquidity | Every leg must show a real bid. A mark with no bid is not a price. |
| Order protocol | Review before place. Fresh UUID per order, same UUID on retry. Re-read the order after placing; never assume a fill. |

---

## 6. Setting up your own copy

You need: a Robinhood account with the options level your strategy
needs and agentic (Claude) trading enabled on exactly one account; a
Claude plan with Claude Code, Artifacts and routines; this repo cloned
to a machine with Python 3 and the Claude desktop app or CLI.

You do not run these steps by hand. Open the repository in Claude Code
and say hello; Claude reads CLAUDE.md and works through them with you,
one question at a time. They are written out here so you know what is
coming and can check its work. The quoted blocks are what Claude does
at each step, phrased as the request it is fulfilling.

**Step 1. Connect Robinhood.** In claude.ai, Settings, Connectors, add
Robinhood and sign in. In the Robinhood app, enable agentic trading on
the one account you want the desk to use and fund it. Then in Claude
Code:

> Call get_accounts on the Robinhood connector and tell me which account
> is tradable by you. Show only the last four digits.

**Step 2. Define your strategy.** This is the step that makes the desk
yours. Paste this:

> Read GUIDE.md and PROMPT 0 of swing-desk-prompts.md. I am setting up
> my own copy of this desk. Please ask me, one question at a time, what
> options strategy I would like to execute, until you can write it as
> rules a machine can follow with no judgment calls. Cover every
> sub-section of the STRATEGY block: INSTRUMENT, UNIVERSE, SIGNAL,
> CONTRACT, ENTRY, EXIT, SIZING, TUNABLES. Push back when an answer
> needs judgment to apply, and propose a measurable version. When we
> are done, fill the eight STRATEGY placeholders in PROMPT 0 with my
> answers, set config/caps strategy_code to a short label, and show me
> the finished STRATEGY block before saving. If my strategy needs an
> indicator the engine does not compute, add it to desk_indicators.py
> and to the chart in swing-desk-floor.html. Do not place any order.

Your Claude will interview you and write the strategy into the
constitution.

**Step 3. Fill the rest of PROMPT 0.** Open `swing-desk-prompts.md`.

- ACCOUNT: `{{ACCOUNT_NICKNAME}}`, `{{ACCOUNT_LAST4}}`, `{{BASE_USD}}`.
- COUNCIL: `{{COUNCIL_VIX_MAX}}` (35 is a common choice),
  `{{COUNCIL_MIN_OI}}` (100 is a common choice).
- OFFICER RULES: `{{RISK_PER_POSITION_USD}}`, `{{MAX_POSITIONS}}`,
  `{{MAX_PER_NAME}}`, `{{MAX_DAILY_ENTRIES}}`, `{{ENTRY_WINDOW_ET}}`,
  `{{WEEKLY_BREAKER_PCT}}`, `{{MONTHLY_BREAKER_PCT}}`,
  `{{LOSS_STREAK_N}}`.
- STANDING AUTHORIZATION: `{{STANDING_AUTHORIZATION}}`. Write it in
  your own words. The Robinhood connector will not place an order
  unattended without the owner's explicit standing confirmation, and
  this paragraph is where it lives. Say who you are, which account by
  its last four digits, what you authorize (place, cancel and replace
  option orders in that account within the Officer rules, without
  per-order confirmation), from when, and that you can revoke it in
  writing. If you leave the placeholder in place, every stage stops at
  the review step and asks, which is a fine way to run the first week.

Or ask Claude to do it with you:

> Walk me through every remaining {{PLACEHOLDER}} in
> swing-desk-prompts.md except the two URLs, one at a time, suggest a
> sensible default for each and explain the trade-off, and fill in my
> answers.

**Step 4. Publish your own Mission Control and Floor.**

> Publish swing-desk.html as a new private artifact named "Swing Desk"
> with capabilities db and mcp (Robinhood: get_accounts, get_portfolio,
> get_equity_positions, get_equity_orders, get_equity_quotes,
> get_option_positions, get_option_orders, get_option_quotes). Then
> publish swing-desk-floor.html as a second artifact named "Swing Desk
> Floor" with the same capabilities. Give me both URLs. Then replace
> {{DASHBOARD_URL}} and {{FLOOR_URL}} everywhere in the repo with those
> URLs and republish both pages.

**Step 5. Seed desk memory.** Paste PROMPT 0 and PROMPT 1 (Setup) into
a chat with the Robinhood connector. It writes `config/caps`,
`config/params`, `config/state` and `stats/summary`, creates your
universe scans in Robinhood, looks up this year's holidays and FOMC
dates for you to check, and dry-runs your signal on five names so you
can confirm the rule reads the way you meant. Open your dashboard: the
Officer pill should read "clear to trade" and Broker "live".

**Step 6. Backtest three years before trading a dollar.** Section 6b.
Do not schedule the routine until you have read the worst trades.

**Step 7. Dry run by hand.** Paste PROMPT 0 and PROMPT 2 (Morning Scan)
into a chat with the Robinhood connector on a weekday morning. Watch the
Floor while it runs. Then PROMPT 7 (Status). If you left the
authorization placeholder in place, also run PROMPT 3 once and see it
stop and ask at the review step. That is the behaviour to understand
before you take the gate off.

**Step 8. Build and schedule the routine.**

```bash
python build_routine.py
```

It regenerates `swing-desk-routine-prompt.md` with your constitution
inside and prints any placeholder you forgot. Then at
claude.ai/code/routines create one routine:

- Prompt: everything below the line in `swing-desk-routine-prompt.md`.
- Schedule: `30 12,14,16,17,19,20 * * 1-5` UTC while US daylight time
  lasts (08:30, 10:30, 12:30, 13:30, 15:30, 16:30 ET). After the
  November clock change use `30 13,15,17,18,20,21 * * 1-5`.
- Connector: Robinhood. Tools: Bash, Read, Write, Glob, Grep, WebSearch,
  WebFetch, ToolSearch, Artifact and the Robinhood tools.
- Session persistence off. Notifications on, so you get an email per run.

The routine fires six times a day and runs exactly one stage by the
clock, so one routine covers the whole workflow.

**Step 9. Watch the first week.** Open the Floor each morning. Read the
run cards on Mission Control. Zero candidates on most days is normal
for a selective signal. If you see a red Officer note, read it before
you do anything else.

---

## 6b. Backtesting: three years

Have your Claude write the backtest from your strategy. Paste this in
Claude Code after Step 2:

> Read the STRATEGY and OFFICER RULES sections of PROMPT 0 in
> swing-desk-prompts.md. Write a backtest that replays exactly those
> rules over the last three years of daily bars for my universe, using
> desk_indicators.py for the indicators: fetch the bars with
> get_equity_historicals (interval=day, 10 symbols per call, three years
> plus 300 trading days of warm-up), enter at the next day's open after
> a signal, model option prices with Black-Scholes on 20-day realized
> volatility times 1.2 with two cents of slippage per leg, apply my
> take-profit, stop, time stop and expiry rules, and enforce every
> Officer cap: risk per position, max positions, per name, per day,
> weekly and monthly breakers, loss-streak halving. Report trades, win
> rate, average return on risk, P&L by year and by quarter, by entry
> weekday, by exit reason, the maximum drawdown and its date, and the
> ten worst trades with dates. Then run it again with volatility times
> 1.0 and again with five cents of slippage, and show all three side by
> side. Save the script and every result under research/ with today's
> date. Place no orders.

Read it in this order: the ten worst trades, then by year and quarter,
then the drawdown and what the market was doing that month, then exit
reasons, and the win rate last. If you change the strategy because of
what you read, change PROMPT 0 and run the backtest again.

---

## 7. Running it day to day

- **From a phone**: the Floor link to watch; the Claude app with PROMPT 0
  plus PROMPT 7 for a read-only status; HALT DESK on either page to stop
  new entries.
- **To stop everything**: press Halt. Open positions still have resting
  exit orders at the broker and the monitor stages still manage them. To
  also flatten, run PROMPT 0 plus "close every open position at market
  now and record the exits".
- **To change a rule**: edit PROMPT 0, run `python build_routine.py`,
  paste the new prompt into the routine, commit. Caps are yours to
  change; the Retro's are not.
- **If Broker shows "reconnect"**: claude.ai, Settings, Connectors,
  reconnect Robinhood. Runs fail until you do; the resting exit orders at
  the broker are what protect you in the meantime.
- **If desk memory and the broker disagree**: the Close Review reports
  it in `runs/close.details` and on the dashboard. The broker is the
  truth. Fix memory, never the account, unless you know why.
- **Clock change**: twice a year. Shift the cron as in Step 8.
- **Each January**: refresh `config/caps` market_holidays, early_closes
  and event_blackout_days.

---

## 8. What to expect, stated plainly

- The desk executes whatever you wrote in Step 2 with discipline. It
  cannot make a bad strategy good. The replay in Step 6 is the only
  honest preview you get; read the worst trades, not the win rate.
- Defined-risk short option strategies tend to win often and lose big.
  A strategy that returns 5% of risk per winner needs to win 95% of the
  time just to break even. Size for the losing streak, not the winning
  one. That is what the risk-per-position cap is for.
- Slippage and illiquid markets quietly kill small-edge strategies. The
  liquidity rule exists for that reason. Keep it.
- Breakers will trip. When they do, the desk is working. Read the retro
  before you change anything.
- This is not advice and nobody here is a licensed adviser. The rules
  are written down so you can read them, test them, and decide for
  yourself before a dollar moves.

---

## 9. Every placeholder in the repo

| Placeholder | Where | Filled in |
|---|---|---|
| `{{STRATEGY_INSTRUMENT}}` … `{{STRATEGY_TUNABLES}}` (8) | PROMPT 0 STRATEGY | Step 2 |
| `{{ACCOUNT_NICKNAME}}`, `{{ACCOUNT_LAST4}}`, `{{BASE_USD}}` | PROMPT 0 ACCOUNT | Step 3 |
| `{{COUNCIL_VIX_MAX}}`, `{{COUNCIL_MIN_OI}}` | PROMPT 0 COUNCIL | Step 3 |
| `{{RISK_PER_POSITION_USD}}`, `{{MAX_POSITIONS}}`, `{{MAX_PER_NAME}}`, `{{MAX_DAILY_ENTRIES}}`, `{{ENTRY_WINDOW_ET}}`, `{{WEEKLY_BREAKER_PCT}}`, `{{MONTHLY_BREAKER_PCT}}`, `{{LOSS_STREAK_N}}` | PROMPT 0 OFFICER RULES | Step 3 |
| `{{STANDING_AUTHORIZATION}}` | PROMPT 0 | Step 3 (or leave in place for a supervised first week) |
| `{{DASHBOARD_URL}}`, `{{FLOOR_URL}}` | prompt pack header and DATABASE section, both HTML pages | Step 4 |
| `{{ROBINHOOD_CONNECTOR_UUID}}`, `{{ENVIRONMENT_ID}}` | build_routine.py | Only if you create the routine through the API; pasting the prompt by hand needs neither |

`build_routine.py` prints any placeholder it still finds.

---

## 10. Glossary

- **Defined risk**: a position whose maximum loss is known when you open
  it, such as a vertical spread. The Officer requires it.
- **Delta**: roughly the probability an option finishes in the money.
- **Return on risk**: profit divided by max loss. A position that risks
  $500 and makes $25 returned 5%.
- **Resting exit**: a good-till-cancelled order sitting at the broker
  that closes the position at your target without the desk being awake.
- **Officer**: the hard-cap layer. Runs inside every stage. Cannot be
  argued with.
- **Council**: five seats (macro, range, liquidity, events, officer)
  that vote on each candidate with evidence gathered during the run.
- **Desk memory**: the dashboard artifact's database.
- **Routine**: a scheduled Claude session at claude.ai/code/routines.
