---
name: x-public-timeline-fallback
description: Read public X/Twitter profile timelines when browser login or normal page rendering is broken, using guest activation plus X GraphQL endpoints as a fallback.
---

# When to use

Use this when:
- The user asks you to inspect a public X account or summarize recent posts.
- Browser rendering is inconsistent, logged-out pages show stale or misordered posts, or the login flow fails.
- You need the latest public posts from an account without relying on a full interactive login.

Do not use this for private/protected accounts.

# Why this exists

In browser automation, x.com may:
- fail during login with onboarding/task errors or CORS-like failures,
- show public profile pages with stale, highlighted, or non-chronological posts at the top,
- return incomplete snapshots where pinned/highlighted content appears before newer posts.

The reliable fallback is X's guest flow + GraphQL profile/timeline queries.

# Steps

1. Try the normal browser path first.
   - Open `https://x.com/<screen_name>`.
   - If needed, check whether the visible timeline is clearly chronological and current.
   - If login is required and fails, do not get stuck retrying many times.

2. If browser results look suspicious, use the guest API fallback.

3. Fetch the current web bearer token from X's main JS bundle if needed.
   - In practice, X web often ships a static bearer token inside `main.<hash>.js`.
   - You can also reuse the common public web bearer token if it still works, but extracting it from the current JS is safer.

4. Activate a guest session.
   Example Python pattern:

   ```python
   import requests, urllib.parse
   bearer = '...'
   s = requests.Session()
   headers = {
       'authorization': 'Bearer ' + urllib.parse.unquote(bearer),
       'user-agent': 'Mozilla/5.0',
       'x-twitter-active-user': 'yes',
       'x-twitter-client-language': 'en',
   }
   guest = s.post('https://api.x.com/1.1/guest/activate.json', headers=headers, timeout=30).json()['guest_token']
   headers['x-guest-token'] = guest
   ```

5. Resolve the user ID with `UserByScreenName`.
   - Operation name: `UserByScreenName`
   - Example query id seen during this run: `IGgvgiOx4QZndDHuD3x9TQ`
   - Pass `variables={"screen_name":"elonmusk"}` plus the required feature flags.
   - Read `data.user.result.rest_id`.

6. Fetch the profile timeline with `UserTweets`.
   - Operation name: `UserTweets`
   - Example query id seen during this run: `x3B_xLqC0yZawOB7WQhaVQ`
   - Request a decent page size, e.g. `count=40` or `count=100`.
   - Include feature flags and field toggles expected by the web client.

7. Parse timeline entries carefully.
   - Iterate through `data.user.result.timeline.timeline.instructions[*].entries[*]`.
   - The tweet is typically at `entry.content.itemContent.tweet_results.result`.
   - If the typename is `TweetWithVisibilityResults`, unwrap `.tweet`.
   - Read text from `tweet.legacy.full_text`.
   - Read timestamp from `tweet.legacy.created_at`.
   - Read status ID from `tweet.rest_id`.

8. Do not trust entry order blindly.
   - Browser/profile order can surface highlights or pinned posts near the top.
   - Collect all returned tweets and sort by parsed `legacy.created_at` descending to find the newest one.
   - Check `entryId` for `pinned` if you need to identify pinned content.

9. Inspect media when the text is sparse.
   - If the newest post is mostly a URL or short caption, inspect attached media from `legacy.entities.media` / `legacy.extended_entities.media`.
   - Use vision analysis on `media_url_https` for a better summary.

10. Report the result with a confidence note.
   - If browser login/rendering failed and you used the guest fallback, say so briefly.
   - Distinguish between exact text and interpretive summary.

# Minimal working extraction example

