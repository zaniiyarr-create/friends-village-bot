# Friends Village Website

A Badini Kurdish subscription website starter for the Friends Village Discord bot.

## Included
- Responsive black-and-gold landing page in Kurdish Badini.
- Annual server subscription application: 25,000 IQD / 365 days per Discord server.
- FIB payment instructions and private receipt upload (PNG/JPG/WEBP/PDF, max 5 MB).
- WhatsApp support link for `0750 604 5491`.
- Admin dashboard to review receipts and approve/reject applications.
- The Discord invite URL is shown only on the private application status page after admin approval.
- SQLite subscription database and protected bot API endpoint.
- When an approved subscription expires, the API returns `active: false`; the bot should keep its presence in the guild but disable paid features.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export ADMIN_PASSWORD_HASH="$(python -c 'from werkzeug.security import generate_password_hash; print(generate_password_hash(input(\"Admin password: \")))')"
export BOT_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
python app.py
```

Open `http://localhost:8000`. Admin: `/admin`.

## Deployment (Railway or another Python host)

1. Create a new Python web service from this folder/repository.
2. Add a persistent volume mounted at `/data`.
3. Set these environment variables:
   - `SECRET_KEY`: long random secret.
   - `ADMIN_PASSWORD_HASH`: Werkzeug password hash (generate with the command below).
   - `BOT_API_KEY`: separate long random secret shared with the bot only.
   - `DATABASE_PATH=/data/friends_village_website.sqlite3`
   - `RECEIPT_DIR=/data/friends_village_receipts`
   - `COOKIE_SECURE=1`
   - `WHATSAPP_NUMBER=9647506045491`
   - `FIB_NUMBER=0750 604 5491`
   - `DISCORD_INVITE_URL`: the exact Discord invite URL supplied by the owner.
4. Start command is provided in `Procfile`.
5. Use HTTPS. Never commit `.env`, secrets, database files, or payment receipts.

Generate an admin password hash:

```bash
python -c 'from werkzeug.security import generate_password_hash; print(generate_password_hash("CHOOSE-A-STRONG-PASSWORD"))'
```

## Bot API

Request:

```http
GET /api/subscription/123456789012345678
X-Bot-API-Key: YOUR_BOT_API_KEY
```

Active response:

```json
{"active": true, "server_name": "...", "expires_at": "...", "reason": "active"}
```

Inactive or missing subscriptions return `active: false`. The Discord bot must call this endpoint for each guild and gate only paid features; it must not leave the server when a subscription expires. The API key must never be placed in browser JavaScript.

## Important operational notes

- This first version uses manual FIB receipt review. It does not connect to FIB automatically and does not claim to verify transfers by itself.
- The owner must inspect the transfer in the official FIB app before approving an application.
- A Discord bot invite link cannot itself enforce payment. Enforcement depends on integrating the protected API check into the bot's paid-feature commands/events.
- The form asks for Discord server ID and owner ID; the admin should compare the submitted information and receipt before approval.
- Back up the `/data` volume. The database and uploaded receipts must persist across deployments.
- For production, deploy only over HTTPS and use strong, unique secrets. Do not share the admin password or bot API key.
