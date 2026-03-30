# 🤖 Guide de déploiement — Agent WhatsApp "Awa"

## ÉTAPE 1 — Compte Meta Developer

1. Allez sur https://developers.facebook.com
2. Créez une nouvelle application → choisissez "Business"
3. Ajoutez le produit **WhatsApp**
4. Dans "WhatsApp > Configuration API" :
   - Notez votre **PHONE_NUMBER_ID**
   - Générez un **Token d'accès permanent**
5. Dans "WhatsApp > Configuration du Webhook" :
   - URL du webhook : https://VOTRE_URL.railway.app/webhook
   - Token de vérification : le mot secret que vous choisissez (ex: awa_secret_2024)
   - Souscrivez à : messages

---

## ÉTAPE 2 — Google Calendar API

1. Allez sur https://console.cloud.google.com
2. Créez un nouveau projet
3. Activez l'API **Google Calendar**
4. Allez dans "IAM et admin > Comptes de service"
5. Créez un compte de service → téléchargez le fichier JSON
6. Ouvrez Google Calendar → partagez votre agenda avec l'email du compte de service
   (ex: awa-agent@mon-projet.iam.gserviceaccount.com) avec droits "Modifier les événements"

---

## ÉTAPE 3 — Clé Claude API

1. Allez sur https://console.anthropic.com
2. Créez une clé API
3. Notez-la bien (elle ne s'affiche qu'une fois)

---

## ÉTAPE 4 — Déploiement sur Railway (GRATUIT)

1. Créez un compte sur https://railway.app
2. Cliquez "New Project" → "Deploy from GitHub"
   (uploadez vos fichiers : app.py, requirements.txt, Procfile)
3. Ajoutez les variables d'environnement dans Railway :

| Variable                  | Valeur                          |
|---------------------------|---------------------------------|
| WHATSAPP_TOKEN            | Votre token Meta                |
| VERIFY_TOKEN              | awa_secret_2024                 |
| PHONE_NUMBER_ID           | Votre Phone Number ID           |
| ANTHROPIC_API_KEY         | sk-ant-...                      |
| GOOGLE_CREDENTIALS_JSON   | Contenu du fichier JSON (tout)  |
| CALENDAR_ID               | primary (ou votre email)        |

4. Railway vous donne une URL publique → utilisez-la pour le webhook Meta

---

## ÉTAPE 5 — Test

Envoyez un message WhatsApp à votre numéro de test Meta.
Exemples de messages à tester :
- "Bonjour, je voudrais prendre un rendez-vous"
- "I need help with my computer"
- "Xam na problem bi ak ordinateur bi"
- "أحتاج مساعدة في الكمبيوتر"

---

## 🔧 Dépannage

- Webhook 403 → Vérifiez que VERIFY_TOKEN est identique dans Railway et Meta
- Pas de réponse → Vérifiez les logs Railway (onglet "Deployments > View Logs")
- Erreur Google → Vérifiez que l'email du compte de service a accès à l'agenda
