# What the tests left in the provider accounts (for the owner to delete by hand)

Moved out of HANDOFF on 2026-10-02. Everything here holds test prompts only. The agent's rules
forbid it to delete account data or files for good, whatever the yes: the owner deletes, the
agent only keeps this list. Never bulk delete Gemini threads from this machine in one go (Google's
unusual-traffic check, 2026-09-27).

## ChatGPT (the account logged in on 2026-10-01 20:14)

- Deleted by the owner on 2026-10-02 at about 00:06: all 16 threads of
  `docs/agent/residue-to-delete-2026-10-01.json` (`scripts/purge_test_residue.py ... --yes`, each
  200), the six of the interrupted gate of 16:35 among them
- Perhaps still there, never recorded: the failed picture job of 16:37 ("a plain red circle on
  white", if its prompt went out) and the stop probe's first turn of 21:50 (Cloudflare's check
  answered it; whether a thread was made is not known)
- "Tôi tên gì?" (one turn through the platform on 2026-10-02 at 02:06, kept on purpose; platform
  conversation 143d184cf68b4a8eb34487609826acfa of a throwaway user)
- **Deleted by the owner on 2026-10-02 at about 05:29 ("done: 10 removed, 0 failed", each 200):**
  the ten threads the real gate of 2026-10-02 04:37 to 04:54 left, listed in
  `docs/agent/residue-to-delete-2026-10-02.json` (dry run "10 threads, 0 memories"): "Reply with
  the single word: pong", "a plain red circle on white", "Video script", "renamed-652179", the
  remembered word's question, two zips of a.txt and b.txt, "take your time: ping", and two plain
  turns. Not in that list because the gate never learned its thread: the picture turn that timed
  out at 302s ("vẽ cho tôi một hình vuông màu xanh" and its zip, one thread)

- The stop probe of 2026-10-02 17:39 kept its threads: 6abf8a46-1b20-83ec-96ed-036995f6b066 (a
  lighthouse picture that was stopped before it was drawn) and perhaps two conversations of an
  essay about Hà Nội's history stopped before a word was written (the page showed only a
  placeholder address, so whether the account keeps them is not known)

- The picture plan of 2026-10-02 kept its conversations: four picture turns ("vẽ cho tôi một hình
  vuông màu xanh" at 17:52 and 19:06, "vẽ cho tôi một hình tròn màu đỏ trên nền trắng" at 18:02,
  thread 6abf8f36-ba0c-83ec-b65c-32e3d83679ad, "vẽ cho tôi một ngôi sao vàng trên nền xanh đậm"
  at 19:23) and one plain turn ("Thủ đô của Nhật Bản là gì?")

- The agent's walk of 2026-10-06 (a throwaway platform user, its conversations kept): "Thủ đô
  của Pháp là gì? ..." (the prompt went out twice in one turn, the agent's typing), "Vẽ cho tôi một
  con mèo màu cam ngồi trên bậu cửa sổ." and its video script

- The image API plan's two real requests of 2026-10-09 (through /v1 with a key of the local test
  account, their platform conversations kept): thread 6ac84a4e-e0b8-83ec-9aa9-42afdfa92af7 ("a small
  red fox sitting in the snow, simple flat illustration") and thread
  6ac84b72-168c-83ec-b61f-c4ce92949979 ("the same fox at night under a sky full of stars", with the
  first picture uploaded as its reference)
- The safety plan's attachment probe (2026-10-22, `tests/provider_probe.py attachment`, two runs):
  six uploads of a 1 KB picture `attachment-probe.png` in the account's file store (each attach is a
  `POST /backend-api/files`), never sent in any message; the two draft chips it left on the fox
  thread 6ac84a4e were cleared by the third pass (hover, then the remove control), the thread opens
  clean. Nothing of the platform's users

## Gemini (the account `ke***2@gmail.com`, logged in on 2026-10-01 20:16)

By title, in the sidebar of gemini.google.com:
- "Remember this word for later ..." and "Earlier I asked you to remember a word ..." (the recall
  check, 2026-10-01 about 20:30)
- "Thủ đô của Việt Nam ..." (item 8: a chat, a picture, a video script) and "Tôi tên gì? ..."
- "pong" (the session check of 2026-10-02 01:02, kept on purpose)

