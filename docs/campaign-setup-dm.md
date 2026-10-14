# Create campaigns by Instagram DM

The Pi handles incoming messages to the professional Instagram account selected by `REEL_CAMPAIGN_SETUP_USERNAME`. Leave this setting empty to disable the feature. Connect the selected inbox with the same Meta app; this operator inbox starts enabled. Customer workspaces keep their own pause state.

For the managed installation, message [@reelfollowup](https://ig.me/m/reelfollowup), tap **Send template**, fill in the template and send it back. Review the campaign details and tap **Confirm campaign** within 15 minutes. The account must already be connected; unconnected senders receive the `REEL_CAMPAIGN_SETUP_SIGNUP_URL` link.

```text
Campaign:
Name: My campaign
Keyword: MYKEYWORD
Link: https://example.com/
Follow required: yes
Message: Here’s your link 👇
Button: Open link
```

One keyword per template, all Reels, following required by default. Follow-ups and public reminders start off. Confirmation creates an enabled flow; a paused account stays paused. The Flows page exposes **Set up by DM** only while the configured inbox is connected and enabled.

The bot reads the sender’s Instagram profile and verifies the connected owner account live. A username written in the message never grants access. An existing keyword is matched without case sensitivity and reuses the last matching saved campaign without altering its link, messages, Reel selection or pause state. Unfinished drafts with no link must be completed in the dashboard. If the matching campaign changes between preview and confirmation, the bot sends an updated preview and requires another confirmation.

Signed webhook delivery, owned request IDs, account generation checks and durable send claims prevent cross-account changes and repeated confirmations. No password or Instagram token is requested in a DM. The template fields are parsed as data, never executed.
