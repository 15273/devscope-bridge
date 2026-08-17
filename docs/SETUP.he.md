# הפעלה וחיבור — DevScope (macOS)

English version: [SETUP.md](SETUP.md)

DevScope = תוסף Chrome + שרת מקומי (בריג) על `127.0.0.1:7878`.  
הסוכן הוא ה־CLI של Claude שכבר מותקן אצלך. אין שרת בענן של DevScope.

התיקייה הזו עצמאית. אין תלות במוצר אחר.

---

## דרישות

1. Python 3.11 או חדש יותר (`python3 --version`)
2. Node 18+ (`node --version`) — רק לבנייה הראשונה של התוסף
3. Claude CLI מחובר:

   ```bash
   which claude
   claude login
   ```

4. Chrome

---

## שלב א — התקנת הבריג

פתח טרמינל **בתוך תיקיית `devscope`**:

```bash
cd /path/to/devscope
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

הרצה חד־פעמית (לחיבור ראשון):

```bash
devscope-bridge
```

אמור להופיע:

```
Dev Bridge started. Token: …
```

בחלון אחר:

```bash
curl http://127.0.0.1:7878/health
```

אם חוזר JSON עם `"ok": true` — הבריג חי. השאר את התהליך רץ עד סוף שלב ג, או עבור לשלב ד.

הטוקן נשמר ב־`~/.dev-bridge/token` ונשאר זהה אחרי ריסטארט.

---

## שלב ב — בניית התוסף וטעינה ב־Chrome

```bash
cd /path/to/devscope/extension
npm install
npm run build
```

הפלט הוא `extension/dist/`.

ב־Chrome:

1. גלוש ל־`chrome://extensions`
2. הפעל **מצב מפתח / Developer mode**
3. **Load unpacked** → בחר את התיקייה **`dist`** (לא את `src`)
4. העתק את ה־**ID** של התוסף (32 תווים על הכרטיס)

לחיצה על האייקון פותחת את הפאנל הצדדי.

---

## שלב ג — חיבור התוסף לבריג

עצור את הבריג (Ctrl+C) והפעל מחדש **עם מזהה התוסף** — אחרת CORS חוסם:

```bash
cd /path/to/devscope
source .venv/bin/activate
export BRIDGE_EXTENSION_ID="chrome-extension://PASTE_ID"
devscope-bridge
```

בפאנל הצדדי:

1. גלגל שיניים (Settings)
2. הדבק את הטוקן:

   ```bash
   cat ~/.dev-bridge/token
   ```

3. Save / Test connection

הנקודה ליד החיבור אמורה להיות **ירוקה**.

**צ'אט ראשון:** New chat → בחר תיקיית פרויקט (הקוד שלך) → שלח הודעה.  
כדי שהסוכן יפעל בדפדפן: קשור טאב (כפתור הגלובוס בקומפוזר).

---

## שלב ד — הרצה ברקע (מומלץ ב־Mac)

אחרי ש־`.venv` קיים:

```bash
cd /path/to/devscope
chmod +x scripts/install-macos-service.sh
./scripts/install-macos-service.sh
```

מה זה עושה:

- כותב `~/Library/LaunchAgents/com.devscope.bridge.plist`
- עולה עם ההתחברות למערכת
- KeepAlive
- לוג: `~/.dev-bridge/bridge.log`

```bash
# לוג חי
tail -f ~/.dev-bridge/bridge.log

# עצירה
launchctl bootout "gui/$(id -u)/com.devscope.bridge"

# הפעלה מחדש אחרי שינוי קוד
launchctl kickstart -k "gui/$(id -u)/com.devscope.bridge"
```

אם `/health` לא עונה אחרי כמה שניות — קרא את הלוג. לא מריצים `uvicorn --workers 2`. תהליך אחד בלבד.

---

## שלב ה — כלי MCP (דפדפן / וואטסאפ / ג'ימייל)

Claude רואה את הכלים רק אם יש `.mcp.json` בפרויקט של הצ'אט, **או** אחרי רישום גלובלי.

**הכי פשוט:** ב־New chat בחר כפרויקט את תיקיית `devscope` עצמה (יש בה `.mcp.json`).

**או** העתק את `.mcp.json` לתיקיית הפרויקט שלך.

רישום גלובלי:

```bash
cd /path/to/devscope
source .venv/bin/activate
python -m devscope_bridge.setup_mcp
claude mcp list
```

חשוב: ה־`python3` שב־`.mcp.json` חייב להיות אותו פייתון שבו מותקן `devscope_bridge` (לכן `source .venv/bin/activate`). אם לא — שנה ב־`.mcp.json` את `command` ל־`/path/to/devscope/.venv/bin/python`.

OAuth אופציונלי:

```bash
GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python -m devscope_bridge.gmail.authorize_gmail
GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python -m devscope_bridge.calendar.authorize_calendar
```

הטוקנים נשמרים תחת `~/.dev-bridge/` ולא נכנסים לגיט.

---

## תקלות נפוצות

| מה רואים | מה לעשות |
|---|---|
| Connection refused על `:7878` | הבריג לא רץ. `devscope-bridge` או Kickstart ל־LaunchAgent |
| Health תקוע / Offline למרות שרץ | לוג `~/.dev-bridge/bridge.log`. kickstart מחדש |
| 403 | הטוקן בתוסף לא תואם — הדבק שוב מ־`~/.dev-bridge/token` |
| חיבור אפור, health 200 | חסר `BRIDGE_EXTENSION_ID` — הפעל מחדש עם ה־ID |
| `claude: command not found` | Claude לא ב־PATH של תהליך הבריג. התקן דרך `scripts/install-macos-service.sh` |
| `503 Browser client not connected` | פתח את הפאנל וקשור טאב |
| בנית מחדש ולא רואה שינוי בתוסף | ב־`chrome://extensions` לחץ Reload על כרטיס DevScope |

---

## להפוך לריפו ציבורי

```bash
cd /path/to/devscope
git init
git add .
git status    # וידוא שאין .env / token / סודות
git commit -m "Initial public snapshot of DevScope"
gh repo create devscope --public --source=. --remote=origin --push
```

לפני Push חפש `token` / `eyJ` / סיסמאות. ב־snapshot הזה אין אישורים חיים.