- 2026-10-06: the owner's video turn "Tạo video 30s nó về cuộc sống thời AI hiện nay" (thread
  1dfbd9cdd9657b27, holds a 10s video), and the agent's walk: "Thủ đô của Nhật Bản là gì? ..."
  (b1f1f2e09440e3b3) and "Vẽ cho tôi một chú chó con màu trắng chạy trên bãi cỏ." (7bdd49792accfd7d,
  with the video script that worked at 18:23); the video plan's two videos: "Tạo video 10 giây về một
  chú mèo con đang ngủ dưới nắng bên cửa sổ." (5cbf5c7ea13d3b12, the probe) and "Tạo video 10 giây về
  một chú chó con đang chơi với quả bóng đỏ trong vườn." (4eb4bcfad516f66d, the proof)

## Gemini (the first Google account, used until 2026-09-29)

The `/app/<id>` tails left on purpose by the owner's choice of 2026-09-27: 61a5e2def2f117e6,
a85fb82fb7d62799, 27074bd3946fcf57, 239f0ba819d9963c, 1fff9e0d40c1495a, ea936f95c9f0eefe,
969da7f941ec9cc3, plus those never printed (the `settle-picture` probe's, the driver runs between
76a1e1f and 47cd59b, the real gate at d121414). 23 of the 30 approved on 2026-09-27 were deleted;
a delete that "still opens" was not done (Google refuses deletes after a burst, then blocks).

## Grok (the new account "key ti", logged in on 2026-10-01 20:13)

- The safety plan's real run of 2026-10-22 03:28 (the local test account of
  `storage/diagnostics/manual-test-account.json`): conversation d884325f-af8e-4cd4-8702-8f2fbdfe8296,
  untitled, holding the question "Thủ đô của Pháp là thành phố nào? ..." and an empty answer under
  "High Demand: Grok is under heavy usage right now. Please try again later or upgrade your plan";
  the platform's conversation stores no thread url for a failed first turn, so a delete there will
  not remove it (the orphan-thread class, parked)

- 64e4a6f6-6ead-412a-816f-f8e2b186af50 ("pong", the probe's own turn of 21:25)
- "pong" (the session check of 23:06), "Thủ đô của Pháp ..." (the stop check's plain turn) and
  the essay about Hà Nội's winter (its stopped turn)
- whatever the walled turn of 21:27 left (a walled turn can still make a thread)

- 2026-10-06, the agent's walk: "Thủ đô của Ý là gì? ..." and "Vẽ cho tôi một chiếc thuyền buồm
  trên biển lúc hoàng hôn."

## Grok (the old account, used until 2026-10-01)

- The memory leak test's two threads: ae9f4f6b-60f5-46ce-a9e9-c4f25ddcedd5 and
  7b95db0b-abc7-44ea-a15a-a9decde76645
- The real gate of 2026-09-28: 17ad1091-ee8b-4d7d-8fff-90ac375eda6d,
  7b58be36-393b-4c21-81cb-6bdd8a739d4e, 7be18593-1502-4934-8a9b-158bb7691982,
  e2560047-c0fa-40f4-afa0-5fed01e22a59
- 39 older conversations, most made by gates and probes before 72ca6ed, many with an empty title.
  With the owner's yes ten were removed on 2026-09-26 (47 became 39). The rest wait for a list the
  owner approves: a title does not say which are the owner's own

## On this machine

- In the Trash since 2026-10-01 23:00, for the owner to empty: the three old session files,
  `ai-platform-old-session-<provider>-20261001.json`. They are no longer read and still hold
  credentials (the old Grok account's login is live in its file)
- Kept gate workspaces that are no longer needed, under `$TMPDIR`: `ai-platform-acceptance-f69ugegc`,
  `-t2_wyf_a`, `-oxn_cmz3`, `-snmfc5q1`, `-4e01f7i4`, `-hye7088z`
- The platform's own test users: `/tmp/manual-test-account.json` (the agent's walk of 2026-10-06),
  `/tmp/design-review-account.json` (mock turns only),
  `/tmp/e2e_acceptance/test-account.json` and
  `test-account-gemini.json` (email and password of two throwaway users; their conversations are
  left for the owner to look at), and the throwaway users each session check registered
