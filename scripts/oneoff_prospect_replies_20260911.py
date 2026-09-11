import imaplib
import os
import re
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

USERNAME = os.environ["CASE_HUNTER_GMAIL_USERNAME"].strip()
PASSWORD = os.environ["CASE_HUNTER_GMAIL_APP_PASSWORD"].strip()


def _sent_mailbox(imap):
    status, boxes = imap.list()
    if status != "OK":
        return None
    for raw in boxes or []:
        text = raw.decode("utf-8", errors="replace")
        if "\\Sent" in text:
            quoted = re.findall(r'"([^"]+)"', text)
            if quoted:
                return quoted[-1]
    return None


def _already_sent(marker):
    with imaplib.IMAP4_SSL("imap.gmail.com", 993) as imap:
        imap.login(USERNAME, PASSWORD)
        mailbox = _sent_mailbox(imap)
        if not mailbox:
            return False
        status, _ = imap.select(f'"{mailbox}"', readonly=True)
        if status != "OK":
            return False
        status, data = imap.search(
            None,
            "HEADER",
            "X-Case-Hunter-Reply",
            f'"{marker}"',
        )
        return status == "OK" and bool(data and data[0].strip())


def _send(marker, to, subject, body, cc=None):
    if _already_sent(marker):
        print(f"SKIP_ALREADY_SENT {marker}")
        return

    msg = EmailMessage()
    msg["From"] = formataddr(("Nicolás Vega", USERNAME))
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid()
    msg["X-Case-Hunter-Reply"] = marker
    msg.set_content(body)

    recipients = [to] + ([cc] if cc else [])
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(USERNAME, PASSWORD)
        smtp.send_message(msg, from_addr=USERNAME, to_addrs=recipients)
    print(f"SENT {marker} {to}")


_send(
    "hmv-20260911-v1",
    "julio@jmarinpropiedades.cl",
    "Re: Antecedentes públicos sobre pagos del proyecto Plaza Domingo Espiñeira",
    """Hola Julio,

Gracias por responder. Estudio Ingeniería Informática y estoy desarrollando de forma independiente Case Hunter, una herramienta para detectar y ordenar antecedentes públicos relacionados con contratos, pagos y cierres administrativos con organismos públicos.

La idea es identificar casos que todavía pueden requerir seguimiento, ordenar la cronología y señalar cuál parece ser la siguiente gestión útil. No represento a la municipalidad ni a una empresa de cobranza.

En el caso de HMV encontré antecedentes públicos suficientes para preparar una síntesis breve del proyecto Plaza Domingo Espiñeira y del estado de los pagos que aparecen en esos registros.

Si te parece, te la envío por este mismo medio.

Saludos,
Nicolás Vega""",
    cc="contacto@chmv.cl",
)

_send(
    "alembic-20260911-v1",
    "cobranzachile@alembic.co.in",
    "Re: Antecedente público sobre deuda y despachos",
    """Estimados,

Gracias por responder. Les comparto la síntesis del antecedente público que encontré.

Fuente: Registro de Audiencias de la Ley del Lobby, identificador MU271AW2265687, audiencia del 28 de julio de 2026.

En el registro se consigna una reunión vinculada a Alembic Pharmaceuticals por regularización de deuda vencida. El antecedente señala que, según el registro del área contable, se reconocía una deuda de arrastre por $5.178.271. También indica que el municipio se encontraba bloqueado para nuevos despachos desde diciembre de 2025 y que el Director Comunal de Salud enviaría el detalle de la deuda a la administración municipal para solicitar recursos destinados al pago.

Fuente pública:
https://www.leylobby.gob.cl/instituciones/MU271/audiencias/2026/800758/936913

Esto refleja únicamente lo publicado en ese registro y no permite confirmar por sí solo el estado actual del pago. Si el asunto sigue pendiente, puedo ordenar los hitos posteriores y revisar qué gestión pública aparece como siguiente paso.

¿Sigue pendiente actualmente o ya fue regularizado?

Saludos,
Nicolás Vega""",
)
