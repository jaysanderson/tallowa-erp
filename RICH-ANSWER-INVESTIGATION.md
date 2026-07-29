# Rich Ops Assistant answer panel - Step 1 investigation

GM feedback (22 Jul 2026): the Ops Assistant's final answer looks dull - flat
numbered prose over data we already have structured. This is the investigation
findings before building the richer panel.

## Where the structured data actually lives

Every raw ARAG NDJSON line I'd been inspecting only had `step`/`answer` fields
populated (what `_map_arag_event` already parses). **There is a THIRD event
shape I had never looked at: `{"context": {...}, "operation": 0, ...}`.** It
arrives once per interaction, after the tool-call steps and before the
`possible_answer`/`answer` events. Its shape:

```json
{
  "context": {
    "id": "...", "question": "...",
    "chunks": [
      {
        "chunk_id": "mcp_<registered-agent-uuid>_<tool_name>",
        "title": "Calling <tool_name>",
        "text": "<the tool's raw JSON response, AS A STRING>",
        "action": "<tool_name> of <uuid> with parameters {...}",
        "origin_agent": "mcp"
      }
    ],
    "source": "smart_agent", "summary": "<same prose as the final answer>",
    "citations": ["<chunk_id>", ...]
  }
}
```

`chunk.text` is a **JSON-encoded string** of exactly what our own `/mcp` tool
returned - the real database rows, untouched by any LLM narration. `chunk_id`
lets us recover which tool it came from
(`^mcp_[0-9a-fA-F-]{36}_(.+)$` -> the tool name), matching the same UUID
convention `_tool_name()` already strips elsewhere.

`possible_answer` (an intermediate event) and the final `answer` event are
**pure prose, no structured data attached** - `possible_answer.chunks` /
`.structured` are both `null` in every run I captured. So the ONLY place the
rows live is this `context` event.

## Real field shapes, 3 different tools (full samples saved to
`/Users/jsanders/.claude/jobs/d1128312/tmp/sample_context_events.json`)

**"Which invoices are overdue and how much is outstanding?"** ->
`invoices_list_invoices`:
```json
{"id":6,"inv_no":"INV-5218","customer_id":2,"sales_order_id":6,"shipment_id":6,
 "status":"overdue","issued_on":"2026-06-16","due_on":"2026-07-16",
 "subtotal":20720.0,"gst":2072.0,"total":22792.0,"paid_on":null,
 "customer_name":"Marran Automotive"}
```
7 rows returned (only 3 `status:"overdue"` - the agent's prose only picked
those 3, silently discarding the other 4 draft/sent/paid rows that were
also in the payload).

**"What quality holds are open right now and why?"** -> `holds_list_holds`:
```json
{"id":5,"hold_no":"HLD-0145","scope":"run","scope_id":14,
 "reason":"Run consumed suspect lot WF-2261 - held at station 60 pending
 containment disposition","placed_by":"Dana Okafor",
 "placed_at":"2026-07-19T09:30:00Z","released_at":null,"released_by":null,
 "status":"open","scope_label":"RUN-1101"}
```

**"What is holding up production on line A-1?"** -> `lines_list_lines`:
```json
{"id":6,"plant_id":1,"code":"A-1","name":"Assembly & Test - Braking",
 "process_type":"assembly","takt_seconds":270,"status":"running",
 "stoppage_reason":null,"plant_name":"Bellbrook Plant","machines":3,
 "active_runs":1}
```
(This is the exact "trivial catalogue call" the false-confident-answer safety
net already excludes from grounding - confirms that fix is targeting the
right data shape.)

## What this means for the field-detection heuristic

Field names vary per tool (no single schema), but there's a strong, generalisable
convention across all of them, matching what `app.js`'s existing `badge()`
color map already assumes:
- **Identifier/label**: a `*_no` or `code` field, or `id` as fallback -
  `inv_no`, `hold_no`, `code`.
- **Money**: numeric field named `total`/`amount`/`subtotal`/`price`/`cost`/`value`.
- **Date**: string field named `*_on`/`*_at`/`*_date` matching an ISO date/
  datetime pattern.
- **Status/severity**: a `status` field - and `app.js` already has a
  comprehensive status -> colour `BADGE` map (`overdue`->red, `open`->red,
  `running`->green, `paid`->green, `sent`->blue, etc.) used by every table in
  the app already. The new renderer should reuse `badge()` directly rather
  than invent a second colour system.
- **Display name**: `customer_name`/`name`/`plant_name`/`scope_label` - the
  most prose-like string field, used as the row's primary label.
- **Reason/detail**: `reason`/`stoppage_reason` - free text, shown as a
  secondary line under the row.

This is enough to build one GENERIC structured-rows renderer (detect an
array-of-objects payload, infer id/money/date/status/name columns by name
pattern) that will lift every hero question that returns real rows, not just
invoices.

## Next: Step 2 prototype

Building `richAnswer()` in `app.js` - a generic renderer that, given the rows
array(s) captured from `context.chunks` during the stream, renders a headline
metric strip + a formatted table/cards with severity badges, replacing the
flat numbered-prose rendering as the primary "finished" view (prose becomes a
one-line summary above it). Report + before/after screenshots follow.