```python
import requests, urllib.parse, json
from email.utils import parsedate_to_datetime

bearer = 'AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA'
s = requests.Session()
headers = {
    'authorization': 'Bearer ' + urllib.parse.unquote(bearer),
    'user-agent': 'Mozilla/5.0',
    'x-twitter-active-user': 'yes',
    'x-twitter-client-language': 'en',
}
headers['x-guest-token'] = s.post(
    'https://api.x.com/1.1/guest/activate.json',
    headers=headers,
    timeout=30,
).json()['guest_token']

features_user = {
    'hidden_profile_subscriptions_enabled': True,
    'profile_label_improvements_pcf_label_in_post_enabled': True,
    'responsive_web_profile_redirect_enabled': False,
    'rweb_tipjar_consumption_enabled': True,
    'verified_phone_label_enabled': False,
    'subscriptions_verification_info_is_identity_verified_enabled': True,
    'subscriptions_verification_info_verified_since_enabled': True,
    'highlights_tweets_tab_ui_enabled': True,
    'responsive_web_twitter_article_notes_tab_enabled': True,
    'subscriptions_feature_can_gift_premium': False,
    'creator_subscriptions_tweet_preview_api_enabled': True,
    'responsive_web_graphql_skip_user_profile_image_extensions_enabled': False,
    'responsive_web_graphql_timeline_navigation_enabled': True,
}

user = s.get(
    'https://x.com/i/api/graphql/IGgvgiOx4QZndDHuD3x9TQ/UserByScreenName',
    headers=headers,
    params={
        'variables': json.dumps({'screen_name': 'elonmusk'}, separators=(',', ':')),
        'features': json.dumps(features_user, separators=(',', ':')),
    },
    timeout=30,
).json()['data']['user']['result']

features_tweets = {
    'rweb_video_screen_enabled': False,
    'profile_label_improvements_pcf_label_in_post_enabled': True,
    'responsive_web_profile_redirect_enabled': False,
    'rweb_tipjar_consumption_enabled': True,
    'verified_phone_label_enabled': False,
    'creator_subscriptions_tweet_preview_api_enabled': True,
    'responsive_web_graphql_timeline_navigation_enabled': True,
    'responsive_web_graphql_skip_user_profile_image_extensions_enabled': False,
    'premium_content_api_read_enabled': False,
    'communities_web_enable_tweet_community_results_fetch': True,
    'c9s_tweet_anatomy_moderator_badge_enabled': True,
    'responsive_web_grok_analyze_button_fetch_trends_enabled': True,
    'responsive_web_grok_analyze_post_followups_enabled': False,
    'responsive_web_jetfuel_frame': False,
    'responsive_web_grok_share_attachment_enabled': True,
    'responsive_web_grok_annotations_enabled': True,
    'articles_preview_enabled': True,
    'responsive_web_edit_tweet_api_enabled': True,
    'graphql_is_translatable_rweb_tweet_is_translatable_enabled': True,
    'view_counts_everywhere_api_enabled': True,
    'longform_notetweets_consumption_enabled': True,
    'responsive_web_twitter_article_tweet_consumption_enabled': True,
    'tweet_awards_web_tipping_enabled': False,
    'responsive_web_grok_show_grok_translated_post': False,
    'responsive_web_grok_analysis_button_from_backend': True,
    'creator_subscriptions_quote_tweet_preview_enabled': False,
    'freedom_of_speech_not_reach_fetch_enabled': True,
    'standardized_nudges_misinfo': True,
    'tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled': True,
    'longform_notetweets_rich_text_read_enabled': True,
    'longform_notetweets_inline_media_enabled': True,
    'responsive_web_grok_image_annotation_enabled': True,
    'responsive_web_grok_imagine_annotation_enabled': True,
    'responsive_web_grok_community_note_auto_translation_is_enabled': False,
    'responsive_web_enhance_cards_enabled': False,
}
field_toggles = {
    'withPayments': False,
    'withAuxiliaryUserLabels': False,
    'withArticleRichContentState': True,
    'withArticlePlainText': False,
    'withArticleSummaryText': False,
    'withArticleVoiceOver': False,
    'withGrokAnalyze': False,
    'withDisallowedReplyControls': False,
}
obj = s.get(
    'https://x.com/i/api/graphql/x3B_xLqC0yZawOB7WQhaVQ/UserTweets',
    headers=headers,
    params={
        'variables': json.dumps({
            'userId': user['rest_id'],
            'count': 100,
            'includePromotedContent': True,
            'withQuickPromoteEligibilityTweetFields': True,
            'withVoice': True,
            'withV2Timeline': True,
        }, separators=(',', ':')),
        'features': json.dumps(features_tweets, separators=(',', ':')),
        'fieldToggles': json.dumps(field_toggles, separators=(',', ':')),
    },
    timeout=60,
).json()

items = []
for inst in obj['data']['user']['result']['timeline']['timeline']['instructions']:
    for ent in inst.get('entries', []):
        tr = ent.get('content', {}).get('itemContent', {}).get('tweet_results', {}).get('result')
        if not tr:
            continue
        if tr.get('__typename') == 'TweetWithVisibilityResults':
            tr = tr.get('tweet')
        if not tr or tr.get('__typename') != 'Tweet':
            continue
        legacy = tr.get('legacy', {})
        if legacy.get('created_at'):
            items.append((parsedate_to_datetime(legacy['created_at']), tr))

latest = max(items, key=lambda x: x[0])[1]
print(latest['rest_id'], latest['legacy']['created_at'], latest['legacy'].get('full_text'))
```

# Pitfalls

- Query IDs can change. If a hardcoded GraphQL query ID stops working, extract the current one from X's `main.<hash>.js` bundle by searching for operation names like `UserByScreenName` and `UserTweets`.
- Logged-out browser pages may show highlighted or pinned items above chronologically newer tweets.
- Some tweets have almost no text and only a media URL. Check `entities.media` and analyze the media if the user wants a meaningful summary.
- Be careful not to claim a successful login if you actually used a public fallback.

# Verification

- Confirm the latest timestamp by sorting parsed tweets by `legacy.created_at`.
- Confirm the tweet URL as `https://x.com/<screen_name>/status/<rest_id>`.
- If available, compare the latest item against the browser page and mention any ordering discrepancy.