"""Gateway-only padded AEAD records. Cover reads are not ORAM."""
import json
import os
from pathlib import Path
import re
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RECORD_BYTES = 32768
PLAIN_BYTES = RECORD_BYTES - 12 - 16


class PayloadVault:
    def __init__(self, directory, key):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.cipher = AESGCM(key)
        self.dummy = self.directory / "cover.enc"
        if not self.dummy.exists():
            self._write(self.dummy, self.pack(None, b"cover-v1"))

    def pack(self, value, associated):
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > PLAIN_BYTES - 4:
            raise ValueError("Vault record capacity exceeded")
        plain = len(encoded).to_bytes(4, "big") + encoded
        plain += secrets.token_bytes(PLAIN_BYTES - len(plain))
        nonce = secrets.token_bytes(12)
        return nonce + self.cipher.encrypt(nonce, plain, associated)

    def unpack(self, blob, associated):
        if len(blob) != RECORD_BYTES:
            raise ValueError("Invalid vault record size")
        plain = self.cipher.decrypt(blob[:12], blob[12:], associated)
        size = int.from_bytes(plain[:4], "big")
        if size > PLAIN_BYTES - 4:
            raise ValueError("Invalid vault payload size")
        return json.loads(plain[4:4+size])

    def cover_read(self):
        # Exactly one fixed-size cover read per record read/write. This does not
        # hide filenames, counts, filesystem metadata, or host access patterns.
        blob = self.dummy.read_bytes()
        self.unpack(blob, b"cover-v1")

    @staticmethod
    def _write(path, blob):
        temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
        try:
            with temporary.open("xb") as stream:
                os.chmod(temporary, 0o600)
                stream.write(blob)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def binding(ref, role, run_id, owner, kind):
        if role not in ("red", "blue") or kind not in ("prompt", "output", "defense"):
            raise ValueError("Invalid vault binding")
        return json.dumps(["payload-v1", ref, role, run_id, owner, kind], separators=(",", ":")).encode()

    def put(self, value, *, role, run_id, owner, kind):
        ref = secrets.token_hex(16)
        self.cover_read()
        path = self.directory / (ref + ".enc")
        blob = self.pack(value, self.binding(ref, role, run_id, owner, kind))
        # Immutable opaque records need no replace/rename. The database receives
        # this reference only AFTER close; an interrupted write is an unlinked
        # orphan, never a published partial payload. Config updates stay atomic.
        created = False
        try:
            with path.open("xb") as stream:
                created = True
                os.chmod(path, 0o600)
                stream.write(blob)
        except BaseException:
            if created:
                path.unlink(missing_ok=True)
            raise
        return ref

    def get(self, ref, *, role, run_id, owner, kind):
        if not re.fullmatch(r"[a-f0-9]{32}", ref):
            raise ValueError("Invalid vault reference")
        self.cover_read()
        return self.unpack((self.directory / (ref + ".enc")).read_bytes(), self.binding(ref, role, run_id, owner, kind))
