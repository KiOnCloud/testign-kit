# Research 01: Claude in Chrome, Chrome remote debugging, Figma MCP limits

Checked: 2026-11-19 (Asia/Tokyo). Read-only research; the only file written is this report.

## Bottom line

1. **Subagents get the Chrome tools.** Subagents inherit the parent session's MCP tools, including background subagents. The docs list no exception for `claude-in-chrome`. Every subagent shares the session's one browser connection and one tab group, and no per-subagent isolation is documented. Run test cases one at a time.
2. **The Chrome 136 rule still holds.** On branded Chrome for Windows, macOS and Linux, `--remote-debugging-port` and `--remote-debugging-pipe` are refused for the default user data directory. Current Chromium `main` still enforces this. The one way into the default profile is the Chrome 144+ `chrome://inspect` approval mode. That mode shows a dialog for every connection, and its HTTP `/json` endpoints return 404.
3. **Figma limits, Full/Dev seats:** 200 calls/day on Professional and Organization, at 10/min and 15/min respectively; Enterprise allows 600/day at 20/min. **View/Collab seats and Starter plans:** 20 calls per month. `get_metadata` returns structure only: IDs, names, types, positions and sizes. Use `get_design_context` to get text.

## Q1. Claude Code + Claude in Chrome

| Fact | Finding | Source |
|---|---|---|
| Subagent tool inheritance | "Subagents inherit the built-in tools and MCP tools available in the main conversation". A background subagent (the default) "keeps every MCP tool" and only loses some built-in tools. Removed from every subagent: `AskUserQuestion`, `EnterPlanMode`, `WaitForMcpServers`, `Workflow`, and a few others. The docs list no Chrome exception. | [sub-agents#available-tools](https://code.claude.com/docs/en/sub-agents#available-tools) |
| Subagents using Chrome in practice | Changelog 2.1.323: "Fixed some Claude in Chrome tool calls, such as `browser_batch`, not showing the tool's name ... in a subagent's progress". This implies subagents call these tools in normal use. | [changelog](https://code.claude.com/docs/en/changelog) |
| Plugin-agent caveat | Plugin subagents ignore `mcpServers`, `hooks` and `permissionMode`. Inherited tools still arrive when `tools` is omitted. If a plugin agent sets `tools`, it must list `mcp__claude-in-chrome__*` explicitly. | [sub-agents](https://code.claude.com/docs/en/sub-agents) (frontmatter and tool-filter sections) |
| Permission prompts from subagents | A background subagent's prompts show up in the main session. A grant that lasts "for the rest of the session" applies to the whole session. Browser prompts read "Claude in Chrome wants to" and can allow all actions on a site for the session. | [sub-agents](https://code.claude.com/docs/en/sub-agents#tools-permissions-and-results-of-background-subagents), [chrome](https://code.claude.com/docs/en/chrome) |
| Plan / auth | Requires a direct Anthropic plan (Pro, Max, Ultra, Team or Enterprise) and sign-in with `/login`. With an API key or a `claude setup-token` token, Chrome stays off even with `--chrome`. Not available through Bedrock, Google Cloud Agent Platform or Foundry. Off under ZDR. Off by default under HIPAA, where an Owner can turn it on. | [chrome#prerequisites](https://code.claude.com/docs/en/chrome#prerequisites) |
| Extension version | Claude in Chrome 1.0.36 or later, from the Chrome Web Store. | [chrome](https://code.claude.com/docs/en/chrome) |
| How to enable | Launch with `claude --chrome`, or run `/chrome` to turn it on by default (setting `claudeInChromeDefaultEnabled`; env var `CLAUDE_CODE_ENABLE_CFC`). A project's `.claude/settings*.json` **cannot** turn it on; Claude Code ignores that setting and prints a warning. `/chrome` also selects the browser when more than one is connected (this matches `list_connected_browsers` / `select_browser`). | [chrome](https://code.claude.com/docs/en/chrome#project-settings-cant-turn-on-chrome) |
| OS | The docs give native-messaging host paths for macOS, Linux and Windows. "Chrome integration isn't supported in Windows Subsystem for Linux (WSL)." No explicit OS list exists, so OS support is inferred from those host paths. | [chrome](https://code.claude.com/docs/en/chrome) |
| Browsers | Claude Code docs: Chrome and Edge work, and Claude Code also detects Brave, Arc, Vivaldi and Opera. **Conflict:** the support article says only Google Chrome is supported, "not ... other Chromium-based web browsers". Plan for Chrome only. | [chrome](https://code.claude.com/docs/en/chrome), [support 12012173](https://support.claude.com/en/articles/12012173-getting-started-with-claude-in-chrome) |
| Cloud / other modes | The Chrome page does not cover cloud sessions. Changelog entries (2.1.293 and others) show claude.ai cloud sessions reaching the user's browser over the bridge. Code Mode cannot use Chrome. `claude remote-control` sessions keep Chrome off unless started with `--chrome`. | [changelog](https://code.claude.com/docs/en/changelog), [code-mode](https://code.claude.com/docs/en/code-mode), [remote-control](https://code.claude.com/docs/en/remote-control) |
| Login state | "Claude opens new tabs for browser tasks and shares your browser's login state, so it can access any site you're already signed into." | [chrome](https://code.claude.com/docs/en/chrome) |
| Login pages / CAPTCHA | "When Claude encounters a login page or CAPTCHA, it pauses and asks you to handle it manually." The Desktop Browser pane uses the same safety model: Claude "won't ... bypass CAPTCHAs without your input". The extension can also request logins from 1Password (beta, macOS). | [chrome](https://code.claude.com/docs/en/chrome), [desktop](https://code.claude.com/docs/en/desktop), [support 12012173](https://support.claude.com/en/articles/12012173-getting-started-with-claude-in-chrome) |
| JS dialogs | `alert`, `confirm` and `prompt` block browser events. The user must dismiss them by hand and then tell Claude to continue. | [chrome#browser-not-responding](https://code.claude.com/docs/en/chrome#browser-not-responding) |
| Tabs | Claude opens new tabs and collects them in "a Chrome tab group tied to your session". `/clear` closes the group. `/resume` or exit closes it only if it holds nothing but empty new tabs. `tabs_context_mcp` with `createIfEmpty` prompts in plan mode. | [chrome](https://code.claude.com/docs/en/chrome) |
| Concurrency | Tab groups are isolated **per session**: changelog 2.1.186 fixed "Chrome tab-group isolation ... for concurrent CLI sessions". On Windows, named-pipe `EADDRINUSE` means "Close any other Claude Code sessions that might be using Chrome". The docs say nothing about parallel subagents inside one session. The extension's service worker can go idle in long sessions; recover with `/chrome`, then "Reconnect extension". | [changelog](https://code.claude.com/docs/en/changelog), [chrome](https://code.claude.com/docs/en/chrome) |
| Org mismatch | The extension must be signed in to the same claude.ai organization as Claude Code. Otherwise tools return "Browser extension is not connected". The extension also needs to reach `bridge.claudeusercontent.com`. | [chrome](https://code.claude.com/docs/en/chrome), [network-config](https://code.claude.com/docs/en/network-config) |

## Q2. Chrome remote debugging (136+) and a dependency-free client

**Status: still true.** The Chrome blog (2025-03-17) says: "from Chrome 136 ... `--remote-debugging-port` and `--remote-debugging-pipe` ... will no longer be respected if attempting to debug the default Chrome data directory. These switches must now be accompanied by the `--user-data-dir` switch to point to a non-standard directory." A non-default directory "uses a different encryption key". Chrome for Testing "will continue to respect the existing behavior".
Source: https://developer.chrome.com/blog/remote-debugging-port

**Current enforcement in source (Chromium `main`, read 2026-11-19).** `IsRemoteDebuggingAllowed()` in [chrome/browser/devtools/remote_debugging_server.cc](https://chromium.googlesource.com/chromium/src/+/main/chrome/browser/devtools/remote_debugging_server.cc) works as follows:
- The check applies when `GOOGLE_CHROME_BRANDING` is set on Windows, macOS or Linux.
- It returns `kDisabledByDefaultUserDataDir` when the directory is the default one.
- The pipe branch and the port branch both call it.
- The default-dir check is off for unbranded Chromium builds. The `DevToolsRemoteDebuggingAllowed` policy can also disable debugging.
- On failure the switch is skipped and no server starts.

The current DevTools-MCP docs (updated 2026-10-12) still say a custom `--user-data-dir` is required for the port route ([configuration](https://developer.chrome.com/docs/devtools/agents/get-started/configuration)).

**Exception: approval mode on the default profile (Chrome 144+).**
- The user turns it on at `chrome://inspect/#remote-debugging`.
- "every time [a client] requests a remote debugging session, Chrome will show a dialog". The "controlled by automated test software" banner shows while a session is active ([blog, 2025-12-16](https://developer.chrome.com/blog/chrome-devtools-mcp-debug-your-browser-session); [auto-connect docs](https://developer.chrome.com/docs/devtools/agents/use-cases/auto-connect)).
- In source this runs as `RemoteDebuggingServerMode::kWithApprovalOnly`. In that mode `/json*`, the discovery page and frontend requests get `Send404` ([devtools_http_handler.cc](https://chromium.googlesource.com/chromium/src/+/main/content/browser/devtools/devtools_http_handler.cc)).
- Clients find the endpoint by reading `<user-data-dir>/DevToolsActivePort` (port, then a WS path) and connecting to `ws://127.0.0.1:<port><path>`. That is how chrome-devtools-mcp does it ([BrowserManager.ts](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/src/BrowserManager.ts)).
- On macOS, reading that file can fail with `EPERM` until the terminal is granted Chrome access under Files & Folders ([troubleshooting](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/troubleshooting.md)).

**Python stdlib only.** Plainly: every CDP route except the pipe needs a WebSocket, and the stdlib has no WebSocket client. The options, in order:

1. **Hand-rolled RFC 6455 client over `socket` (recommended, about 100 to 150 lines).**
   - Send an HTTP `Upgrade` with a random 16-byte base64 `Sec-WebSocket-Key`.
   - Check that `Sec-WebSocket-Accept` equals `base64(sha1(key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"))`, using `hashlib` and `base64`.
   - Mask every client frame. Handle the 7/16/64-bit length forms, continuation frames, ping/pong and close.
   - This works the same on macOS and Windows, in both port mode and approval mode.
   - In port mode, `urllib` can fetch `/json/version` to get `webSocketDebuggerUrl`. In approval mode, read `DevToolsActivePort` instead.
2. **`--remote-debugging-pipe`.** Chrome reads CDP on fd 3 and writes on fd 4, with NUL-delimited JSON (the default, non-CBOR mode).
   - This needs no WebSocket, but the script must **launch** Chrome itself, so it cannot attach to a running browser.
   - It still needs a non-default `--user-data-dir` on branded Chrome.
   - POSIX: `subprocess.Popen(pass_fds=...)` handles it.
   - Windows: Chrome uses `--remote-debugging-io-pipes=<handles>` instead ([devtools_agent_host_impl.cc](https://chromium.googlesource.com/chromium/src/+/main/content/browser/devtools/devtools_agent_host_impl.cc)). Python's `pass_fds` is POSIX-only, so a stdlib Windows version is **unconfirmed** and awkward.

**Extensions in a non-default `--user-data-dir`.** It is an ordinary separate profile. The user installs the extension from the Web Store and signs in to Claude there, and to every app under test, because cookies are not shared with the default profile. Two caveats:
- **Native-messaging gotcha (source-confirmed).** On macOS and Linux, Chrome looks for user-level native-messaging hosts in `<user-data-dir>/NativeMessagingHosts` (`DIR_USER_NATIVE_MESSAGING` = `DIR_USER_DATA` + `NativeMessagingHosts`, [chrome_paths.cc](https://chromium.googlesource.com/chromium/src/+/main/chrome/common/chrome_paths.cc)). Claude Code writes its host manifest only under the default directory (`~/Library/Application Support/Google/Chrome/NativeMessagingHosts/...`). A custom profile on macOS will therefore **not find it** unless the file is copied there. Windows uses the HKCU registry, which does not depend on the profile.
- **Unconfirmed:** whether local Claude Code to extension traffic still needs native messaging or can run over the `bridge.claudeusercontent.com` WebSocket alone. The docs mention both. Test it in the spike before relying on a custom profile.

## Q3. Figma remote MCP server

**Rate limits** ([rate-limits-access](https://developers.figma.com/docs/figma-mcp-server/rate-limits-access/); the old `plans-access-and-permissions` page now redirects there):

| Seat | Starter | Professional | Organization | Enterprise |
|---|---|---|---|---|
| View, Collab | up to 20 / month | up to 20 / month | up to 20 / month | up to 20 / month |
| Full, Dev | — | 200 / day, 10 / min | 200 / day, 15 / min | 600 / day, 20 / min |

- Per-minute limits apply on top of the daily or monthly caps.
- Education plans get the same limits as Full/Dev on Professional.
- Limits cover read tools. Write tools are exempt (`add_code_connect_map`, `create_new_file`, `generate_figma_design`, `whoami`, and others). "Figma may change rate limits at any time."
- **Conflict:** the GitHub [figma/mcp-server-guide README](https://github.com/figma/mcp-server-guide) still says "up to 6 tool calls per month" for Starter and View/Collab, and ties Full/Dev to REST API Tier 1. Git blame dates that line to 2025-10-28, so it is stale. Trust the developer docs (20/month).
- The help-center page "What if I'm rate-limited?" covers **REST API** limits (6/month on paid plans for View/Collab). It notes that the plan owning the **file** decides the limit, so a Starter-team file gets Starter limits even for a paid Full seat. The page says the MCP server "applies separate rules" ([help 34963238552855](https://help.figma.com/hc/en-us/articles/34963238552855)).
- Planning math: one case typically takes `get_metadata` + `get_screenshot` + `get_design_context`, or about 3 calls. A Pro Full seat can then import roughly 66 screens a day at most, at 10 calls a minute. A View seat can import 6 screens a month.

**`get_metadata` content.** Official text: "Returns a lightweight XML outline of your selection with basic properties only: layer IDs, names, types, positions, and sizes". Without a node ID it lists the file's top-level pages ([tools-and-prompts](https://developers.figma.com/docs/figma-mcp-server/tools-and-prompts/)). It does **not** return text characters, which matches what you observed. Text-layer names often equal their text because Figma names text layers after their content until renamed (general Figma behaviour, not confirmed on this page), but that is unreliable. For text, use `get_design_context`, which returns code with the text. `use_figma` (remote only) can also inspect content. Whether `use_figma` reads count toward rate limits is unconfirmed.

## Limitations and open questions

- Nobody has tested parallel subagents driving one tab group. The docs neither forbid nor support it, so keep execution serial.
- The local Claude Code to extension transport (native messaging vs bridge) is undocumented. This decides whether a custom-profile CDP fallback can coexist with the extension on macOS.
- The OS list for the Chrome integration is inferred from host paths and is not stated anywhere.
- Browser support conflicts between the Claude Code docs and the support article.
- Figma limits apply per user and per file plan. Whether limits are pooled across teams is not documented.
- I did not run any local experiment: no Chrome launch and no Figma calls.
