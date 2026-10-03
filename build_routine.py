#!/usr/bin/env python3
"""Compose the single cloud-routine prompt from the prompt pack and the indicator engine.

Writes swing-desk-routine-prompt.md (human-pasteable) and swing-desk-routine.json
(body for the claude.ai routines API). Run after editing swing-desk-prompts.md or
desk_indicators.py so the routine stays in sync with the repo.

Two values in the JSON body are yours to fill (or leave the placeholders and paste
the prompt into a routine by hand at claude.ai/code/routines):
  ROBINHOOD_CONNECTOR_UUID  the id of your Robinhood connector in claude.ai
  ENVIRONMENT_ID            the id of the cloud environment your routines run in
"""
import json, re, sys

ROBINHOOD_CONNECTOR_UUID = "{{ROBINHOOD_CONNECTOR_UUID}}"
ENVIRONMENT_ID = "{{ENVIRONMENT_ID}}"

src = open('swing-desk-prompts.md', encoding='utf-8').read()
engine = open('desk_indicators.py', encoding='utf-8').read()

def section(prefix):
    i = src.index('## ' + prefix); j = src.index('\n------', i); return src[i:j].strip()

def body(s, banner):
    return '=' * 72 + '\n' + banner + '\n\n' + s.split('\n', 1)[1].strip()

p0 = section('PROMPT 0').split('\n', 1)[1].strip()
dispatch = '''DISPATCH (read this first)
This routine fires six times per weekday. While US daylight time lasts the cron is 30 12,14,16,17,19,20 UTC (08:30, 10:30, 12:30, 13:30, 15:30, 16:30 ET); after the November clock change it is 30 13,15,17,18,20,21 UTC. Get the current time in New York with Bash: TZ=America/New_York date +%H. Run exactly one stage by that ET hour and then stop: 08 = Morning Scan; 10 = Entry Window (first pass); 12 = Midday Monitor; 13 = Entry Window (second pass); 15 = Close Review; 16 = Weekly Retro, and only if today is Friday in America/New_York (on other days reply 'no stage at this hour' and stop without writing anything). Any other hour: reply 'no stage at this hour' and stop.
The Artifact tool (read_db / write_db) may not be in your tool list at start; load it with ToolSearch ("select:Artifact") before the first database call.

INDICATOR ENGINE (write this file first in every stage that needs indicators)
Save the Python below verbatim to desk_indicators.py in the working directory (Write tool). It needs only the standard library. Run it as
  python3 desk_indicators.py <bars.json> [params.json] > report.json
where <bars.json> is the file that Claude Code saved a large get_equity_historicals result to (the tool result tells you the path; never read that file yourself, just pass the path), and params.json holds config/params from desk memory. Then read report.json. It computes, per symbol: the classic set (sma50/200, ema10/20, rsi14/2, adx10, atr14, 20-day high pullback, volume vs 20-day average), Williams %R variants including a smoothed fast/slow pair with joint zones and reversal signals, and market-structure tools (swing and internal structure BOS/CHoCH, order blocks, fair value gaps, premium/discount zone). It also reports example rule checks (setups A, B, C, P and rule R); those are examples and gate nothing unless your STRATEGY's SIGNAL section names them. Trust the report; do not recompute by hand.

----- desk_indicators.py -----
''' + engine + '''
----- end of desk_indicators.py -----'''

prompt = p0.replace('ACCOUNT\n', dispatch + '\n\nACCOUNT\n', 1) + '\n\n' + '\n\n'.join([
    body(section('PROMPT 2'), 'STAGE: MORNING SCAN (08 ET)'),
    body(section('PROMPT 3'), 'STAGE: ENTRY WINDOW (10 and 13 ET)'),
    body(section('PROMPT 4'), 'STAGE: MIDDAY MONITOR (12 ET)'),
    body(section('PROMPT 5'), 'STAGE: CLOSE REVIEW (15 ET)'),
    body(section('PROMPT 6'), 'STAGE: WEEKLY RETRO (16 ET, Fridays only)')])

left = sorted(set(re.findall(r'\{\{[A-Z0-9_]+\}\}', prompt)))
if left:
    print('placeholders still in the prompt pack (fill them before scheduling):', ', '.join(left), file=sys.stderr)

open('swing-desk-routine-prompt.md', 'w', encoding='utf-8').write(
    '# Swing Desk routine prompt\n\nPaste everything below the line as the prompt of ONE claude.ai routine '
    '(claude.ai/code/routines). Schedule: cron `30 12,14,16,17,19,20 * * 1-5` (UTC) during US daylight time, '
    '`30 13,15,17,18,20,21 * * 1-5` after the November clock change. Connector: Robinhood. Tools: Bash, Read, '
    'Write, Glob, Grep, WebSearch, WebFetch, ToolSearch, Artifact, mcp__Robinhood__*. Session persistence: off. '
    'Regenerate this file with build_routine.py after editing the prompt pack or desk_indicators.py.\n\n---\n\n' + prompt + '\n')

body_json = {
    "name": "Swing Desk (one strategy, weekdays, six stages by the clock)",
    "cron_expression": "30 12,14,16,17,19,20 * * 1-5", "enabled": False, "persist_session": False,
    "mcp_connections": [{"connector_uuid": ROBINHOOD_CONNECTOR_UUID, "name": "Robinhood", "url": "https://agent.robinhood.com/mcp/trading"}],
    "notifications": {"channel": {"email": True, "push": False}},
    "session_request": {"environment_id": ENVIRONMENT_ID,
                        "config": {"model": "claude-fable-5", "allowed_tools": ["Bash", "Read", "Write", "Glob", "Grep", "WebSearch", "WebFetch", "ToolSearch", "Artifact", "ArtifactData", "mcp__Robinhood__*"]},
                        "events": [{"payload": {"type": "user", "message": {"role": "user", "content": prompt}}}]}}
json.dump(body_json, open('swing-desk-routine.json', 'w', encoding='utf-8'), indent=1)
print(len(prompt), 'chars in routine prompt')
