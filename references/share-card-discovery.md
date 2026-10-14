# From a shared card to the original article

Use this route when the screenshot is of a WeChat conversation, forwarded article card, share sheet, notification, reading list or article preview. A card's headline usually describes the post, not the paper. First discover the full post; only then identify papers.

If multiple cards appear, preserve top-to-bottom `card_id` and separate each card's title, account, snippet and location. Use `{"cards": [card1, card2], "vision_provenance": {...}}` as the input to `discover`. Its output contains one plan per card. For extraction specify `--discovery work/discovery.json --card card_001`; omitting `--card` for a batch is an error to prevent accidental mixing. Keep one output folder per card. A post's `papers` array may have zero, one or many records. Use `collect` to summarize them; card count is never the expected paper count.

## Read the screenshot

Use the user's configured vision workflow. On the original installation run `vlm-vision.ps1 -ImagePath "..." -Prompt "Read the WeChat article share card. Extract only visible article title, whether it is truncated, public-account name if actually shown, visible summary, visible article URL/QR reference, and each clue's location. Separately label chat sender and chat timestamp; do not use them as account name or article date. Report unreadable text and do not complete missing words." -Channel glm-thinking -Json`.

Preserve the standardized `task_type`, `tool_used`, `confidence`, `result`, `metadata` fields. Create `work/share-card.json` from the observed `result`, with this shape:

```json
{
  "visible_title": "Exact title characters visible on the card…",
  "title_truncated": true,
  "account_name": "Only if identified as the public account",
  "visible_snippet": "Only if visible",
  "article_url": "",
  "article_date": null,
  "chat_sender": "Separate from account name; omit private names from search",
  "chat_timestamp": "Not a publication date; do not send to search",
  "vision_provenance": {"task_type": "image_reasoning", "tool_used": "actual tool", "confidence": "medium", "result": "actual observed result", "metadata": {}}
}
```

Do not search the chat sender, other messages, contact details or private annotations. If there is a readable direct link or decoded QR, prefer it to guessing from the headline. If only a thumbnail/no readable clues are visible, ask for the article link or a clearer card image and keep the reason explicit.

## Search for the original post

Run `python <skill>/scripts/paper_finder.py discover --input work/share-card.json --out work/discovery.json`. This builds queries; it does not search the web. Use available web search/browser tools to execute the relevant queries. Start with the visible title/longest untruncated fragment plus account name, preferably `site:mp.weixin.qq.com`; try a broader title/account query if the official page is not indexed. Avoid requiring a guessed missing end of the title or treating chat date as article date. Limit the initial pass to the supplied plan (usually 2–4 queries); refine once using new visible evidence if necessary.

Record at most three plausible `candidate_articles` in the discovery JSON with URL, title, account if known, snippet, source domain and reason. Search snippets are candidate clues, not proof of complete article identity. Prioritize an official page over a repost. A repost can help recover title/DOI clues, but must be labeled as secondary and not silently substituted for the original.

## Read and verify the page

Try `extract --url "candidate URL" --discovery work/discovery.json --out work/intake.json`. It retains share-card provenance and compares the fetched page's title/account with visible clues. WeChat's `activity-name`, `js_name`, `publish_time` and `og:title` are extracted when present. The script's status is conservative; missing HTML metadata may require browser inspection.

Verify both post title and public-account identity against the actual page where possible; corroborate an unknown account with a distinctive visible summary or other visible card clue. Truncated-title agreement alone is insufficient. Inspect conflicting account names or multiple similarly titled reposts. A direct captured article URL is stronger evidence, but an unexpected redirect or visibly different title still needs review. Preserve the selected URL and specific reasons in `source_verification`.

If more than one candidate remains plausible, show the small candidate list and let the user select instead of proceeding from an arbitrary article. If the page is blocked, try the controlled browser once. Then use user-provided article screenshots/text or explicitly labeled secondary text for further search. Do not claim the full original post was read when only snippets or a repost were available.

## Continue to papers

Proceed with normal extraction only after source identity is corroborated. Read the full available body and relevant images, follow the “原文链接” or paper reference where it helps, then build the paper list. Keep both `source_verification` (right post?) and each paper's `verification` (right paper?) in the report/manifest.

Report “card read, original post still unconfirmed” separately from “original post found, paper still unconfirmed”. If only secondary evidence is available, provide provisional candidates with that limitation; defer automatic paper download until both source and paper identity are adequately established.
