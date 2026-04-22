from app.services.file_service import ALLOWED_EXTENSIONS, EXT_TO_FILE_TYPE, MIME_TO_FILE_TYPE


def test_drawio_extension_is_uploadable() -> None:
    assert ".drawio" in ALLOWED_EXTENSIONS
    assert EXT_TO_FILE_TYPE[".drawio"] == "document"


def test_xml_mime_types_map_to_document() -> None:
    assert MIME_TO_FILE_TYPE["application/xml"] == "document"
    assert MIME_TO_FILE_TYPE["text/xml"] == "document"