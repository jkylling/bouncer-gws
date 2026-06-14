# bouncer-gws

[Bouncer](https://github.com/jkylling/bouncer) API specs for Google
Workspace: Gmail, Calendar, Drive, Docs, and Sheets.

## Installing

From a bouncer data directory:

```sh
bouncer apis add github.com/jkylling/bouncer-gws@<ref>
```

## What's in the box

| File                 | Service      | Notes                                                          |
|----------------------|--------------|----------------------------------------------------------------|
| `apis/gmail.yaml`    | Gmail API v1 | 14 metas (mailbox, message, thread, draft, label, attachment, plus 8 `settings_*` metas), 79 actions across messages, threads, drafts, labels, history, attachments, watch/stop, and settings (filters, send-as, vacation, IMAP/POP, language, forwarding, delegates, S/MIME, CSE). |
| `apis/calendar.yaml` | Calendar v3  | 5 metas (calendar, calendar_list_entry, event, acl_rule, setting), 37 actions across calendars, calendar list, events, ACL, freebusy, colors, settings, push notifications. |
| `apis/drive.yaml`    | Drive v3     | 7 metas (drive_user, file, permission, comment, reply, revision, drive), 45 actions across files, permissions, comments, replies, revisions, changes, shared drives. |
| `apis/docs.yaml`     | Docs v1      | 1 meta (document); 3 actions: `create_document`, `get_document`, `batch_update_document`. |
| `apis/sheets.yaml`   | Sheets v4    | 3 metas (spreadsheet, developer_metadata, value_range), 17 actions across spreadsheets, values, batch operations, developer metadata. |
| `apis/discovery.yaml`| Discovery v1 | 0 metas, 2 actions (`list_apis`, `get_rest_description`). Public schema service Google SDKs hit at startup; no auth, no user data. Pair with the permit-all suggested policy below. |

## Authentication

Google Workspace APIs accept short-lived OAuth2 access tokens.
Bouncer wraps either a hand-captured access token (one-shot calls)
or a refresh token (long-running agents) into a JWT the proxy
unwraps and forwards upstream.

### Scopes

Pick the tightest scope per service the agent will touch. Bouncer
narrows, never widens. A token issued with `gmail.readonly` cannot
`send_message` regardless of what the policy permits.

| Service  | Scope                                             |
|----------|---------------------------------------------------|
| Gmail    | `gmail.modify` for most patterns; `gmail.readonly` for read-only agents. |
| Calendar | `calendar`; `calendar.readonly`.                  |
| Drive    | `drive`; `drive.file` if the agent only touches files it created. |
| Docs     | `documents`; pair with a Drive scope to discover. |
| Sheets   | `spreadsheets`; same — pair with Drive for discovery. |

Full URI is `https://www.googleapis.com/auth/<scope>`.

### Access token (smoke test, CI)

Quick path — no Google project required. In the
[OAuth Playground](https://developers.google.com/oauthplayground)
tick the scopes from the table, *Authorize APIs*, then *Exchange
authorization code for tokens*. Copy `access_token` (`ya29…`) and
mint a bouncer JWT around it:

```sh
bouncer issue-token \
  --subject my-agent \
  --access-token "$GOOGLE_ACCESS_TOKEN" \
  --ttl 1h
```

Google access tokens expire after ~1h.

### OAuth2 refresh (long-running agents)

Capture a refresh token once and let `POST /token` rotate access
tokens transparently.

**1. Set up a Google Cloud project and OAuth client.** A one-time
ten-minute setup; the same client can issue refresh tokens for any
number of agents.

   a. **Pick or create a project** at
      [console.cloud.google.com](https://console.cloud.google.com/).
      Personal Gmail accounts can create projects too — no
      Workspace tenant required.

   b. **Enable each upstream API** at
      [APIs & Services → Library](https://console.cloud.google.com/apis/library).
      Search for and enable *Gmail API*, *Google Drive API*,
      *Google Docs API*, *Google Sheets API*, *Google Calendar API*
      — whichever the agent will touch. Skipping one means a 403
      from Google before bouncer's policy runs.

   c. **Configure the OAuth consent screen** at
      [APIs & Services → OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent):
      - *User type*: **External** (Internal only works inside a
        Workspace org).
      - Fill in app name + support email.
      - Add the scopes from the table above. Sensitive / restricted
        scopes (`gmail.modify`, `drive`) flag the project for
        Google verification before the app can leave Testing mode.
      - Add your own Google
        account as a *Test user* — the agent acts as you, so the
        test user is the same address whose mailbox / Drive the
        agent will touch. Refresh tokens issued in
        Testing expire after 7 days, so a long-running agent
        eventually needs the app to be published.

   d. **Create an OAuth 2.0 Client ID** at
      [APIs & Services → Credentials](https://console.cloud.google.com/apis/credentials)
      → *Create credentials* → *OAuth client ID*:
      - *Application type*: **Desktop app** — the loopback flow
        Google's CLIs and `gws-cli` use. No redirect URIs to
        configure.
      - Download the JSON; save as `client_secrets.json`. Treat
        like a (low-sensitivity) credential — it's the
        impersonation surface for anyone running the OAuth flow.

**2. Capture a refresh token.** This bundle ships
[`scripts/get_credentials.py`](scripts/get_credentials.py) — a
stdlib-only Python script (3.7+) that drives the installed-app
loopback flow. It opens a browser for consent, listens on
`127.0.0.1:<free-port>` for the redirect, exchanges the code with
PKCE, and writes a credentials JSON in the shape bouncer reads:

```sh
python3 scripts/get_credentials.py \
  --client-secrets ./client_secrets.json \
  --scopes gmail.modify,drive,calendar,documents,spreadsheets \
  --out ./google-creds.json
```

Any other tool that drives the same flow works equivalently —
[`gws-cli`](https://github.com/googleworkspace/cli)'s
`gws auth login` followed by `gws auth export --unmasked >
google-creds.json` produces a compatible file.

**3. Mint a `credentials.json`.** Wrap the refresh token in a
refresh JWT and write a Google-shaped credentials file. The
`--proxy-url` value is the *origin the OAuth2 client will POST to
on refresh* and depends on how the client reaches the proxy:

- **MITM mode (default for unmodified SDKs).** The client thinks
  it is calling Google directly; HTTPS_PROXY routes the connection
  through bouncer, which intercepts `POST /token` regardless of
  Host. Use Google's real token origin so the client config is
  unaltered:

  ```sh
  bouncer issue-token \
    --subject my-agent \
    --credentials-file ./google-creds.json \
    --proxy-url https://oauth2.googleapis.com \
    --out ./credentials.json
  ```

- **Direct mode (the client points at the proxy itself).** Used
  for clients that accept an arbitrary `token_uri`. Skip the
  HTTPS_PROXY / CA-trust dance, but configure the client with
  bouncer's host:

  ```sh
  bouncer issue-token \
    --subject my-agent \
    --credentials-file ./google-creds.json \
    --proxy-url http://localhost:8080 \
    --out ./credentials.json
  ```

`issue-token` reads `client_id`, `client_secret`, and
`refresh_token` from the input file and copies them into the
output — the upstream `client_id` / `client_secret` ride on the
wire on every refresh (standard OAuth2), and the upstream refresh
token is encrypted into the JWT and never leaves the proxy.

### Sanity check

If your access token is good, this curl call (no proxy) returns
your Gmail profile:

```sh
curl -s https://gmail.googleapis.com/gmail/v1/users/me/profile \
  -H "Authorization: Bearer $GOOGLE_ACCESS_TOKEN"
```

The same call against the proxy with the bouncer JWT should
round-trip identically (subject to whatever policies are
installed):

```sh
curl -s http://localhost:8080/gmail/v1/users/me/profile \
  -H "Authorization: Bearer $BOUNCER_JWT"
```

## Calling the proxy

### Curl

Replace each Google host with the bouncer host; the path stays
the same:

```sh
curl -H "Authorization: Bearer $BOUNCER_JWT" \
     http://localhost:8080/gmail/v1/users/me/profile
```

### gws-cli / gogcli / official SDKs

Tools that hard-code Google's API hosts can't be redirected to a
different origin. Trust bouncer's MITM CA, point the client at the
proxy via `HTTPS_PROXY`, and the client transparently calls bouncer
thinking it's Google. Most of these SDKs also fetch a Discovery
document at startup; install the permit-all policy for the
`discovery` API (see *Discovery — recommended policy* below) so
those bootstrap calls aren't denied.

```sh
# 1. Trust bouncer's MITM CA (one-time bootstrap).
curl -fsS http://localhost:8080/_api/ca.crt -o bouncer-mitm-ca.crt
export SSL_CERT_FILE=$PWD/bouncer-mitm-ca.crt

# 2. Point HTTPS_PROXY at bouncer and feed the client the
#    credentials file that issue-token --out produced.
export HTTPS_PROXY=http://localhost:8080
export GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=$PWD/credentials.json
gws drive files list
```

## Gmail — suggested setup and policy patterns

Two trust signals do the work in these patterns:

- **`<LABEL_ID>`** — a Gmail label the operator (or a separate
  reviewer step) attaches to messages the agent is allowed to
  touch. Durable, visible in the Gmail UI, and the agent can update
  it explicitly through `modify_message`. Use for the day-to-day
  "the agent owns this thread" gate.
- **`<TRUSTED_HEADER>: <TRUSTED_HEADER_VALUE>`** — a header the
  agent's compose pipeline should stamp on every outgoing body. Its a limitation of the Gmail API that labels cannot be added at creation, drafts or sent messages. The
  *originator* signal: any reply in the thread carries it without
  an extra label round-trip. The header is externally visible if email metadata is inspected. Consider using `BCC: <your-email>+ai@<domain>` if you want to keep the header from leaking.

### Agent-owned messages (read, modify, trash, delete)

Permit every `users.messages.*` action that binds `message`, plus
`get_attachment`, when the message is "agent-owned" — tagged with
`<LABEL_ID>` OR carrying the trusted header.

```yaml
action: |
  action.name in [
    "get_message", "modify_message",
    "trash_message", "untrash_message", "delete_message",
    "get_attachment"
  ]
condition: |
  "<LABEL_ID>" in message.labelIds
  || (message.headers != null
      && message.headers.exists(h,
           h.name == "<TRUSTED_HEADER>" && h.value == "<TRUSTED_HEADER_VALUE>"))
result: permit
```

Listing-style actions (`list_messages`, `list_threads`,
`list_labels`) are gated separately — see *Read-only discovery*
below. `list_threads` is the load-bearing one: thread results
carry message snippets, so it needs a tighter pattern than the
other two.

### Agent-owned threads

Same predicate, lifted to the thread level: a thread is agent-owned
when *any* of its messages carries `<LABEL_ID>` or the trusted
header. Matches the typical Gmail workflow where the user replies
in-thread and the agent should keep its permissions across the
whole thread, not just the original message.

```yaml
action: |
  action.name in [
    "get_thread", "modify_thread",
    "trash_thread", "untrash_thread", "delete_thread"
  ]
condition: |
  thread.messages.exists(m,
    "<LABEL_ID>" in m.labelIds
    || (m.payload.headers != null
        && m.payload.headers.exists(h,
             h.name == "<TRUSTED_HEADER>" && h.value == "<TRUSTED_HEADER_VALUE>")))
result: permit
```

### Agent-authored drafts (read, update, delete)

Drafts can't be self-labelled via the drafts API, so the trust signal here is the trusted header in the
draft's RFC-5322 body. The agent stamps it; `agent_drafts` reads
it.

```yaml
action: |
  action.name in ["get_draft", "update_draft", "delete_draft"]
condition: |
  draft.message.payload.headers != null
  && draft.message.payload.headers.exists(h,
       h.name == "<TRUSTED_HEADER>" && h.value == "<TRUSTED_HEADER_VALUE>")
result: permit
```

`delete_draft` is in the set on purpose: nothing has left the
mailbox yet, and an agent that can `update_draft` can already
overwrite the contents to nothing.

### Sending drafts (`<SEND_LABEL_ID>`)

`send_draft` is the load-bearing safety boundary — sending actually
delivers mail. Use a *separate* label `<SEND_LABEL_ID>` (distinct
from `<LABEL_ID>`) and require it on the draft's underlying message
before allowing send:

```yaml
action: action.name == "send_draft"
condition: |
  "<SEND_LABEL_ID>" in draft.message.labelIds
result: permit
```

Why a label rather than a header here: the agent stamps headers on
its own bodies, so a header is not credible against an
agent-side compromise. Labels live on message metadata and can be
applied by a separate actor via `users.messages.modify` against the
draft's underlying message id — bypassing the drafts-update
labelling restriction that prevents the agent itself from
self-labelling. Typical wirings for `<SEND_LABEL_ID>`:

- a reviewer button in `/_admin/proposals` that calls
  `users.messages.modify` to attach the label, then approves the
  send;
- a separate MCP tool the agent harness only calls after a human
  OK in some side channel;
- a per-call proposal approved through `/_api/proposals` whose
  approval handler attaches the label.

### Creating authored drafts

Refuse `create_draft` unless the request body's structured
`message.payload.headers` already contains the trusted header. This
lifts the gate from "agent can write to the drafts folder" to
"every draft the agent writes is announced as its own work":

```yaml
action: action.name == "create_draft"
condition: |
  request.body.?message.?payload.?headers.orValue([]).exists(h,
    h.name == "<TRUSTED_HEADER>" && h.value == "<TRUSTED_HEADER_VALUE>")
result: permit
```

### Read-only discovery

`list_messages` and `list_labels` return only metadata (ids and
label names — no body content), so a single open permit is
appropriate:

```yaml
action: |
  action.name in ["list_messages", "list_labels"]
condition: "true"
result: permit
```

### Guarded thread discovery

`list_threads` is split out because each returned thread carries
a `snippet` field — ~100–200 chars of the latest message, plus
HTML highlight tags around any `q=` match. Unconstrained, that's
enough to leak content past the label gate: `q=test` returns the
matching thread's snippet even when `agent_threads` would refuse
`get_thread` on the same id.

If discovery isn't load-bearing, **omit `list_threads` entirely**
and let the operator hand the agent thread ids out-of-band. If
search is needed, require every request to carry a `labelIds=`
filter pinned to the agent label so only operator-tagged threads
surface. `labelIds` is a strict AND-filter — additional
`labelIds` or a `q=` clause can only narrow the return set, never
broaden it (`q=label:<NAME>` is not equivalent: `q` is freeform
text, so the agent could append other terms and reach unlabeled
threads):

```yaml
action: action.name == "list_threads"
condition: |
  request.query.exists(kv,
    kv.key == "labelIds" && kv.value == "<LABEL_ID>")
result: permit
```

`<LABEL_ID>` is the same `Label_…` machine id used in
`message.labelIds` — Gmail's `labelIds` query parameter takes the
id, not the human-readable name. The list-threads view is then a
subset of the threads `agent_threads` already permits via
`get_thread`: snippets reveal nothing the agent couldn't already
fetch by id.

Threads gated only by the trusted-header signal (no label) are
not discoverable through this policy — `list_threads` can't
filter by header. In practice that's fine: the trusted header
covers agent-authored content the agent already knows about.

## Drive — suggested setup and policy patterns

Drive's gating is built around an **agent folder**: a single Drive
folder `<AGENT_FOLDER_ID>` whose direct children are the
agent-managed files. `file.parents` is one level only; for nested
folders, layer more policies.

### Read/write inside the agent folder

Permit the full content surface (file ops, comments, replies, file
labels) when the file's direct parent is `<AGENT_FOLDER_ID>`:

```yaml
action: |
  action.name in [
    "get_file", "update_file", "upload_file_update",
    "delete_file", "copy_file", "export_file", "watch_file",
    "list_file_labels", "modify_file_labels",
    "list_comments", "get_comment", "create_comment",
    "update_comment", "delete_comment",
    "list_replies", "get_reply", "create_reply",
    "update_reply", "delete_reply"
  ]
condition: |
  "<AGENT_FOLDER_ID>" in file.parents
result: permit
```

Excluded on purpose: `permissions.*` (sharing — separate trust
axis), `revisions.*` (administrative), `list_files` (covered below).

### Creating into the agent folder

`create_file` and `upload_file` accept a `parents` array on create.
Without a gate they let the agent place new files anywhere. Force
every newly-created file into `<AGENT_FOLDER_ID>` so
`agent_folder_files` can subsequently manage it:

```yaml
action: |
  action.name in ["create_file", "upload_file"]
condition: |
  "<AGENT_FOLDER_ID>" in request.body.?parents.orValue([])
result: permit
```

### Reading comments on user-authored files

Comments and replies live on the same Drive endpoints regardless of
the underlying file type, so a Docs or Sheets file owned by the
user gets its comment thread readable through this Drive policy:

```yaml
action: |
  action.name in ["list_comments", "get_comment",
                  "list_replies", "get_reply"]
condition: |
  file.ownedByMe == true
result: permit
```

### Read-only on recently-modified files (any folder)

Useful when an agent needs to summarise or quote the user's recent
work without being told the file ids upfront. Drive's `modifiedTime`
is RFC 3339, so the stdlib `timestamp()` builder casts it for CEL
duration arithmetic against the request-scoped `now`. Pair with
`ownedByMe` to keep the agent off shared files outside the folder:

```yaml
action: action.name == "get_file"
condition: |
  file.ownedByMe == true
  && file.modifiedTime != null
  && timestamp(file.modifiedTime) > now - duration("24h")
result: permit
```

`now` is fixed once per request and shared with every other policy
on the same evaluation, so two policies inspecting `now` can't
straddle a clock boundary.

### Read-only discovery

`list_files` returns metadata only (id, name, mimeType, parents,
owners). Search is the discovery primitive — without it the agent
has to be handed every file ID externally, which makes the folder
workflow unusable.

```yaml
action: action.name == "list_files"
condition: "true"
result: permit
```

## Docs — policy patterns

Docs reuses Drive's `<AGENT_FOLDER_ID>` and `ownedByMe` signals
through the `drive.file` cross-API bind on each action.

### Read/write on docs in the agent folder

```yaml
action: |
  action.name in ["get_document", "batch_update_document"]
condition: |
  "<AGENT_FOLDER_ID>" in drive.file.parents
result: permit
```

### Read-only on user-authored docs (any folder)

Useful for an agent that needs to summarise or quote earlier work.
Pair with Drive's `authored_comments_read` for comment context.

```yaml
action: action.name == "get_document"
condition: |
  drive.file.ownedByMe == true
result: permit
```

Read-only by design: writing into a doc outside the agent folder
crosses into territory where the user might not expect agent edits.
Folder placement is the load-bearing trust signal for write;
ownership alone isn't.

## Sheets — policy patterns

Same shape as Docs — `drive.file` cross-API bind, agent-folder gate
for read+write, ownership gate for read-only.

### Read/write on sheets in the agent folder

```yaml
action: |
  action.name in [
    "get_spreadsheet", "get_spreadsheet_by_data_filter",
    "batch_update_spreadsheet",
    "get_values", "update_values", "append_values", "clear_values",
    "batch_get_values", "batch_update_values", "batch_clear_values",
    "batch_get_values_by_data_filter",
    "batch_update_values_by_data_filter",
    "batch_clear_values_by_data_filter",
    "copy_sheet_to",
    "get_developer_metadata", "search_developer_metadata"
  ]
condition: |
  drive.file.parents != null
  && "<AGENT_FOLDER_ID>" in drive.file.parents
result: permit
```

Single condition, multi-action: every operation that binds
`spreadsheet` (and through it `drive.file`) sits in this one policy
to avoid fanout.

### Read-only on user-authored sheets (any folder)

```yaml
action: |
  action.name in [
    "get_spreadsheet", "get_spreadsheet_by_data_filter",
    "get_values", "batch_get_values", "batch_get_values_by_data_filter",
    "get_developer_metadata", "search_developer_metadata"
  ]
condition: |
  drive.file.ownedByMe == true
result: permit
```

## Discovery — recommended policy

The `discovery` API only serves public schema documents — there's
no user data and no authenticated surface to gate. Google client
libraries (gws-cli, gogcli, the Python google-api-python-client,
the official Workspace SDKs) hit it at startup to fetch the REST
description for each API they call, so denying it bricks the
client before it ever touches Gmail or Drive. The recommended
baseline is a permit-all, installed once per data dir:

```yaml
api: discovery
name: discovery-permit-all
action: |
  action.name in ["list_apis", "get_rest_description"]
condition: "true"
result: permit
```

Drop it in `<data-dir>/policies/discovery.yaml` (or POST to
`/_api/policies`) and stock SDKs work through the proxy without
extra wiring.

## License

Apache License 2.0 — see [LICENSE](LICENSE).
