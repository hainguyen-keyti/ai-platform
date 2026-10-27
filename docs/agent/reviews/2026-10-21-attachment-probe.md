# 2026-10-22: the ChatGPT composer's attachment, measured on the real page (tests/provider_probe.py attachment, 00:5x, ChatGPT off the worker, PROBE_THREAD_URL the agent's own fox thread of 2026-10-09)

One 1 KB PNG attached three times, never sent. The site uploaded it each time (POST /backend-api/files, process_upload_stream). The record, verbatim:

```
[attachment] starting
[attachment: before any attach] 0 preview(s), 0 remove control(s) in the form: []; all matches: [{'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: requests while attaching] ['POST /backend-api/sentinel/chat-requirements/prepare -> 200', 'POST /backend-api/conversation/init -> 200', 'POST /backend-api/sentinel/chat-requirements/finalize -> 200', 'POST /backend-api/amphora/clear_settings_cache -> 200', 'POST /backend-api/f/conversation/prepare -> 200', 'POST /backend-api/files -> 200', 'POST /backend-api/files/process_upload_stream -> 200', 'POST /backend-api/file_upload_action_suggestions -> 200']
[attachment: after the attach, before anything else] 1 preview(s), 1 remove control(s) in the form: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]; all matches: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: after _clear_composer (select all, Backspace)] 1 preview(s), 1 remove control(s) in the form: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]; all matches: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: after goto HOME (a new chat's open)] 0 preview(s), 0 remove control(s) in the form: []; all matches: [{'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: attached again before the thread load] 1 preview(s), 1 remove control(s) in the form: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]; all matches: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: landed] https://chatgpt.com/c/6ac84a4e-e0b8-83ec-9aa9-42afdfa92af7
[attachment: after goto the thread (a follow-up's open)] 0 preview(s), 0 remove control(s) in the form: []; all matches: [{'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: back on HOME after the thread] 0 preview(s), 0 remove control(s) in the form: []; all matches: [{'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: before the remove control] 0 preview(s), 0 remove control(s) in the form: []; all matches: [{'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: summary] cleared by _clear_composer: False; survives goto HOME: False; survives goto thread: False
==================================================
1 probe(s) ran, 0 crashed
```

## The second run, 2026-10-22 01:4x (the probe extended after the tier 1 review: an attach on the thread's own page)

Two more attaches of the same 1 KB picture on the thread page, never sent. **A chip attached on the thread page survives a load of the same thread (a per-conversation draft) and not a load of the home page.** The record, verbatim:

```
[attachment] starting
[attachment: before any attach] 0 preview(s), 0 remove control(s) in the form: []; all matches: [{'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: requests while attaching] ['POST /backend-api/sentinel/chat-requirements/prepare -> 200', 'POST /backend-api/sentinel/chat-requirements/finalize -> 200', 'POST /backend-api/conversation/init -> 200', 'POST /backend-api/amphora/clear_settings_cache -> 200', 'POST /backend-api/f/conversation/prepare -> 200', 'POST /backend-api/files -> 200', 'POST /backend-api/files/process_upload_stream -> 200', 'POST /backend-api/file_upload_action_suggestions -> 200']
[attachment: after the attach, before anything else] 1 preview(s), 1 remove control(s) in the form: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]; all matches: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: after _clear_composer (select all, Backspace)] 1 preview(s), 1 remove control(s) in the form: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]; all matches: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: after goto HOME (a new chat's open)] 0 preview(s), 0 remove control(s) in the form: []; all matches: [{'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: attached again before the thread load] 1 preview(s), 1 remove control(s) in the form: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]; all matches: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: landed] https://chatgpt.com/c/6ac84a4e-e0b8-83ec-9aa9-42afdfa92af7
[attachment: after goto the thread (a follow-up's open)] 0 preview(s), 0 remove control(s) in the form: []; all matches: [{'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: back on HOME after the thread] 0 preview(s), 0 remove control(s) in the form: []; all matches: [{'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: attached on the thread page] 1 preview(s), 1 remove control(s) in the form: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]; all matches: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: after goto HOME from the thread's attach] 0 preview(s), 0 remove control(s) in the form: []; all matches: [{'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: attached on the thread page again] 1 preview(s), 1 remove control(s) in the form: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]; all matches: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: after goto the same thread again (a per-conversation draft?)] 1 preview(s), 1 remove control(s) in the form: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]; all matches: [{'tag': 'img', 'testid': '', 'label': '', 'alt': 'attachment-probe.png', 'src': 'data:image/png;base64,iVBORw0KGgoAAAANSU', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Remove attachment-probe.png', 'alt': '', 'src': '', 'inForm': True, 'visible': True}, {'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: from the thread page] survives goto HOME: False; survives goto the same thread: True
[attachment: before the remove control] 0 preview(s), 0 remove control(s) in the form: []; all matches: [{'tag': 'button', 'testid': '', 'label': 'Add files and more', 'alt': '', 'src': '', 'inForm': True, 'visible': True}]
[attachment: summary] cleared by _clear_composer: False; survives goto HOME: False; survives goto thread: False
==================================================
1 probe(s) ran, 0 crashed
```

## The third pass, 2026-10-22 02:1x: the driver's own look on the thread that held the draft, and which press takes a chip (`/tmp/attachment_clear_pass.py`, `/tmp/attachment_remove_ways.py`, no upload, no turn)

