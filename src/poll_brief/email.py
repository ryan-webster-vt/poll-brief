"""SES multipart email delivery."""


def send_digest(client, sender, recipient, subject, plain, html):
    response = client.send_email(
        Source=sender,
        Destination={"ToAddresses": [recipient]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {
                "Text": {"Data": plain, "Charset": "UTF-8"},
                "Html": {"Data": html, "Charset": "UTF-8"},
            },
        },
    )
    if not response.get("MessageId"):
        raise RuntimeError("SES did not confirm acceptance")
    return response["MessageId"]
