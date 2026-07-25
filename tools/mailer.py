"""Gmail SMTP로 PDF 리포트를 첨부해서 네이버 메일로 발송한다."""
import os
import smtplib
from email.message import EmailMessage
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def send_report_email(pdf_path, subject, body_text, recipient=None):
    recipient = recipient or os.environ["REPORT_RECIPIENT_EMAIL"]
    sender = os.environ["GMAIL_ADDRESS"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(body_text)

    with open(pdf_path, "rb") as f:
        msg.add_attachment(
            f.read(), maintype="application", subtype="pdf",
            filename=os.path.basename(pdf_path),
        )

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
        server.login(sender, app_password)
        server.send_message(msg)


if __name__ == "__main__":
    send_report_email(
        os.path.join(os.path.dirname(__file__), "..", ".tmp", "sample_report.pdf"),
        subject="[테스트] 건강 콘텐츠 트렌드 리포트",
        body_text="테스트 발송입니다.",
    )
    print("발송 완료")
