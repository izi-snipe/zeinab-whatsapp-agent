import os
import json
import logging
from flask import Flask, request, jsonify
import requests
from anthropic import Anthropic
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime, timedelta
import re

# ============================================================
# CONFIGURATION — Remplacez par vos vraies valeurs
# ============================================================
WHATSAPP_TOKEN        = os.environ.get("WHATSAPP_TOKEN", "VOTRE_TOKEN_META")
WHATSAPP_VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "un_mot_secret_que_vous_choisissez")
PHONE_NUMBER_ID       = os.environ.get("PHONE_NUMBER_ID", "VOTRE_PHONE_NUMBER_ID")
ANTHROPIC_API_KEY     = os.environ.get("ANTHROPIC_API_KEY", "VOTRE_CLE_CLAUDE")
GOOGLE_CREDENTIALS    = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")  # JSON en string
CALENDAR_ID           = os.environ.get("CALENDAR_ID", "primary")

# ============================================================
# INITIALISATION
# ============================================================
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

claude = Anthropic(api_key=ANTHROPIC_API_KEY)

# Historique des conversations par numéro de téléphone
conversation_history = {}

# ============================================================
# SYSTEM PROMPT — Persona "Awa" multilingue
# ============================================================
SYSTEM_PROMPT = """Tu es Awa, l'assistante virtuelle intelligente d'une entreprise de services informatiques.
Tu réponds aux clients de manière professionnelle, chaleureuse et efficace.

LANGUES : Tu détectes automatiquement la langue du client et tu réponds TOUJOURS dans la même langue.
- Français : réponse formelle et professionnelle
- Wolof : utilise un ton chaleureux et familier
- Arabe : réponse respectueuse et formelle (عربي)
- Anglais : professional and friendly tone

TES CAPACITÉS :
1. Répondre aux questions sur les services IT (dépannage, installation, maintenance, réseau, etc.)
2. Prendre des rendez-vous → quand un client veut un RDV, collecte : nom, date souhaitée, heure, type de service
3. Consulter les disponibilités du calendrier
4. Confirmer, modifier ou annuler des rendez-vous

PRISE DE RDV — Format JSON à retourner quand tu as toutes les infos :
Quand tu as collecté toutes les informations pour un RDV, inclus à la fin de ta réponse ce bloc JSON (invisible pour le client) :
[RDV_ACTION:{"action":"create","nom":"...","date":"YYYY-MM-DD","heure":"HH:MM","service":"...","telephone":"..."}]

Pour consulter les disponibilités :
[RDV_ACTION:{"action":"check","date":"YYYY-MM-DD"}]

Pour annuler un RDV :
[RDV_ACTION:{"action":"cancel","nom":"...","date":"YYYY-MM-DD"}]

IMPORTANT :
- Ne jamais inventer des disponibilités, dis que tu vas vérifier
- Sois concise (max 3-4 phrases par réponse sur WhatsApp)
- Termine toujours par une question ou une proposition d'aide
"""

# ============================================================
# GOOGLE CALENDAR
# ============================================================
def get_calendar_service():
    try:
        if GOOGLE_CREDENTIALS:
            creds_dict = json.loads(GOOGLE_CREDENTIALS)
            creds = service_account.Credentials.from_service_account_info(
                creds_dict,
                scopes=["https://www.googleapis.com/auth/calendar"]
            )
            return build("calendar", "v3", credentials=creds)
    except Exception as e:
        logger.error(f"Erreur Google Calendar: {e}")
    return None

def create_appointment(nom, date_str, heure_str, service, telephone):
    service_cal = get_calendar_service()
    if not service_cal:
        return False, "Erreur de connexion au calendrier"
    try:
        start_dt = datetime.strptime(f"{date_str} {heure_str}", "%Y-%m-%d %H:%M")
        end_dt   = start_dt + timedelta(hours=1)
        event = {
            "summary": f"RDV {service} — {nom}",
            "description": f"Client: {nom}\nTéléphone: {telephone}\nService: {service}",
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "Africa/Dakar"},
            "end":   {"dateTime": end_dt.isoformat(),   "timeZone": "Africa/Dakar"},
        }
        created = service_cal.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        return True, created.get("htmlLink", "")
    except Exception as e:
        logger.error(f"Erreur création RDV: {e}")
        return False, str(e)

def check_availability(date_str):
    service_cal = get_calendar_service()
    if not service_cal:
        return []
    try:
        start = datetime.strptime(date_str, "%Y-%m-%d")
        end   = start + timedelta(days=1)
        events_result = service_cal.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start.isoformat() + "Z",
            timeMax=end.isoformat() + "Z",
            singleEvents=True,
            orderBy="startTime"
        ).execute()
        return events_result.get("items", [])
    except Exception as e:
        logger.error(f"Erreur vérif dispo: {e}")
        return []

