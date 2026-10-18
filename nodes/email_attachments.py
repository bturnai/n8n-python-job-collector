"""Node "Csatolmanyok elokeszitese": turns optional e-mail attachments into files.

The e-mail webhook receives {to, subject, html, attachments}, where attachments
is an optional list of {filename, mimeType, content}. `content` is the file in
base64 text, because a JSON body cannot carry raw bytes.

n8n's e-mail node can only attach "binary" data, so every attachment is moved
from the JSON into the item's `binary` part under its own key (att0, att1, ...).
The e-mail node reads the list of these keys from `attachmentKeys`.
"""


def to_binary_entry(attachment, index):
    """One attachment in n8n's binary format.

    Example: {"filename": "cv.docx", "content": "UEsDB..."} ->
             {"data": "UEsDB...", "mimeType": "application/octet-stream", "fileName": "cv.docx"}
    """
    file_name = attachment.get("filename") or ("csatolmany_" + str(index))  # "attachment_<n>"
    mime_type = attachment.get("mimeType") or "application/octet-stream"  # "some binary file"
    return {"data": attachment["content"], "mimeType": mime_type, "fileName": file_name}


def main(items):
    output = []
    for item in items:
        # A copy of the request body, so that the original item is not modified.
        body = dict(item["json"].get("body") or {})

        attachments = body.pop("attachments", None)  # removes it from the body
        if not isinstance(attachments, list):
            attachments = []

        binary = {}
        for index, attachment in enumerate(attachments):
            # Skip empty or malformed entries; the key keeps the attachment's
            # original position.
            if not isinstance(attachment, dict) or not attachment.get("content"):
                continue
            binary["att" + str(index)] = to_binary_entry(attachment, index)

        output.append({
            "json": {"body": body, "attachmentKeys": ",".join(binary.keys())},
            "binary": binary,
        })
    return output