The fox thread held the two chips of the second run. With the driver's own locators (`count()`, hidden elements included): both chips counted at once after `_open` and still at +2s and +5s (no late hydration; in the second pass the previews counted 0 at the first instant while the remove controls counted 2); a plain `click()` on the remove control did not take a chip (`_drop_attachments` refused, the safe direction); **hovering the preview and then clicking the remove control took a chip in 1.7s**, twice, and the thread opened clean afterwards. A clean composer (HOME) counts 0 and 0 at once and at +3s. The records, verbatim:

```
opened the thread in 4.6s, landed https://chatgpt.com/c/6ac84a4e-e0b8-83ec-9aa9-42afdfa92af7
[the thread, at once after _open] {'previews': 2, 'previews visible': 2, 'removes': 2, 'removes visible': 2} labels ['Remove attachment-probe.png', 'Remove attachment-probe.png']
[the thread, +2s] {'previews': 2, 'previews visible': 2, 'removes': 2, 'removes visible': 2} labels ['Remove attachment-probe.png', 'Remove attachment-probe.png']
[the thread, +5s] {'previews': 2, 'previews visible': 2, 'removes': 2, 'removes visible': 2} labels ['Remove attachment-probe.png', 'Remove attachment-probe.png']
[_drop_attachments] raised ProviderError: chatgpt's composer holds an attachment of another turn that could not be removed, so nothing was sent
[the thread, after _drop_attachments] {'previews': 2, 'previews visible': 2, 'removes': 2, 'removes visible': 2} labels ['Remove attachment-probe.png', 'Remove attachment-probe.png']
[the same thread opened again, +3s (gone for good?)] {'previews': 2, 'previews visible': 2, 'removes': 2, 'removes visible': 2} labels ['Remove attachment-probe.png', 'Remove attachment-probe.png']
[a new chat (HOME), at once after _open] {'previews': 0, 'previews visible': 0, 'removes': 0, 'removes visible': 0} labels []
[a new chat (HOME), +3s] {'previews': 0, 'previews visible': 0, 'removes': 0, 'removes visible': 0} labels []

opened, chips (previews, removes): (0, 2)
[hover the preview, then click the remove control] pressed in 1.7s: (2, 2) -> (1, 1)
[hover the preview, then click the remove control] again until clean: chips now (0, 0)
the thread opened again, +3s: chips (0, 0)
```

## 2026-10-22 03:4x: the ChatGPT /v1 picture request of the real run failed at the send; reproduced read-only up to the attach (`/tmp/chatgpt_attach_then_composer.py`, one upload of the same reference, nothing sent)

The job (d8c60b81) failed as worker_error, `TimeoutError: Locator.inner_text` on the composer in `_send`, 85 s. On the real page the attach of the 2.4 MB reference brought up a dialog: **"File added to chat only. You don't have enough storage space left to save this file. Remove files to create space."**: the shared account's file storage is full (every platform upload and the probe's seven uploads are kept there). The composer itself stayed counted (1) for 12 s after the attach; the home page also held the failed job's typed prompt as a draft. The record, verbatim:

```
opened HOME in 5.6s; composer count 1
drop_attachments: nothing left; memory: off ; composer 1
reference upload-db940fab34aa4acc905aa101b3fdd5bb.png 2478403 bytes; file inputs 2
+ 1s composer 1 url https://chatgpt.com/ form text 'Use the attached image as the reference and generate a new image: the same picture as a pencil sketch Think'
+ 2s composer 1 url https://chatgpt.com/ form text 'Use the attached image as the reference and generate a new image: the same picture as a pencil sketch Think'
+ 3s composer 1 url https://chatgpt.com/ form text 'Use the attached image as the reference and generate a new image: the same picture as a pencil sketch Think'
+ 4s composer 1 url https://chatgpt.com/ form text 'Use the attached image as the reference and generate a new image: the same picture as a pencil sketch Think'
+ 5s composer 1 url https://chatgpt.com/ form text 'Use the attached image as the reference and generate a new image: the same picture as a pencil sketch Think'
+ 6s composer 1 url https://chatgpt.com/ form text 'Use the attached image as the reference and generate a new image: the same picture as a pencil sketch Think'
+ 7s composer 1 url https://chatgpt.com/ form text 'Use the attached image as the reference and generate a new image: the same picture as a pencil sketch Think'
+ 8s composer 1 url https://chatgpt.com/ form text 'Use the attached image as the reference and generate a new image: the same picture as a pencil sketch Think'
+ 9s composer 1 url https://chatgpt.com/ form text 'Use the attached image as the reference and generate a new image: the same picture as a pencil sketch Think'
+10s composer 1 url https://chatgpt.com/ form text 'Use the attached image as the reference and generate a new image: the same picture as a pencil sketch Think'
+11s composer 1 url https://chatgpt.com/ form text 'Use the attached image as the reference and generate a new image: the same picture as a pencil sketch Think'
+12s composer 1 url https://chatgpt.com/ form text 'Use the attached image as the reference and generate a new image: the same picture as a pencil sketch Think'
editables: ['DIV.ProseMirror# visible=true']
dialogs: ['File added to chat only You don’t have enough storage space left to save this file. Remove files to create space. upload-db940fab34aa4acc905aa101b3fdd5bb.png 3.']
```
