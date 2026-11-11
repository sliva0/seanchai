"""Source documents to `.dad`.

`tgpp_docx` reads a 3GPP or oneM2M `.docx` and needs `seanchai[extract]`, so
nothing here imports it. `rfc_text` reads RFC plain text and `transcription` a
hand transcription; neither needs an extra. `sources` holds the input patches,
exclusions and quirks they read, and `errors` what they raise. Each module's
`__all__` is what it offers.
"""
