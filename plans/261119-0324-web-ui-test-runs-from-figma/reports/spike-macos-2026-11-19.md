# Spike on macOS — 2026-11-19

Site: `https://dev.u-supp-u.devkarte.jp/`, project `usupp`, account roles admin, staff, client.
Run from the planning session with the tester's own Chrome (one browser connected, macOS).
Items D, H and the debug-connection half of B need the tester at the keyboard and are still open.

## Results

| Item | Result | Evidence |
|---|---|---|
| A — a subagent uses the Chrome tools | **Pass** for a general subagent. Not yet tried with a plugin agent definition. | The subagent loaded the tools with one tool search, opened its own tab in the session's tab group, read `/news` (heading お知らせ一覧, five navigation links), saved a screenshot and closed its tab. 8 tool calls, about 31 seconds, about 89k tokens. The session's other tab was untouched. |
| B — evidence as a file | **Pass without a debug connection.** | The Chrome tool's screenshot and zoom actions take `save_to_disk`. A full screenshot was saved as a JPEG; a zoom on a region (0,0)–(700,60) was saved as a 1504×130 PNG at device resolution. The files land in the session's tool-results folder, and the tool result names the path. The debug-connection route is untested and no longer required for evidence. |
| C — screen of a target node | **Partly.** Works for instance layers, not for plain nodes. | See below. |
| E — cost | Partly measured. | One read-only row: 8 tool calls, 31 s, 89k subagent tokens. Figma calls used by this spike so far: 11 (9 `get_metadata`, 2 `get_screenshot`). The fifteen-row measurement is still open. |
| F — Figma capture to a file | **Pass.** | The screenshot tool returns a short-lived image URL; the table's capture was downloaded with `curl` into a folder during planning. One call per capture. |
| G — phone-width viewport | **Fail as tried.** | `resize_window` to 390×844 reported success, but the page still saw 1680 wide (`outerWidth` and `innerWidth` unchanged). The window is probably maximised or full screen. To retry with a normal window; otherwise only a debug connection can emulate the size. |
| D — runner signs in to the test Chrome | Open. | `spike/webtest_spike.py` is written (debug pipe, standard library, macOS and Linux). Needs the tester. |
| H — switching scenarios | Open. | Needs D. |

## Item C in detail

The file's pages are named by screen: C-1.Home, C-2.About Usupp, C-3.News List, C-4.News Detail,
C-5.Inquiry, C-6.Booking Form, C-7.Booking History, C-8.My Profile, and A-1 to A-15 for the admin
side. The site's navigation matches the client pages: `/`, `/about-us`, `/news`, `/reservation`,
`/inquiry`.

- 16 of the 45 targets are instance layers (ids that start with `I`). The first id segment is the top-level instance, and a page outline (`get_metadata` on the page) contains it with its frame, for example `I2502:49325;…;2502:60003` → page C-7.Booking History, frame "Desktop - Booking History - View", layer "USU Booking Ticket". The frame name also gives the viewport (Desktop or Mobile).
- Of the five instance rows in the random sample, three were found in the two pages read (Booking History, Booking Form steps 1 and 3). The two with `6619:2926` were not in the three pages read; more pages are needed.
- 29 targets are plain nodes. `get_metadata` on such a node returns its name and local position only, never its parent. The Home page's main frame (`6599:124179`) is returned without children, so nodes inside it cannot be found through the page outline either. None of the five plain nodes in the sample was placed.

Method that follows: build a node-to-page index once per file from the page outlines (about 25
calls for the screen pages, cached with the import), use it for instance rows, and for plain nodes
let the agent propose a screen from the row's text and capture against the site's navigation,
marked low confidence for the tester to confirm.

## Other observations

- The tester's Chrome was already signed in on the test site (the header shows a user menu with マイプロフィール, 予約履歴, ログアウト). A run in that Chrome uses that session.
- Two Chrome tool results reported different sizes for the same window (viewport 1680×899 from the page reader, 1512×809 as the screenshot's coordinate frame). Coordinates from one must not be used with the other.
- Screenshots saved to disk are written by the session's tooling into its own folder; the path is specific to the client. A run would copy the file from the path the tool reports.

## Second round, in the tester's own profile

After the first round the user chose to run in the Chrome profile that is already signed in.

- Item G again, in a new window of that profile: the window opened 606 wide and `resize_window` to 390, 520 and 1440 each reported success without changing it (`outerWidth` stayed 606). The tool does not resize this window. At 606 wide the site shows its menu-button layout; its phone breakpoint is 600. Result: fail; phone-width rows go to the tester.
- One real row, end to end: row 2 ("予約確認 → 予約履歴"). Open the base URL, open the menu, find the link, save a screenshot, read the page text. The link reads 予約履歴 and the old text is absent: pass. One batched browser call did it. The saved image shows the signed-in user's name and address, so evidence images are personal data of the test account.
- Tabs opened by the session were closed afterwards.

Decisions taken by the user after this round: the tester's own profile, sign-in by hand, no debug
connection, no automatic runner, no stored account values. They are applied to the plan.

## What the first round suggested for the plan

1. Evidence no longer needs a debug connection. The orchestrator can copy the image the Chrome tool saved. Cost: the evidence then comes from the agent side, not from the server, so the server no longer vouches for the image or its URL.
2. A debug connection is then needed only for the automatic login runner. Manual sign-in in the tester's own Chrome needs no extra setup at all.
3. The screen column is filled with high confidence for about a third of the rows (instance layers) and proposed with low confidence for the rest.
4. `mobile` rows stay with the tester unless the retry of item G passes.

## Still to do

- Items D and H are dropped with the runner; `spike/webtest_spike.py` stays unrun as a record.
- Item A with a plugin agent definition; item E on fifteen rows.
- Windows.
