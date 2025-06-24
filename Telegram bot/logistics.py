import logging
import smtplib
import gspread
import traceback
import io
import os
import json
from zoneinfo import ZoneInfo
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

# --- Configuration ---
# Your bot's API token.
BOT_TOKEN = "7906935873:AAFF5dspEavs_k251lu3fgvQKhS_jSRassw"

# --- Admin & Report Configuration ---
# The Chat ID for your Admin Team's group.
TARGET_CHAT_ID = -1002848963725
# The ID of the root folder in Google Drive where submission folders will be created.
# Leave as None to create a new root folder named "Telegram Bot Submissions".
DRIVE_ROOT_FOLDER_ID = None 

# --- Google Sheets Configuration ---
# The URL of your Google Sheet.
GOOGLE_SHEET_URL = "https://docs.google.com/spreadsheets/d/1qzs6qFWJIbQaUeJhrUDU7XnFhNiuts9SLp1OWf8Kq7k/edit?usp=sharing"

# --- Bot Logic ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Define states for the new conversation flow
(
    SELECT_TYPE,
    GET_ALL_TEXT,
    GET_PHOTOS,
    CONFIRM_SUBMISSION,
) = range(4)

def get_google_services():
    """Authenticates with Google using environment variables and returns clients."""
    scopes = ["https://spreadsheets.google.com/feeds", 'https://www.googleapis.com/auth/drive']
    
    gcp_json_credentials_dict = json.loads(os.environ["GCP_CREDENTIALS_JSON"])
    creds = Credentials.from_service_account_info(gcp_json_credentials_dict, scopes=scopes)

    gspread_client = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return gspread_client, drive_service

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Displays the main welcome message and instructions."""
    context.user_data.clear()
    await update.message.reply_text(
        "Welcome to the ULD Logistics Bot.\n"
        "To start a new submission, use the /start command or the menu button."
    )
    return ConversationHandler.END


async def start_submission(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asks the user to select the submission type from a command."""
    context.user_data.clear()
    keyboard = [
        [
            InlineKeyboardButton("Inbound", callback_data="Inbound"),
            InlineKeyboardButton("Outbound", callback_data="Outbound"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Please select the submission type:", reply_markup=reply_markup)
    return SELECT_TYPE


async def start_submission_from_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asks the user to select the submission type from a button click."""
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    keyboard = [
        [
            InlineKeyboardButton("Inbound", callback_data="Inbound"),
            InlineKeyboardButton("Outbound", callback_data="Outbound"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text="Please select the submission type:", reply_markup=reply_markup)
    return SELECT_TYPE


async def get_submission_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the submission type and asks for text details."""
    query = update.callback_query
    await query.answer()
    context.user_data["submission_type"] = query.data
    
    await query.edit_message_text(text=f"You selected: {query.data}")

    instructions = (
        "Now, please provide the following details in a single message, with each item on a new line:\n"
        "1. Container/Reference Number\n"
        "2. Number of Pallets/Cartons\n"
        "3. Damage Notes/Remarks (or 'None' if not applicable)"
    )
    await context.bot.send_message(chat_id=query.message.chat_id, text=instructions)
    return GET_ALL_TEXT


async def get_all_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Parses the single multi-line message for all text data."""
    lines = update.message.text.split('\n')
    if len(lines) < 3:
        await update.message.reply_text(
            "The format seems incorrect. Please provide the three pieces of information, each on a new line."
        )
        return GET_ALL_TEXT

    context.user_data["container_number"] = lines[0].strip()
    context.user_data["quantity"] = lines[1].strip()
    context.user_data["notes"] = "\n".join(lines[2:]).strip() 

    context.user_data["photos"] = []
    reply_keyboard = [["Done Uploading"]]
    await update.message.reply_text(
        "Thank you. Now, please upload the required photos.\n"
        "Send your photos now. Press 'Done Uploading' when you are finished.",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, resize_keyboard=True
        ),
    )
    return GET_PHOTOS


async def get_photos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores photos as they are uploaded."""
    photo_file = await update.message.photo[-1].get_file()
    context.user_data["photos"].append(photo_file)
    return GET_PHOTOS


async def photos_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Finalizes photo upload and shows summary for confirmation."""
    user_data = context.user_data
    photo_count = len(user_data.get('photos', []))
    await update.message.reply_text(f"Thank you. {photo_count} photo(s) have been received.", reply_markup=ReplyKeyboardRemove())
    
    summary = (
        f"✅ *New Submission Summary*\n\n"
        f"*Type:* `{user_data['submission_type']}`\n"
        f"*Container/Reference:* `{user_data['container_number']}`\n"
        f"*Pallet/Carton Count:* `{user_data['quantity']}`\n"
        f"*Damage Notes/Remarks:*\n`{user_data['notes']}`\n\n"
        f"*Photos Uploaded:* `{photo_count}`"
    )
    await update.message.reply_text(summary, parse_mode='Markdown')
    
    reply_keyboard = [["Confirm & Submit", "Cancel"]]
    await update.message.reply_text(
        "Please review the details above. If everything is correct, press 'Confirm & Submit'.",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, resize_keyboard=True
        ),
    )
    return CONFIRM_SUBMISSION

def upload_to_drive(drive_service, container_folder_id, file_content, file_name):
    """Uploads a file from memory to a specific Google Drive folder."""
    file_metadata = {'name': file_name, 'parents': [container_folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(file_content), mimetype='image/jpeg', resumable=True)
    file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
    drive_service.permissions().create(fileId=file.get('id'), body={'type': 'anyone', 'role': 'reader'}).execute()
    return file.get('webViewLink')

def get_or_create_folder(drive_service, folder_name, parent_id=None):
    """Finds a folder by name or creates it if it doesn't exist."""
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder'"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    
    response = drive_service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    if response.get('files'):
        return response.get('files')[0].get('id')
    else:
        file_metadata = {'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder'}
        if parent_id:
            file_metadata['parents'] = [parent_id]
        folder = drive_service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')

def send_email_report(subject: str, html_body: str):
    """Sends a report via email using credentials from environment variables."""
    try:
        smtp_server = os.environ["SMTP_SERVER"]
        smtp_port = int(os.environ.get("SMTP_PORT", 587))
        email_sender = os.environ["EMAIL_SENDER"]
        email_password = os.environ["EMAIL_PASSWORD"]
        email_recipients = os.environ["EMAIL_RECIPIENTS"].split(',')

        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = email_sender
        msg['To'] = ", ".join(email_recipients)

        part = MIMEText(html_body, 'html')
        msg.attach(part)

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(email_sender, email_password)
            server.sendmail(email_sender, email_recipients, msg.as_string())
        logger.info("Email sent successfully!")
    except KeyError:
        logger.warning("Email environment variables not set. Skipping email notification.")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        logger.error(traceback.format_exc())

async def submit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Finalizes submission, uploads to Drive, sends reports, and updates Google Sheet."""
    user = update.message.from_user
    user_data = context.user_data
    
    # Get current time and convert to Singapore time using the standard library
    utc_now = datetime.now(ZoneInfo("UTC"))
    submission_time = utc_now.astimezone(ZoneInfo("Asia/Singapore"))

    await update.message.reply_text("Submission confirmed! Uploading photos to Google Drive...", reply_markup=ReplyKeyboardRemove())

    drive_photo_links = []
    try:
        gspread_client, drive_service = get_google_services()
        photo_files = user_data.get("photos", [])
        if photo_files:
                root_folder_id = DRIVE_ROOT_FOLDER_ID or get_or_create_folder(drive_service, "Telegram Bot Submissions")
                container_folder_id = get_or_create_folder(drive_service, user_data['container_number'], root_folder_id)
                
                for i, photo_file in enumerate(photo_files):
                    file_content = await photo_file.download_as_bytearray()
                    file_name = f"photo_{i+1}_{submission_time.strftime('%Y-%m-%d_%H-%M-%S')}.jpg"
                    drive_link = upload_to_drive(drive_service, container_folder_id, file_content, file_name)
                    drive_photo_links.append(drive_link)
    except Exception as e:
        logger.error("Failed to upload to Google Drive:")
        logger.error(traceback.format_exc())
        await update.message.reply_text("An error occurred while uploading photos to Google Drive. Please notify an admin.")
    
    # Define the new timestamp format
    formatted_timestamp = submission_time.strftime("%d/%m/%Y %H:%M:%S")

    # --- Send Email Notification ---
    email_subject = f"Container Submission {user_data['submission_type']}: {user_data['container_number']} @ {formatted_timestamp}"
    
    qa_list = [
        {"question": "Submission Type", "answer": user_data['submission_type']},
        {"question": "Container/Reference Number", "answer": user_data['container_number']},
        {"question": "Number of Pallets/Cartons", "answer": user_data['quantity']},
        {"question": "Damage Notes/Remarks", "answer": user_data['notes']}
    ]

    email_html_body = f"<h2>{email_subject}</h2><ul>"
    for pair in qa_list:
        email_html_body += f"<li><b>{pair['question']}</b>: {pair['answer']}</li>"
    email_html_body += "</ul>"

    if drive_photo_links:
        email_html_body += "<h3>Uploaded File Links:</h3><ul>"
        for link in drive_photo_links:
            email_html_body += f'<li><a href="{link}">{link}</a></li>'
        email_html_body += "</ul>"
    
    send_email_report(email_subject, email_html_body)
    # ---
    
    # --- Update Google Sheet ---
    try:
        gspread_client, _ = get_google_services()
        spreadsheet = gspread_client.open_by_url(GOOGLE_SHEET_URL)
        
        if user_data['submission_type'] == "Inbound":
            worksheet_name = "Inbound Submissions 20/5/2025"
        else: # Outbound
            worksheet_name = "Outbound Submissions 20/5/2025"
        
        try:
            sheet = spreadsheet.worksheet(worksheet_name)
        except gspread.exceptions.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title=worksheet_name, rows=100, cols=20)
            headers = [
                "Timestamp", "Email Address", "Container/PO Number", 
                "Number of Pallets/ Carton", "Damage notes / Remarks", 
                "Photo Option", "Additional Photo Option", 
                "Additional Photo Option #2", "All Photo Links"
            ]
            sheet.append_row(headers)
            logger.info(f"Created new worksheet '{worksheet_name}' with headers.")

        photo_col_f = drive_photo_links[0] if len(drive_photo_links) > 0 else ""
        photo_col_g = drive_photo_links[1] if len(drive_photo_links) > 1 else ""
        photo_col_h = "\n".join(drive_photo_links[2:]) if len(drive_photo_links) > 2 else ""

        sheet_row = [
            formatted_timestamp,
            f"{user.full_name} (@{user.username})",
            user_data['container_number'],
            user_data['quantity'],
            user_data['notes'],
            photo_col_f, photo_col_g, photo_col_h, ""
        ]
        sheet.append_row(sheet_row)
        logger.info(f"Google Sheet '{worksheet_name}' updated successfully.")
    except Exception as e:
        logger.error("Failed to update Google Sheet:")
        logger.error(traceback.format_exc())

    await update.message.reply_text("Submission complete!")

    # --- Send to Admin Group ---
    final_report_markdown = (
        f"📝 *New Logistics Report*\n\n"
        f"*Timestamp:* {formatted_timestamp}\n"
        f"*Submitted by:* {user.full_name} (@{user.username})\n"
        f"*Container/Reference:* `{user_data['container_number']}`\n"
        f"*Pallet/Carton Count:* `{user_data['quantity']}`\n"
        f"*Damage Notes/Remarks:*\n`{user_data['notes']}`"
    )

    if TARGET_CHAT_ID:
        try:
            photo_ids = [pf.file_id for pf in user_data.get("photos", [])]
            if photo_ids:
                media_group = [InputMediaPhoto(media=pid) for pid in photo_ids]
                media_group[0] = InputMediaPhoto(media=photo_ids[0], caption=final_report_markdown, parse_mode='Markdown')
                for i in range(0, len(media_group), 10):
                    await context.bot.send_media_group(chat_id=TARGET_CHAT_ID, media=media_group[i:i + 10])
            else:
                await context.bot.send_message(chat_id=TARGET_CHAT_ID, text=final_report_markdown, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Failed to send to TARGET_CHAT_ID: {e}")
            # Add user-facing error message for debugging
            error_message = f"Failed to send report to the admin group. Please notify an admin.\n\n*Error details:* `{e}`"
            await update.message.reply_text(error_message, parse_mode='Markdown')

    # --- Offer to start a new submission ---
    keyboard = [[InlineKeyboardButton("Start New Submission", callback_data="new_submission")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Ready for the next one?", reply_markup=reply_markup)

    user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the current operation."""
    context.user_data.clear()
    await update.message.reply_text("Submission cancelled.")
    return ConversationHandler.END


def main() -> None:
    """Sets up and runs the bot."""
    application = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start_submission),
            CallbackQueryHandler(start_submission_from_button, pattern="^new_submission$")
        ],
        states={
            SELECT_TYPE: [CallbackQueryHandler(get_submission_type)],
            GET_ALL_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_all_text)],
            GET_PHOTOS: [
                MessageHandler(filters.PHOTO, get_photos),
                MessageHandler(filters.Regex("^Done Uploading$"), photos_done),
            ],
            CONFIRM_SUBMISSION: [
                MessageHandler(filters.Regex("^Confirm & Submit$"), submit),
                MessageHandler(filters.Regex("^Cancel$"), cancel),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("help", start))
    application.add_handler(conv_handler)
    
    print("Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()
