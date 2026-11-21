"""Password storage: crack the hashes from a stolen database (Lecture 4).

The attacker is assumed to have a copy of the database file already
(for example through SQL injection). We read the local files to play that.
"""
import hashlib
import time

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

from common import COMMON_PASSWORDS, NAIVE_DB, SECURE_DB, db_rows, report


def run():
    with open(COMMON_PASSWORDS, encoding="utf-8") as f:
        wordlist = [line.strip() for line in f if line.strip()]

    # Naive: unsalted MD5 - look every word up.
    start = time.time()
    cracked = []
    for row in db_rows(NAIVE_DB, "SELECT username, password_md5 FROM users"):
        for word in wordlist:
            if hashlib.md5(word.encode()).hexdigest() == row["password_md5"]:
                cracked.append(f"{row['username']}:{word}")
    naive_time = time.time() - start

    # How fast is MD5 vs Argon2id on this machine?
    start = time.time()
    for i in range(200000):
        hashlib.md5(str(i).encode()).hexdigest()
    md5_speed = 200000 / (time.time() - start)

    ph = PasswordHasher()
    found = []
    start = time.time()
    hashes = db_rows(SECURE_DB, "SELECT username, password_hash FROM users WHERE username = 'shopper'")
    for row in hashes:
        for word in wordlist:
            try:
                ph.verify(row["password_hash"], word)
                found.append(f"{row['username']}:{word}")
            except VerificationError:
                pass
    argon_speed = len(wordlist) / (time.time() - start)

    return report("Password storage", bool(cracked),
                  f"cracked {', '.join(cracked)} from MD5 in {naive_time:.3f}s",
                  not found,
                  f"Argon2id+salt: {len(found)}/{len(wordlist)} guesses matched; "
                  f"~{argon_speed:.0f} guesses/s vs ~{md5_speed / 1e6:.1f} million/s for MD5")


if __name__ == "__main__":
    run()