def cancel_appointment(nom, date_str):
    service_cal = get_calendar_service()
    if not service_cal:
        return False, "Erreur de connexion"
    try:
        start = datetime.strptime(date_str, "%Y-%m-%d")
        end   = start + timedelta(days=1)
        events_result = service_cal.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start.isoformat() + "Z",
            timeMax=end.isoformat() + "Z",
            q=nom,
            singleEvents=True
        ).execute()
        events = events_result.get("items", [])
        if not events:
            return False, "Aucun RDV trouvé"
        service_cal.events().delete(calendarId=CALENDAR_ID, eventId=events[0]["id"]).execute()
        return True, "RDV annulé"
    except Exception as e:
        return False, str(e)

# ============================================================
# TRAITEMENT DES ACTIONS RDV
# ============================================================
def process_rdv_action(action_json, telephone):
    action = action_json.get("action")
    if action == "create":
        success, result = create_appointment(
            nom       = action_json.get("nom", "Client"),
            date_str  = action_json.get("date"),
            heure_str = action_json.get("heure"),
            service   = action_json.get("service", "Service IT"),
            telephone = telephone
        )
        return success, result
    elif action == "check":
        events = check_availability(action_json.get("date"))
        return True, events
    elif action == "cancel":
        return cancel_appointment(action_json.get("nom"), action_json.get("date"))
    return False, "Action inconnue"

# ============================================================
# CLAUDE — Générer une réponse
# ============================================================
def get_ai_response(phone_number, user_message):
    if phone_number not in conversation_history:
        conversation_history[phone_number] = []

    conversation_history[phone_number].append({
        "role": "user",
        "content": user_message
    })

    # Limiter l'historique à 20 messages
    if len(conversation_history[phone_number]) > 20:
        conversation_history[phone_number] = conversation_history[phone_number][-20:]

    try:
        response = claude.messages.create(
            model      = "claude-sonnet-4-20250514",
            max_tokens = 1000,
            system     = SYSTEM_PROMPT,
            messages   = conversation_history[phone_number]
        )
        assistant_message = response.content[0].text

        # Extraire une éventuelle action RDV
        rdv_pattern = r'\[RDV_ACTION:({.*?})\]'
        rdv_match   = re.search(rdv_pattern, assistant_message, re.DOTALL)
        clean_message = re.sub(rdv_pattern, '', assistant_message).strip()

        # Traiter l'action RDV si présente
        if rdv_match:
            try:
                action_data = json.loads(rdv_match.group(1))
                success, result = process_rdv_action(action_data, phone_number)
                if action_data.get("action") == "create" and success:
                    clean_message += "\n\n✅ Votre rendez-vous a bien été enregistré dans notre agenda !"
                elif action_data.get("action") == "check" and success:
                    if result:
                        slots = [e.get("summary", "") for e in result]
                        clean_message += f"\n\n📅 Créneaux déjà pris ce jour : {', '.join(slots)}"
                    else:
                        clean_message += "\n\n📅 Ce jour est entièrement disponible !"
            except json.JSONDecodeError:
                logger.error("Erreur parsing JSON RDV")

        conversation_history[phone_number].append({
            "role": "assistant",
            "content": clean_message
        })
        return clean_message

    except Exception as e:
        logger.error(f"Erreur Claude: {e}")
        return "Désolé, une erreur est survenue. Veuillez réessayer."

# ============================================================
# ENVOI DE MESSAGE WHATSAPP
# ============================================================
def send_whatsapp_message(to, message):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        logger.info(f"Message envoyé à {to}")
        return True
    except Exception as e:
        logger.error(f"Erreur envoi WhatsApp: {e}")
        return False

# ============================================================
# WEBHOOK META
# ============================================================
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """Vérification du webhook par Meta"""
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("Webhook vérifié avec succès !")
        return challenge, 200
    return "Token invalide", 403

@app.route("/webhook", methods=["POST"])
def receive_message():
    """Réception des messages WhatsApp"""
    try:
        data = request.get_json()
        logger.info(f"Données reçues: {json.dumps(data, indent=2)}")

        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return jsonify({"status": "no_message"}), 200

        msg = messages[0]
        phone_number = msg.get("from")
        msg_type     = msg.get("type")

        if msg_type == "text":
            user_text = msg["text"]["body"]
            logger.info(f"Message de {phone_number}: {user_text}")

            # Générer la réponse IA
            ai_response = get_ai_response(phone_number, user_text)

            # Envoyer la réponse
            send_whatsapp_message(phone_number, ai_response)

        elif msg_type == "audio":
            send_whatsapp_message(phone_number,
                "Je suis désolée, je ne peux pas encore traiter les messages vocaux. "
                "Pouvez-vous écrire votre message ? 😊")

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logger.error(f"Erreur webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "Agent Awa actif ✅", "version": "1.0"}), 200

# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
